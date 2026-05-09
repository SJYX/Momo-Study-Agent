"""
core/sync_manager.py: 后台同步任务调度与队列管理。
"""
import queue
import threading
import time
from typing import Callable, Optional

from core.active_profile_registry import is_active
from core.sync_priority import Priority
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

        self.sync_queue = queue.PriorityQueue()
        self.conflict_sync_queue = queue.Queue()
        self._sync_worker_stopped = False
        self._stop_event = threading.Event()
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._consecutive_p1_count = 0

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

    def _next_seq(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def queue_maimemo_sync(
        self,
        voc_id,
        spell,
        interpretation,
        tags,
        force_sync: bool = False,
        priority: Priority = Priority.P1,
        profile_name: str = "",
    ):
        item = {
            "voc_id": str(voc_id),
            "spell": spell,
            "interpretation": interpretation,
            "tags": list(tags or []),
            "force_sync": bool(force_sync),
            "priority": int(priority),
            "profile_name": str(profile_name or "").strip().lower(),
        }
        self.sync_queue.put((int(priority), self._next_seq(), item))

    def _take_next_item(self):
        try:
            p0 = self.sync_queue.get_nowait()
        except queue.Empty:
            return None
        return self._apply_starvation_policy(p0)

    def _apply_starvation_policy(self, p0):
        # 防饿死：连续 5 个 P1 后若存在非 P1，强制让出 1 个。
        if int(p0[0]) == int(Priority.P1):
            if self._consecutive_p1_count >= 5:
                deferred = [p0]
                chosen = None
                while True:
                    try:
                        candidate = self.sync_queue.get_nowait()
                    except queue.Empty:
                        break
                    if int(candidate[0]) > int(Priority.P1):
                        chosen = candidate
                        break
                    deferred.append(candidate)
                for task in deferred:
                    self.sync_queue.put(task)
                    self.sync_queue.task_done()
                if chosen is not None:
                    self._consecutive_p1_count = 0
                    return chosen
                self._consecutive_p1_count += 1
                return p0
            self._consecutive_p1_count += 1
            return p0

        self._consecutive_p1_count = 0
        return p0

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
            if self._stop_event.is_set() and self.sync_queue.empty():
                break

            wrapped = self._take_next_item()
            if wrapped is None:
                try:
                    wrapped = self.sync_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                wrapped = self._apply_starvation_policy(wrapped)

            priority, _, item = wrapped
            task_done_manually = False
            try:
                if int(priority) >= int(Priority.P3) and not is_active(item.get("profile_name", "")):
                    self.sync_queue.put((priority, self._next_seq(), item))
                    self.sync_queue.task_done()
                    task_done_manually = True
                    time.sleep(0.5)
                    continue

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
                if not task_done_manually:
                    self.sync_queue.task_done()

        self._sync_worker_stopped = True

    def flush_pending_syncs(self, context_name: str):
        pending_count = self.sync_queue.qsize()
        if pending_count > 0:
            self.logger.info(f"🔁 还有 {pending_count} 个 {context_name} 结果正在后台同步，可继续其他操作。")

    def shutdown(self):
        pending_count = self.sync_queue.qsize()
        self.logger.info(f"退出前关闭后台同步线程，剩余任务 {pending_count} 个...")
        self._stop_event.set()
        self.sync_worker_thread.join(timeout=5.0)
        if self.sync_worker_thread.is_alive():
            self.logger.warning("后台同步线程未在 10 秒内结束")
        else:
            self.logger.info("✅ 后台同步线程已平滑退出")
