"""
core/study_workflow.py: 主学习流程与任务编排，负责单词处理流水线与 AI 调度。
"""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from config import AI_PROVIDER, BATCH_SIZE, DRY_RUN
from database.momo_words import (
    get_processed_ids_in_batch,
    get_progress_tracked_ids_in_batch,
    get_local_word_note,
    save_ai_word_notes_batch,
    save_ai_batch,
    mark_processed_batch,
)
from database.utils import clean_for_maimemo
from core.sync_manager import SyncManager


class StudyWorkflow:
    """核心业务层：单词处理流水线、缓存判重、AI 调度、DB 写入与同步任务投递。"""

    def __init__(self, logger, ai_client, momo_api, ui_manager, db_path=None):
        self.logger = logger
        self.ai_client = ai_client
        self.momo = momo_api
        self.ui = ui_manager

        # 判重缓存（内存态）
        self._session_processed_ids = set()
        self._processed_cache = {}
        self._processed_cache_ttl_seconds = int(os.getenv("PROCESSED_CACHE_TTL_SECONDS", "900"))
        self._processed_cache_max_entries = int(os.getenv("PROCESSED_CACHE_MAX_ENTRIES", "50000"))

        self.sync_manager = SyncManager(
            logger=self.logger,
            momo_api=self.momo,
            on_mark_processed=self._mark_processed_with_cache,
            db_path=db_path,
        )

    def _prune_processed_cache(self):
        if len(self._processed_cache) <= self._processed_cache_max_entries:
            return
        overflow = len(self._processed_cache) - self._processed_cache_max_entries
        keys = sorted(self._processed_cache.items(), key=lambda kv: kv[1].get("ts", 0.0))
        for k, _ in keys[:overflow]:
            self._processed_cache.pop(k, None)

    def _get_processed_ids_cached(self, voc_ids):
        now = time.time()
        processed_ids = set()
        to_query = []

        for vid in voc_ids:
            v = str(vid)
            if v in self._session_processed_ids:
                processed_ids.add(v)
                continue

            cached = self._processed_cache.get(v)
            if cached and (now - cached.get("ts", 0.0) <= self._processed_cache_ttl_seconds):
                if cached.get("processed"):
                    processed_ids.add(v)
                continue

            to_query.append(v)

        if to_query:
            fresh_processed = set(get_processed_ids_in_batch(to_query))
            for v in to_query:
                is_processed = v in fresh_processed
                self._processed_cache[v] = {"processed": is_processed, "ts": now}
                if is_processed:
                    self._session_processed_ids.add(v)
            processed_ids.update(fresh_processed)
            self._prune_processed_cache()

        return processed_ids

    def _mark_processed_with_cache(self, voc_id, spelling):
        now = time.time()
        self._session_processed_ids.add(str(voc_id))
        self._processed_cache[str(voc_id)] = {"processed": True, "ts": now}

    def _recover_processed_from_local_notes(self, pending_words):
        """对历史遗留数据做自愈：若本地已有笔记但缺少 processed 标记，则回填。"""
        if not pending_words:
            return set()

        recovered = []
        for w in pending_words:
            vid = str(w.get("voc_id") or "")
            if not vid:
                continue

            note = get_local_word_note(vid)
            if not note:
                continue

            has_note_content = bool(
                str(note.get("basic_meanings") or "").strip()
                or str(note.get("raw_full_text") or "").strip()
                or str(note.get("memory_aid") or "").strip()
            )
            if not has_note_content:
                continue

            spelling = str(note.get("spelling") or w.get("voc_spelling") or "")
            recovered.append((vid, spelling, str(w.get("voc_spelling") or spelling or vid)))

        if not recovered:
            return set()

        mark_processed_batch([(vid, spelling) for vid, spelling, _ in recovered])

        now = time.time()
        recovered_ids = set()
        recovered_spells = []
        for vid, _, spell_preview in recovered:
            recovered_ids.add(vid)
            self._session_processed_ids.add(vid)
            self._processed_cache[vid] = {"processed": True, "ts": now}
            recovered_spells.append(spell_preview)

        self.logger.info(f"[去重] 自愈回填 processed 标记: {len(recovered_ids)} 词")
        self.logger.info(f"[去重] 自愈回填单词: {self._format_words_preview(recovered_spells)}")

        return recovered_ids

    def _recover_processed_from_progress_history(self, pending_words):
        """本地兜底：如果存在学习进度历史，也回填 processed 标记。"""
        if not pending_words:
            return set()

        pending_ids = [str(w.get("voc_id") or "") for w in pending_words if w.get("voc_id")]
        if not pending_ids:
            return set()

        tracked_ids = get_progress_tracked_ids_in_batch(pending_ids)
        if not tracked_ids:
            return set()

        items = []
        spell_preview = []
        for w in pending_words:
            vid = str(w.get("voc_id") or "")
            if vid and vid in tracked_ids:
                spell = str(w.get("voc_spelling") or "")
                items.append((vid, spell))
                spell_preview.append(spell or vid)

        if not items:
            return set()

        mark_processed_batch(items)

        now = time.time()
        recovered_ids = set()
        for vid, _ in items:
            recovered_ids.add(vid)
            self._session_processed_ids.add(vid)
            self._processed_cache[vid] = {"processed": True, "ts": now}

        self.logger.info(f"[去重] 进度历史回填 processed 标记: {len(recovered_ids)} 词")
        self.logger.info(f"[去重] 进度历史回填单词: {self._format_words_preview(spell_preview)}")

        return recovered_ids

    @staticmethod
    def _format_words_preview(words, limit=20):
        """将单词列表压缩为日志友好的预览字符串。"""
        if not words:
            return ""
        #  defensive: ensure all items are strings
        safe_words = [str(w) for w in words if w is not None]
        if not safe_words:
            return "[empty]"
            
        if len(safe_words) <= limit:
            return ", ".join(safe_words)
        return f"{', '.join(safe_words[:limit])} ... (+{len(safe_words) - limit})"

    def _process_results(self, batch_words, ai_results, current_start, total, batch_id):
        ai_map = {item["spelling"].lower(): item for item in ai_results}
        notes_to_save = []
        pending_sync_items = []
        dry_run_processed_items = []

        for idx, w in enumerate(batch_words):
            num = current_start + idx + 1
            spell = w["voc_spelling"].lower()
            vid = str(w["voc_id"])

            if spell not in ai_map:
                self.logger.warning(f"{spell} 结果缺失")
                self.logger.info(
                    f"[RowStatus] {spell} 处理失败：结果缺失",
                    extra={
                        "event": "row_status",
                        "data": {
                            "rows": [
                                {
                                    "item_id": spell,
                                    "status": "error",
                                    "phase": "ai_result",
                                    "error": "AI 返回缺失该单词结果",
                                }
                            ]
                        },
                    },
                )
                continue

            payload = ai_map[spell]
            self.logger.info(
                f"[RowStatus] {spell} AI 处理完成",
                extra={
                    "event": "row_status",
                    "data": {
                        "rows": [
                            {
                                "item_id": spell,
                                "status": "running",
                                "phase": "ai_done",
                            }
                        ]
                    },
                },
            )
            meta = {
                "batch_id": batch_id,
                "original_meanings": w.get("voc_meanings") or w.get("voc_meaning") or w.get("meanings"),
                "content_origin": "ai_generated",
                "content_source_db": None,
                "content_source_scope": None,
                "maimemo_context": {
                    "review_count": w.get("review_count"),
                    "short_term_familiarity": w.get("short_term_familiarity"),
                },
            }
            notes_to_save.append({"voc_id": vid, "payload": payload, "metadata": meta})

            if DRY_RUN:
                dry_run_processed_items.append((vid, spell))
            else:
                brief = clean_for_maimemo(payload.get("basic_meanings", ""))
                pending_sync_items.append(
                    {
                        "num": num,
                        "total": total,
                        "voc_id": vid,
                        "spell": spell,
                        "brief": brief,
                        "tags": ["雅思"],
                    }
                )

        saved_ok = True
        if notes_to_save:
            saved_ok = save_ai_word_notes_batch(notes_to_save)
            if not saved_ok:
                self.logger.warning("⚠️ 批量落库入队失败（写队列可能已满）")

        if dry_run_processed_items:
            marked_ok = mark_processed_batch(dry_run_processed_items)
            if not marked_ok:
                self.logger.warning("⚠️ Dry-run 批量处理标记入队失败（写队列可能已满）")
        
        # 无论是否是 DRY_RUN，只要结果已生成并投递保存，立即更新内存缓存
        # 这样在后续批次（或同一会话的重复请求）中可以立即跳过
        now = time.time()
        for data in notes_to_save:
            vid = str(data["voc_id"])
            self._session_processed_ids.add(vid)
            self._processed_cache[vid] = {"processed": True, "ts": now}

        if pending_sync_items:
            if not saved_ok:
                self.logger.warning("⚠️ 落库失败，取消本批次同步入队")
                return
            for item in pending_sync_items:
                self.sync_manager.queue_maimemo_sync(
                    item["voc_id"],
                    item["spell"],
                    item["brief"],
                    item["tags"],
                    force_sync=True,  # 内存信任：刚生成结果直接同步，跳过写后即读
                )
                self.logger.info(
                    f"[RowStatus] {item['spell']} 已入同步队列",
                    extra={
                        "event": "row_status",
                        "data": {
                            "rows": [
                                {
                                    "item_id": item["spell"],
                                    "status": "done",
                                    "phase": "sync_queued",
                                }
                            ]
                        },
                    },
                )
            
            # 汇总打印同步入队信息，避免 200+ 词刷屏
            sync_spells = [item["spell"] for item in pending_sync_items]
            self.logger.info(
                f"[Pipeline] {self._format_words_preview(sync_spells)} - 3. 已投递本地数据库及云端同步队列"
            )

    def _run_ai_batch(self, batch_no, total_batches, batch_spells):
        self.logger.info(
            f"[RowStatus] 批次开始",
            extra={
                "event": "row_status",
                "data": {
                    "rows": [
                        {"item_id": str(spell).lower(), "status": "running", "phase": "ai_request"}
                        for spell in batch_spells
                    ]
                },
            },
        )
        self.logger.info(
            f"[Pipeline] {self._format_words_preview(batch_spells)} - 1. 开始请求 AI 助记 (批次 {batch_no}/{total_batches})"
        )
        results, metadata = self.ai_client.generate_mnemonics(batch_spells)
        return results, metadata

    def process_word_list(self, word_list, name):
        if not word_list:
            self.logger.info(f"{name} 无需处理")
            return

        # 预过滤：跳过 voc_id 或拼写缺失的脏数据
        word_list = [w for w in word_list if w.get("voc_id") and w.get("voc_spelling")]
        if not word_list:
            self.logger.info(f"{name} 过滤后无可处理有效单词")
            return

        all_voc_ids = [str(w.get("voc_id")) for w in word_list]
        processed_ids = self._get_processed_ids_cached(all_voc_ids)

        pending_words = [w for w in word_list if str(w.get("voc_id")) not in processed_ids]
        skipped_words = [w for w in word_list if str(w.get("voc_id")) in processed_ids]

        if pending_words:
            recovered_ids = self._recover_processed_from_progress_history(pending_words)
            if recovered_ids:
                pending_words = [w for w in pending_words if str(w.get("voc_id")) not in recovered_ids]
                skipped_words.extend([w for w in word_list if str(w.get("voc_id")) in recovered_ids])

        if pending_words:
            recovered_ids = self._recover_processed_from_local_notes(pending_words)
            if recovered_ids:
                pending_words = [w for w in pending_words if str(w.get("voc_id")) not in recovered_ids]
                skipped_words.extend([w for w in word_list if str(w.get("voc_id")) in recovered_ids])

        self.logger.info(
            f"[去重] {name}: 总计 {len(word_list)} 词，已处理跳过 {len(skipped_words)} 词，待处理 {len(pending_words)} 词"
        )
        if skipped_words:
            skipped_spells = [str(w.get("voc_spelling", "")) for w in skipped_words if w.get("voc_spelling")]
            if skipped_spells:
                self.logger.info(
                    f"[去重] 本轮跳过单词: {self._format_words_preview(skipped_spells)}"
                )
                rows = []
                for word in skipped_words:
                    spell = str(word.get("voc_spelling", "") or "").strip().lower()
                    voc_id = str(word.get("voc_id", "") or "").strip()
                    if not spell:
                        continue

                    # 已处理并不一定代表已同步：根据本地 sync_status 区分显示。
                    # 0: 待同步  1: 已同步  2: 冲突
                    phase = "skipped"
                    status = "done"
                    reason = ""
                    try:
                        note = get_local_word_note(voc_id)
                        sync_status = int((note or {}).get("sync_status", 0) or 0)
                        if sync_status == 0:
                            phase = "sync_pending"
                            status = "pending"
                            reason = "本地已生成，待上传同步"
                        elif sync_status == 2:
                            phase = "sync_conflict"
                            status = "error"
                            reason = "云端释义冲突，待处理"
                    except Exception:
                        # 查询失败时保守展示为 skipped，避免中断主流程。
                        pass

                    row = {"item_id": spell, "status": status, "phase": phase}
                    if reason:
                        row["error"] = reason
                    rows.append(row)

                self.logger.info(
                    "[RowStatus] 本轮跳过单词状态回填",
                    extra={
                        "event": "row_status",
                        "data": {"rows": rows},
                    },
                )

        if not pending_words:
            self.logger.info("✨ 无需调用 AI。")
            return

        total_pending = len(pending_words)
        ai_workers = max(1, int(os.getenv("AI_PIPELINE_WORKERS", "2")))
        total_batches = (total_pending + BATCH_SIZE - 1) // BATCH_SIZE

        self.logger.info(
            f"[AI] {name} 开始处理：{total_pending} 词，批次大小 {BATCH_SIZE}，并发 {ai_workers}，共 {total_batches} 批"
        )

        try:
            with ThreadPoolExecutor(max_workers=ai_workers) as executor:
                futures = []
                start_pos = 0
                for i in range(0, total_pending, BATCH_SIZE):
                    batch = pending_words[i : i + BATCH_SIZE]
                    batch_spells = [w["voc_spelling"] for w in batch]
                    batch_no = (i // BATCH_SIZE) + 1

                    fut = executor.submit(self._run_ai_batch, batch_no, total_batches, batch_spells)
                    futures.append((fut, batch, start_pos, batch_no, batch_spells))
                    start_pos += len(batch)

                self.logger.info(
                    f"[AI] {total_batches} 个 AI 处理批次已全部进入待处理队列。",
                    extra={
                        "event": "batch_start",
                        "progress": {"current": 0, "total": total_pending, "batches": total_batches},
                    },
                )

                for fut, batch, start_pos, batch_no, batch_spells in futures:
                    results, metadata = fut.result()
                    if not results:
                        self.logger.warning(
                            f"⚠️ AI 批次 {batch_no}/{total_batches} 返回空结果，已跳过: {self._format_words_preview(batch_spells)}",
                            extra={
                                "event": "batch_error",
                                "progress": {"batch_no": batch_no, "total_batches": total_batches},
                            },
                        )
                        continue

                    self.logger.info(
                        f"[Pipeline] {self._format_words_preview(batch_spells)} - 2. AI 助记处理成功 (耗时: {metadata.get('total_latency_ms', 0)}ms，返回 {len(results)} 条)",
                        extra={
                            "event": "batch_done",
                            "progress": {
                                "batch_no": batch_no,
                                "total_batches": total_batches,
                                "words": len(batch),
                                "total": total_pending,
                            },
                        },
                    )

                    bid = str(uuid.uuid4())
                    ok = save_ai_batch(
                        {
                            "batch_id": bid,
                            "request_id": metadata.get("request_id"),
                            "ai_provider": AI_PROVIDER,
                            "model_name": self.ai_client.model_name,
                            "prompt_version": getattr(self.ai_client, "prompt_version", ""),
                            "batch_size": len(batch),
                            "total_latency_ms": metadata.get("total_latency_ms", 0),
                            "total_tokens": metadata.get("total_tokens", 0),
                            "finish_reason": metadata.get("finish_reason"),
                        }
                    )
                    if not ok:
                        self.logger.warning("⚠️ 批次元数据入队失败（写队列可能已满）")

                    self._process_results(batch, results, start_pos, total_pending, bid)
        except KeyboardInterrupt:
            self.logger.warning("检测到中断，正在取消所有待处理的 AI 任务...")
            # 立即关闭线程池，不等待排队任务，由 Python 3.9+ 的 cancel_futures 确保
            executor.shutdown(wait=False, cancel_futures=True)
            raise

        self.sync_manager.flush_pending_syncs(name)

    def shutdown(self):
        self.sync_manager.shutdown()
