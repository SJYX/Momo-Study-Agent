"""
core/study_workflow.py: 主学习流程与任务编排，负责单词处理流水线与 AI 调度。
"""

import os
import uuid
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

        self.word_service = WordService(logger=logger)

        self.sync_manager = SyncManager(
            logger=self.logger,
            momo_api=self.momo,
            on_mark_processed=self._mark_processed_for_sync,
            db_path=db_path,
        )

    def _mark_processed_for_sync(self, voc_id, spelling):
        """sync_manager 回调：当前由 WordService 负责状态管理。"""
        pass

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
        try:
            results, metadata = self.ai_client.generate_mnemonics(batch_spells)
            return results or [], metadata or {}
        except Exception as exc:
            self.logger.warning(f"⚠️ AI 批次 {batch_no}/{total_batches} 处理失败: {exc}")
            return [], {}

    def process_word_list(self, word_list, name):
        if not word_list:
            self.logger.info(f"{name} 无需处理")
            return

        normalized_items = self.word_service.normalize_cloud_items(word_list)
        if not normalized_items:
            self.logger.info(f"{name} 过滤后无可处理有效单词")
            return

        self.logger.info(
            f"[Pipeline] {name} 任务初始化，总计 {len(normalized_items)} 词",
            extra={
                "event": "progress",
                "data": {"current": 0, "total": len(normalized_items), "phase": "initializing"},
            },
        )

        enriched = self.word_service.enrich_with_states(normalized_items, auto_backfill=True)
        pending_items, processed_items = self.word_service.partition_by_processability(enriched)

        skipped_spells = [item.spelling for item in processed_items]
        self.logger.info(
            f"[去重] {name}: 总计 {len(normalized_items)} 词，已处理跳过 {len(processed_items)} 词，待处理 {len(pending_items)} 词"
        )

        if skipped_spells:
            self.logger.info(f"[去重] 本轮跳过单词: {self._format_words_preview(skipped_spells)}")
            rows = []
            for item in processed_items:
                phase = "skipped"
                status = "done"
                reason = ""

                try:
                    note = get_local_word_note(item.voc_id)
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
                        # H1 修复：failed 词不再静默显示为"已完成"，前端能看到失败状态
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
                "[RowStatus] 本轮跳过单词状态回填",
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

        try:
            with ThreadPoolExecutor(max_workers=ai_workers) as executor:
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
                        "progress": {"current": 0, "total": total_pending, "batches": total_batches},
                    },
                )

                for future, batch, start_pos, batch_no, batch_spells in futures:
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

        self.sync_manager.flush_pending_syncs(name)

    def shutdown(self):
        self.sync_manager.shutdown()