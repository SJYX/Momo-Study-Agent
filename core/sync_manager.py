"""
core/sync_manager.py: 后台同步任务调度与队列管理。
"""
import queue
import threading
from typing import Callable, Optional

from database.momo_words import (
    get_local_word_note,
    get_word_note,
    mark_processed,
    mark_note_synced,
    set_note_sync_status,
)


class SyncManager:
    """后台调度层：同步任务入队、worker 执行、同步统计与退出收尾。"""

    def __init__(
        self,
        logger,
        momo_api,
        on_mark_processed: Callable[[str, str], None],
        on_conflict: Optional[Callable[[dict, str], None]] = None,
        db_path: Optional[str] = None,
    ):
        self.logger = logger
        self.momo = momo_api
        self.on_mark_processed = on_mark_processed
        self.on_conflict = on_conflict
        self.db_path = db_path

        self.sync_queue = queue.Queue()
        self.conflict_sync_queue = queue.Queue()
        self._sync_worker_stopped = False

        self._sync_duration_history = {
            "用户数据库": [],
            "中央 Hub 数据库": [],
        }
        self._sync_duration_history_limit = 12

        self.sync_worker_thread = threading.Thread(target=self._maimemo_sync_worker, daemon=True)
        self.sync_worker_thread.start()

    def _canonical_sync_label(self, label: str) -> str:
        text = str(label or "")
        if "用户数据库" in text:
            return "用户数据库"
        if "中央 Hub" in text:
            return "中央 Hub 数据库"
        return ""

    def record_sync_duration(self, label: str, duration_ms: int, status: str = "ok") -> None:
        canonical = self._canonical_sync_label(label)
        if not canonical or duration_ms <= 0:
            return
        normalized_status = str(status or "ok").lower()
        if normalized_status in {"error", "failed", "fail", "skipped"}:
            return
        bucket = self._sync_duration_history.get(canonical)
        if bucket is None:
            return
        bucket.append(int(duration_ms))
        overflow = len(bucket) - self._sync_duration_history_limit
        if overflow > 0:
            del bucket[0:overflow]

    def estimate_exit_sync_timeout_s(self, default_timeout_s: float) -> float:
        def _p80(values):
            if not values:
                return 0
            ordered = sorted(int(v) for v in values)
            idx = max(0, int((len(ordered) - 1) * 0.8))
            return ordered[idx]

        user_p80 = _p80(self._sync_duration_history.get("用户数据库", []))
        hub_p80 = _p80(self._sync_duration_history.get("中央 Hub 数据库", []))
        if user_p80 <= 0 and hub_p80 <= 0:
            return default_timeout_s

        estimated_total_s = ((user_p80 + hub_p80) / 1000.0) * 1.2 + 1.0
        bounded_timeout_s = max(default_timeout_s, min(45.0, estimated_total_s))
        return round(bounded_timeout_s, 1)

    def queue_maimemo_sync(self, voc_id, spell, interpretation, tags, force_sync: bool = False):
        self.sync_queue.put(
            {
                "voc_id": str(voc_id),
                "spell": spell,
                "interpretation": interpretation,
                "tags": list(tags or []),
                # 内存信任标志：True 时跳过 DB 读兜底，直接发起网络同步
                "force_sync": bool(force_sync),
            }
        )

    def _defer_maimemo_conflict(self, item, reason: str):
        self.conflict_sync_queue.put(item)
        self.logger.info(
            f"[RowStatus] {item.get('spell', '')} 同步冲突",
            extra={
                "event": "row_status",
                "data": {
                    "rows": [
                        {
                            "item_id": str(item.get("spell", "")).lower(),
                            "status": "error",
                            "phase": "sync_conflict",
                            "error": reason,
                        }
                    ]
                },
            },
        )
        if self.on_conflict:
            self.on_conflict(item, reason)
            return
        self.logger.warning(f"⚠️ {item.get('spell', item.get('voc_id', 'unknown'))} 已进入冲突队列: {reason}")

    def _maimemo_sync_worker(self):
        while True:
            item = self.sync_queue.get()
            try:
                if item is None:
                    break

                voc_id = item["voc_id"]
                spell = item["spell"]
                interpretation = item["interpretation"]
                tags = item["tags"] or ["雅思"]
                force_sync = bool(item.get("force_sync", False))

                current_note = None
                current_status = 0

                # 仅在非内存信任路径下执行 DB 查询兜底
                if not force_sync:
                    try:
                        if self.db_path:
                            current_note = get_local_word_note(voc_id, db_path=self.db_path)
                        else:
                            current_note = get_local_word_note(voc_id)
                    except Exception as local_read_error:
                        self.logger.warning(f"⚠️ {spell} 本地数据库读取失败: {local_read_error}")

                    if not current_note:
                        try:
                            if self.db_path:
                                current_note = get_word_note(voc_id, db_path=self.db_path)
                            else:
                                current_note = get_word_note(voc_id)
                        except Exception as fallback_read_error:
                            self.logger.warning(f"⚠️ {spell} 主连接读取失败: {fallback_read_error}")

                    current_status = int(current_note.get("sync_status", 0) or 0) if current_note else 0

                if current_status == 2:
                    self._defer_maimemo_conflict(item, "当前状态已是冲突态")
                    continue
                if current_status != 0:
                    self.logger.info(f"ℹ️ {spell} 当前sync_status={current_status}，跳过重复同步")
                    continue

                try:
                    sync_result = self.momo.sync_interpretation(
                        voc_id,
                        interpretation,
                        tags=tags,
                        spell=spell,
                        force_create=True,
                        local_reference=interpretation,
                        return_details=True,
                    )
                    sync_status = 1
                    if isinstance(sync_result, dict):
                        sync_status = int(sync_result.get("sync_status", 0) or 0)
                    elif not sync_result:
                        sync_status = 0

                    if sync_status == 1:
                        try:
                            if self.db_path:
                                mark_processed(voc_id, spell, db_path=self.db_path)
                            else:
                                mark_processed(voc_id, spell)
                        except Exception as persist_error:
                            self.logger.warning(f"⚠️ {spell} 已同步，但 processed 标记持久化失败: {persist_error}")
                        try:
                            self.on_mark_processed(voc_id, spell)
                        except Exception as cache_error:
                            self.logger.warning(f"⚠️ {spell} 已同步，但缓存更新失败: {cache_error}")
                        if self.db_path:
                            ok = mark_note_synced(voc_id, db_path=self.db_path)
                        else:
                            ok = mark_note_synced(voc_id)
                        if not ok:
                            self.logger.warning(f"⚠️ {spell} sync_status=1 写回未命中")
                        self.logger.info(f"[Pipeline] {spell} - 4. 墨墨同步完成: 释义一致并入库")
                        self.logger.info(
                            f"[RowStatus] {spell} 同步完成",
                            extra={
                                "event": "row_status",
                                "data": {
                                    "rows": [
                                        {
                                            "item_id": str(spell).lower(),
                                            "status": "done",
                                            "phase": "sync_done",
                                        }
                                    ]
                                },
                            },
                        )
                    elif sync_status == 2:
                        try:
                            if self.db_path:
                                mark_processed(voc_id, spell, db_path=self.db_path)
                            else:
                                mark_processed(voc_id, spell)
                        except Exception as persist_error:
                            self.logger.warning(f"⚠️ {spell} 冲突态 processed 持久化失败: {persist_error}")
                        try:
                            self.on_mark_processed(voc_id, spell)
                        except Exception as cache_error:
                            self.logger.warning(f"⚠️ {spell} 冲突态缓存更新失败: {cache_error}")
                        if self.db_path:
                            ok = set_note_sync_status(voc_id, 2, db_path=self.db_path)
                        else:
                            ok = set_note_sync_status(voc_id, 2)
                        if not ok:
                            self.logger.warning(f"⚠️ {spell} sync_status=2 写回未命中")
                        self.logger.warning(f"[Pipeline] ⚠️ {spell} - 4. 墨墨同步提示: 发现已存在的不一致释义，已标记冲突")
                        self.logger.info(
                            f"[RowStatus] {spell} 同步冲突",
                            extra={
                                "event": "row_status",
                                "data": {
                                    "rows": [
                                        {
                                            "item_id": str(spell).lower(),
                                            "status": "error",
                                            "phase": "sync_conflict",
                                            "error": "远端释义与本地不一致",
                                        }
                                    ]
                                },
                            },
                        )
                    else:
                        reason = ""
                        if isinstance(sync_result, dict):
                            reason = str(sync_result.get("reason", "") or "").lower()

                        # 非法资源 ID 属于不可重试失败：写回冲突态避免反复重试刷屏。
                        if reason in {"invalid_res_id", "common_invalid_res_id"}:
                            if self.db_path:
                                ok = set_note_sync_status(voc_id, 2, db_path=self.db_path)
                            else:
                                ok = set_note_sync_status(voc_id, 2)
                            if not ok:
                                self.logger.warning(f"⚠️ {spell} 非法 voc_id 状态写回未命中")
                            self.logger.warning(f"⚠️ {spell} voc_id={voc_id} 在墨墨侧非法，已标记为冲突并停止重试")
                            self.logger.info(
                                f"[RowStatus] {spell} 同步失败",
                                extra={
                                    "event": "row_status",
                                    "data": {
                                        "rows": [
                                            {
                                                "item_id": str(spell).lower(),
                                                "status": "error",
                                                "phase": "sync_failed",
                                                "error": "invalid_res_id",
                                            }
                                        ]
                                    },
                                },
                            )
                            continue

                        self.logger.warning(f"⚠️ {spell} 墨墨同步未完成")
                        self.logger.info(
                            f"[RowStatus] {spell} 同步未完成",
                            extra={
                                "event": "row_status",
                                "data": {
                                    "rows": [
                                        {
                                            "item_id": str(spell).lower(),
                                            "status": "error",
                                            "phase": "sync_failed",
                                            "error": reason or "sync_incomplete",
                                        }
                                    ]
                                },
                            },
                        )
                except Exception as e:
                    self.logger.error(f"❌ {spell} 后台同步异常: {e}")
                    self.logger.info(
                        f"[RowStatus] {spell} 同步异常",
                        extra={
                            "event": "row_status",
                            "data": {
                                "rows": [
                                    {
                                        "item_id": str(spell).lower(),
                                        "status": "error",
                                        "phase": "sync_failed",
                                        "error": str(e),
                                    }
                                ]
                            },
                        },
                    )
            finally:
                self.sync_queue.task_done()

        self._sync_worker_stopped = True

    def flush_pending_syncs(self, context_name: str):
        pending_count = self.sync_queue.qsize()
        if pending_count > 0:
            self.logger.info(f"🔁 还有 {pending_count} 个 {context_name} 结果正在后台同步，可继续其他操作。")

    def shutdown(self):
        pending_count = self.sync_queue.qsize()
        self.logger.info(f"退出前关闭后台同步线程，剩余任务 {pending_count} 个...")
        self.sync_queue.put(None)
        self.sync_worker_thread.join(timeout=5.0)
        if self.sync_worker_thread.is_alive():
            self.logger.warning("后台同步线程未在 10 秒内结束")
        else:
            self.logger.info("✅ 后台同步线程已平滑退出")
