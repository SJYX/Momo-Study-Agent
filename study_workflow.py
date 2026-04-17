import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from config import AI_PROVIDER, BATCH_SIZE, DRY_RUN
from core.db_manager import (
    get_processed_ids_in_batch,
    save_ai_word_notes_batch,
    save_ai_batch,
    mark_processed_batch,
    clean_for_maimemo,
)
from sync_manager import SyncManager


class StudyWorkflow:
    """核心业务层：单词处理流水线、缓存判重、AI 调度、DB 写入与同步任务投递。"""

    def __init__(self, logger, ai_client, momo_api, ui_manager):
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

    @staticmethod
    def _format_words_preview(words, limit=20):
        """将单词列表压缩为日志友好的预览字符串。"""
        if not words:
            return ""
        if len(words) <= limit:
            return ", ".join(words)
        return f"{', '.join(words[:limit])} ... (+{len(words) - limit})"

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
                continue

            payload = ai_map[spell]
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

        if DRY_RUN and dry_run_processed_items:
            marked_ok = mark_processed_batch(dry_run_processed_items)
            if not marked_ok:
                self.logger.warning("⚠️ Dry-run 批量处理标记入队失败（写队列可能已满）")
            else:
                now = time.time()
                for voc_id, _spell in dry_run_processed_items:
                    self._session_processed_ids.add(str(voc_id))
                    self._processed_cache[str(voc_id)] = {"processed": True, "ts": now}

        if pending_sync_items:
            if not saved_ok:
                self.logger.warning("⚠️ 落库失败，取消本批次同步入队")
                return
            for item in pending_sync_items:
                self.logger.info(f"[{item['num']}/{item['total']}] ✅ {item['spell']} 已加入收尾同步队列")
                self.sync_manager.queue_maimemo_sync(
                    item["voc_id"],
                    item["spell"],
                    item["brief"],
                    item["tags"],
                    force_sync=True,  # 内存信任：刚生成结果直接同步，跳过写后即读
                )

    def _run_ai_batch(self, batch_no, total_batches, batch_spells):
        """在线程池工作线程中执行单个 AI 批次，输出真实开始/完成日志。"""
        self.logger.info(
            f"[AI] 批次 {batch_no}/{total_batches} 开始执行: {self._format_words_preview(batch_spells)}"
        )
        results, metadata = self.ai_client.generate_mnemonics(batch_spells)
        return results, metadata

    def process_word_list(self, word_list, name):
        if not word_list:
            self.logger.info(f"{name} 无需处理")
            return

        all_voc_ids = [str(w.get("voc_id")) for w in word_list]
        processed_ids = self._get_processed_ids_cached(all_voc_ids)

        pending_words = [w for w in word_list if str(w.get("voc_id")) not in processed_ids]
        skipped_words = [w for w in word_list if str(w.get("voc_id")) in processed_ids]

        self.logger.info(
            f"[去重] {name}: 总计 {len(word_list)} 词，已处理跳过 {len(skipped_words)} 词，待处理 {len(pending_words)} 词"
        )
        if skipped_words:
            skipped_spells = [str(w.get("voc_spelling", "")) for w in skipped_words if w.get("voc_spelling")]
            if skipped_spells:
                self.logger.info(
                    f"[去重] 本轮跳过单词: {self._format_words_preview(skipped_spells)}"
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

        with ThreadPoolExecutor(max_workers=ai_workers) as executor:
            futures = []
            start_pos = 0
            for i in range(0, total_pending, BATCH_SIZE):
                batch = pending_words[i : i + BATCH_SIZE]
                batch_spells = [w["voc_spelling"] for w in batch]
                batch_no = (i // BATCH_SIZE) + 1

                self.logger.info(
                    f"[AI] 批次 {batch_no}/{total_batches} 已入队: {self._format_words_preview(batch_spells)}"
                )
                fut = executor.submit(self._run_ai_batch, batch_no, total_batches, batch_spells)
                futures.append((fut, batch, start_pos, batch_no, batch_spells))
                start_pos += len(batch)

            for fut, batch, start_pos, batch_no, batch_spells in futures:
                results, metadata = fut.result()
                if not results:
                    self.logger.warning(
                        f"⚠️ AI 批次 {batch_no}/{total_batches} 返回空结果，已跳过: {self._format_words_preview(batch_spells)}"
                    )
                    continue

                self.logger.info(
                    f"[AI] 批次 {batch_no}/{total_batches} 完成，返回 {len(results)} 条结果"
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

        self.sync_manager.flush_pending_syncs(name)

    def shutdown(self):
        self.sync_manager.shutdown()
