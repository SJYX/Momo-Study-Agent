"""
core/study_workflow.py: 主学习流程与任务编排，负责单词处理流水线与 AI 调度。
"""

import os
import uuid
import time
from concurrent.futures import ThreadPoolExecutor

from config import AI_PROVIDER, BATCH_SIZE, DRY_RUN
from database.momo_words import get_local_word_note, save_ai_batch, save_ai_word_notes_batch
from database.utils import clean_for_maimemo
from core.sync_manager import SyncManager
from core.word_service import WordService


class StudyWorkflow:
    """核心业务层：单词处理流水线、AI 调度、DB 写入与同步任务投递。"""

    def __init__(self, logger, ai_client, momo_api, ui_manager, db_path=None):
        self.logger = logger
        self.ai_client = ai_client
        self.momo = momo_api
        self.ui = ui_manager
        self.db_path = db_path

        self.word_service = WordService(logger=logger)

        self.sync_manager = SyncManager(
            logger=self.logger,
            momo_api=self.momo,
            db_path=db_path,
        )

    @staticmethod
    def _format_words_preview(words, limit=20):
        """将单词列表压缩为日志友好的预览字符串。"""
        if not words:
            return ""

        safe_words = [str(word) for word in words if word is not None]
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

        for idx, word in enumerate(batch_words):
            num = current_start + idx + 1

            if hasattr(word, "spelling"):
                spell = word.spelling.lower()
                voc_id = str(word.voc_id)
                original_meanings = getattr(word, "meanings", None)
                review_count = getattr(word, "review_count", None)
                short_term_familiarity = getattr(word, "short_term_familiarity", None)
            else:
                spell = word["voc_spelling"].lower()
                voc_id = str(word["voc_id"])
                original_meanings = word.get("voc_meanings") or word.get("voc_meaning") or word.get("meanings")
                review_count = word.get("review_count")
                short_term_familiarity = word.get("short_term_familiarity")

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

            metadata = {
                "batch_id": batch_id,
                "original_meanings": original_meanings,
                "content_origin": "ai_generated",
                "content_source_db": None,
                "content_source_scope": None,
                "maimemo_context": {
                    "review_count": review_count,
                    "short_term_familiarity": short_term_familiarity,
                },
            }
            notes_to_save.append({"voc_id": voc_id, "payload": payload, "metadata": metadata})

            if DRY_RUN:
                dry_run_processed_items.append((voc_id, spell))
            else:
                brief = clean_for_maimemo(payload.get("basic_meanings", ""))
                pending_sync_items.append(
                    {
                        "num": num,
                        "total": total,
                        "voc_id": voc_id,
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
            from core.word_models import WordItem

            dry_run_items = [WordItem(voc_id=voc_id, spelling=spell) for voc_id, spell in dry_run_processed_items]
            marked_ok = self.word_service.mark_completed(dry_run_items, batch_id=batch_id)
            if not marked_ok:
                self.logger.warning("⚠️ Dry-run 批量处理标记入队失败（写队列可能已满）")

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
                    force_sync=True,
                )

    def _run_ai_batch(self, batch_no, total_batches, batch_spells):
        """执行单批 AI 处理。"""
        self.logger.info(
            f"[AI] 批次 {batch_no}/{total_batches} 开始调用 AI（{len(batch_spells)} 词）",
            module="study_workflow",
        )
        try:
            results, metadata = self.ai_client.generate_mnemonics(batch_spells)
            self.logger.info(
                f"[AI] 批次 {batch_no}/{total_batches} 返回 {len(results or [])} 条结果",
                module="study_workflow",
            )
            return results or [], metadata or {}
        except Exception as exc:
            self.logger.warning(f"⚠️ AI 批次 {batch_no}/{total_batches} 处理失败: {exc}")
            return [], {}

    def process_word_list(self, word_list, name):
        self.logger.info(f"[Pipeline] {name} 开始处理，原始列表 {len(word_list)} 词", module="study_workflow")

        if not word_list:
            self.logger.info(f"{name} 无需处理")
            return


        normalized_items, discarded_count = self.word_service.normalize_cloud_items(word_list)
        if not normalized_items:
            self.logger.info(f"{name} 过滤后无可处理有效单词 (丢弃 {discarded_count} 词)")
            return

        # 6.2: 记录进度快照以供薄弱词筛选使用
        try:
            from database.progress_repo import log_progress_snapshots

            # 如果是 Warmup 任务或 review_count 全为 0，尝试回填 study_count
            all_zero = all((item.review_count or 0) == 0 for item in normalized_items)
            if all_zero:
                try:
                    from datetime import datetime
                    import threading
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    # 查询今日已学记录（覆盖今日前后的窗口以防时区差异）
                    # 用 daemon 线程 + join(timeout) 超时保护：API 不可用时最多等 10 秒
                    self.logger.info(f"[Pipeline] {name} review_count 全为 0，正在回填 study_count...", module="study_workflow")
                    _backfill_start = time.time()
                    self.logger.info(f"[Pipeline] {name} 回填步骤 1/3: 调用墨墨 API query_study_records({today_str})...", module="study_workflow")

                    _api_result = [None]
                    _api_error = [None]

                    def _call_api():
                        try:
                            _api_result[0] = self.momo.query_study_records(today_str, today_str)
                        except Exception as exc:
                            _api_error[0] = exc

                    api_thread = threading.Thread(target=_call_api, daemon=True)
                    api_thread.start()
                    api_thread.join(timeout=10)

                    if api_thread.is_alive():
                        self.logger.warning(f"⚠️ query_study_records 超时(10s)，跳过 study_count 回填", module="study_workflow")
                        records_res = None
                    elif _api_error[0] is not None:
                        raise _api_error[0]
                    else:
                        records_res = _api_result[0]
                        self.logger.info(f"[Pipeline] {name} 回填步骤 1/3: API 返回，耗时 {int((time.time()-_backfill_start)*1000)}ms", module="study_workflow")

                    if records_res and records_res.get("data", {}).get("records"):
                        records = records_res["data"]["records"]
                        self.logger.info(f"[Pipeline] {name} 回填步骤 2/3: API 返回 {len(records)} 条学习记录，开始构建 count_map...", module="study_workflow")
                        count_map = {str(r.get("voc_id")): int(r.get("study_count", 0)) for r in records}
                        matched = 0
                        for item in normalized_items:
                            if item.voc_id in count_map:
                                item.review_count = count_map[item.voc_id]
                                matched += 1
                        self.logger.info(f"[Pipeline] {name} 回填步骤 3/3: 匹配到 {matched}/{len(normalized_items)} 个词的 study_count，耗时 {int((time.time()-_backfill_start)*1000)}ms", module="study_workflow")
                    elif records_res:
                        self.logger.warning(f"[Pipeline] {name} 回填: API 返回了数据但 records 为空", module="study_workflow")
                    else:
                        self.logger.warning(f"[Pipeline] {name} 回填: API 返回 None", module="study_workflow")
                except Exception as enrichment_err:
                    self.logger.warning(f"⚠️ 进度数据补全失败 (不影响主流程): {enrichment_err}")

                _backfill_elapsed = int((time.time() - _backfill_start) * 1000)
                self.logger.info(f"[Pipeline] {name} 回填 study_count 完成 ({_backfill_elapsed}ms)", module="study_workflow")

            # 将 WordItem 转换为 log_progress_snapshots 预期的 dict 格式 (ProgressSnapshot)
            snapshots = [
                {
                    "voc_id": item.voc_id,
                    "short_term_familiarity": item.short_term_familiarity,
                    "review_count": item.review_count,
                }
                for item in normalized_items
            ]
            count = log_progress_snapshots(snapshots)
            if count > 0:
                self.logger.info(f"✅ 成功记录 {count} 个单词的进度历史快照 (总计 {len(snapshots)} 词)")

        except Exception as e:
            self.logger.error(f"❌ 记录进度历史快照失败: {e}")

        self.logger.info(f"[Pipeline] {name} 进度快照阶段完成，准备初始化任务...", module="study_workflow")

        self.logger.info(
            f"[Pipeline] {name} 任务初始化，总计 {len(normalized_items)} 词（过滤脏数据 {discarded_count} 词）",
            extra={
                "event": "progress",
                "data": {"total": len(normalized_items), "discarded": discarded_count, "phase": "initializing"},
            },
        )



        self.logger.info(f"[Pipeline] {name} 正在查询单词状态库...")
        t_enrich_start = time.time()

        self.logger.info(f"[Pipeline] {name} 调用 enrich_with_states 前 (items={len(normalized_items)})", module="study_workflow")
        enriched = self.word_service.enrich_with_states(normalized_items, auto_backfill=True, db_path=self.db_path)
        self.logger.info(f"[Pipeline] {name} enrich_with_states 返回 (enriched={len(enriched)})", module="study_workflow")
        t_enrich_end = time.time()
        self.logger.info(f"[Profiling] {name} 状态增强耗时: {int((t_enrich_end - t_enrich_start)*1000)}ms")

        t_part_start = time.time()
        pending_items, processed_items = self.word_service.partition_by_processability(enriched)
        t_part_end = time.time()
        self.logger.info(f"[Profiling] {name} 任务分组耗时: {int((t_part_end - t_part_start)*1000)}ms")


        skipped_spells = [item.spelling for item in processed_items]
        self.logger.info(
            f"[去重] {name}: 总计 {len(normalized_items)} 词，已处理跳过 {len(processed_items)} 词，待处理 {len(pending_items)} 词"
        )

        if skipped_spells:
            self.logger.info(f"[去重] 本轮跳过单词: {self._format_words_preview(skipped_spells)}")
            # B1 优化：使用批量查询替代循环查询 (避免 N+1 问题)
            processed_voc_ids = [item.voc_id for item in processed_items]
            notes_map = self.word_service.get_notes_in_batch(processed_voc_ids, db_path=self.db_path)
            
            rows = []
            for item in processed_items:
                phase = "skipped"
                status = "done"
                reason = ""

                try:
                    note = notes_map.get(str(item.voc_id))
                    sync_status = int((note or {}).get("sync_status", 0) or 0)
                    if sync_status == 0:
                        phase = "sync_pending"
                        status = "pending"
                        reason = "本地已生成，待上传同步"
                    elif sync_status == 2:
                        phase = "sync_conflict"
                        status = "warning"
                        reason = "云端释义冲突，待处理"
                    elif sync_status == 5:
                        phase = "sync_failed"
                        status = "error"
                        reason = (note or {}).get("match_reason") or "上传失败"
                except Exception:
                    pass

                row = {"item_id": item.spelling, "status": status, "phase": phase}
                if reason:
                    row["error"] = reason
                rows.append(row)

            self.logger.info(
                f"[RowStatus] 本轮跳过单词状态回填 ({len(rows)} 词)",
                extra={"event": "row_status", "data": {"rows": rows}},
            )

        if not pending_items:
            self.logger.info("✨ 无需调用 AI。")
            return

        total_pending = len(pending_items)
        ai_workers = max(1, int(os.getenv("AI_PIPELINE_WORKERS", "2")))
        total_batches = (total_pending + BATCH_SIZE - 1) // BATCH_SIZE

        self.logger.info(
            f"[AI] {name} 开始处理：{total_pending} 词，批次大小 {BATCH_SIZE}，并发 {ai_workers}，共 {total_batches} 批"
        )

        executor = ThreadPoolExecutor(max_workers=ai_workers)
        try:
            futures = []
            start_pos = 0
            for i in range(0, total_pending, BATCH_SIZE):
                batch = pending_items[i : i + BATCH_SIZE]
                batch_spells = [item.spelling for item in batch]
                batch_no = (i // BATCH_SIZE) + 1

                future = executor.submit(self._run_ai_batch, batch_no, total_batches, batch_spells)
                futures.append((future, batch, start_pos, batch_no, batch_spells))
                start_pos += len(batch)

            self.logger.info(
                f"[AI] {total_batches} 个 AI 处理批次已全部进入待处理队列。",
                extra={
                    "event": "batch_start",
                    "progress": {"total": total_pending, "batches": total_batches},
                },
            )

            for future, batch, start_pos, batch_no, batch_spells in futures:
                # 批次开始：发射 running 行状态，让前端知道当前处理哪个词
                running_rows = [{"item_id": s, "status": "running", "phase": f"ai_batch {batch_no}/{total_batches}"} for s in batch_spells]
                self.logger.info(
                    f"[RowStatus] 批次 {batch_no}/{total_batches} 开始处理: {self._format_words_preview(batch_spells)}",
                    extra={"event": "row_status", "data": {"rows": running_rows}},
                )

                results, metadata = future.result()
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

                batch_id = str(uuid.uuid4())
                ok = save_ai_batch(
                    {
                        "batch_id": batch_id,
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

                self._process_results(batch, results, start_pos, total_pending, batch_id)
        except KeyboardInterrupt:
            self.logger.warning("检测到中断，正在取消所有待处理的 AI 任务...")
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            executor.shutdown(wait=True)

        self.sync_manager.flush_pending_syncs(name)

    def shutdown(self):
        self.sync_manager.shutdown()