"""
core/sync_manager.py: 后台同步任务调度与队列管理。
"""
import queue
import threading
import time
from typing import Callable, Optional

from core.active_profile_registry import is_active
from core.feature_flags import is_enabled
from core.metrics import get_metrics_collector
from core.sync_priority import Priority
from database.momo_words import (
    get_local_word_note,
    mark_processed,
    mark_processed_batch,
    mark_note_synced,
    set_note_sync_status,
    update_sync_status_batch,
)
from database.utils import clean_for_maimemo


# PLAYBOOK B3 闲时引擎阈值。"_is_idle" 全部满足 + 连续稳定 IDLE_DEBOUNCE_S 秒才进入 idle。
IDLE_API_P95_MS = 200.0
IDLE_QUEUE_THRESHOLD = 5.0
IDLE_DB_P95_MS = 100.0
IDLE_DEBOUNCE_S = 5.0


class SyncManager:
    """后台调度层：同步任务入队、worker 执行、同步统计与退出收尾。"""

    def __init__(
        self,
        logger,
        momo_api,
        db_path: Optional[str] = None,
    ):
        self.logger = logger
        self.momo = momo_api
        self.db_path = db_path

        self.sync_queue = queue.PriorityQueue()
        self._sync_worker_stopped = False
        self._stop_event = threading.Event()
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._consecutive_p1_count = 0
        # PLAYBOOK B3：闲时引擎防抖时间戳。None 表示尚未连续满足闲时条件。
        self._idle_since: Optional[float] = None

        self._sync_duration_history = {
            "用户数据库": [],
            "中央 Hub 数据库": [],
        }
        self._sync_duration_history_limit = 12

        # 写合并缓冲：积攒终态写入，定量/定时批量刷盘
        self._pending_synced: list = []  # [(voc_id, spell), ...] 成功同步待刷盘
        self._pending_status: list = []  # [(sync_status, match_confidence, match_reason, last_synced_content, voc_id), ...] 终态状态待刷盘
        self._flush_lock = threading.Lock()
        self._last_flush_ts = time.time()
        self._flush_batch_size = 20   # 积攒满 N 条即刷
        self._flush_interval_s = 2.0  # 或间隔 N 秒即刷

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
        retry_count: int = 0,
    ):
        item = {
            "voc_id": str(voc_id),
            "spell": spell,
            "interpretation": interpretation,
            "tags": list(tags or []),
            "force_sync": bool(force_sync),
            "priority": int(priority),
            "profile_name": str(profile_name or "").strip().lower(),
            "retry_count": int(retry_count),
        }
        self.sync_queue.put((int(priority), self._next_seq(), item))
        # 相态 3（queued）虚化为内存态广播，不再硬写数据库以减轻写锁争用。
        # 若进程崩溃，未同步成功的记录仍保留 status=0，重启后自愈/重试会重新捕获。

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
                deferred = []
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
                
                if chosen is not None:
                    # 找到了更高优先级的任务 chosen。
                    # 此时 p0 及取出的 candidate (在 deferred 中) 都要放回队列等待后续调度。
                    # 必须配合 task_done() 平衡重复 put 带来的未完成计数增量。
                    self.sync_queue.put(p0)
                    self.sync_queue.task_done()
                    for task in deferred:
                        self.sync_queue.put(task)
                        self.sync_queue.task_done()
                    self._consecutive_p1_count = 0
                    return chosen
                else:
                    # 未找到更高优先级的任务，当前 p0 继续由外层执行。
                    # p0 绝对不能放回队列，仅将无辜取出的 candidate 还原。
                    for task in deferred:
                        self.sync_queue.put(task)
                        self.sync_queue.task_done()
                    self._consecutive_p1_count += 1
                    return p0
            self._consecutive_p1_count += 1
            return p0

        self._consecutive_p1_count = 0
        return p0

    def _is_idle(self, profile: str) -> bool:
        """PLAYBOOK B3：闲时引擎判定。

        全部条件满足且**连续稳定 IDLE_DEBOUNCE_S 秒**才视为 idle：
        1. api.duration_ms P95 < IDLE_API_P95_MS
        2. sync.queue.depth P95 < IDLE_QUEUE_THRESHOLD
        3. db.batch_write.duration_ms P95 < IDLE_DB_P95_MS

        feature flag IDLE_ENGINE_ENABLED=False 时永远返回 False（回退到 Phase 4 行为）。
        当任一指标无数据（None）时不视为超阈值——保留乐观假设。
        """
        if not is_enabled("IDLE_ENGINE_ENABLED", default=True):
            self._idle_since = None
            return False

        prof = profile or "_global"
        coll = get_metrics_collector()

        api_p95 = coll.percentile(prof, "api.duration_ms", 95)
        if api_p95 is not None and api_p95 >= IDLE_API_P95_MS:
            self._idle_since = None
            return False

        qd_p95 = coll.percentile(prof, "sync.queue.depth", 95)
        if qd_p95 is not None and qd_p95 >= IDLE_QUEUE_THRESHOLD:
            self._idle_since = None
            return False

        db_p95 = coll.percentile(prof, "db.batch_write.duration_ms", 95)
        if db_p95 is not None and db_p95 >= IDLE_DB_P95_MS:
            self._idle_since = None
            return False

        # 防抖：首次满足条件时记下时间戳；连续稳定 IDLE_DEBOUNCE_S 秒后才返回 True
        if self._idle_since is None:
            self._idle_since = time.time()
            return False
        return (time.time() - self._idle_since) >= IDLE_DEBOUNCE_S

    def _maimemo_sync_worker(self):
        while True:
            if self._stop_event.is_set() and self.sync_queue.empty():
                break

            # PLAYBOOK B5：采样队列深度（每轮一次，B3 闲时判定输入之一）。
            # profile 维度用 ActiveProfileRegistry 取最近活跃 profile；为空则归 "_global"。
            try:
                from core.active_profile_registry import get_active as _get_active
                metrics_prof = _get_active() or "_global"
                get_metrics_collector().record(
                    metrics_prof, "sync.queue.depth", float(self.sync_queue.qsize())
                )
            except Exception:
                pass

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
                    # B3 闲时引擎：系统稳定 idle 时全速消费 P3/P4，不再因非 active profile 暂停
                    if not self._is_idle(item.get("profile_name", "")):
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
                last_synced_content = None
                synced_content = clean_for_maimemo(interpretation)

                # 仅在非内存信任路径下执行 DB 查询
                if not force_sync:
                    try:
                        if self.db_path:
                            current_note = get_local_word_note(voc_id, db_path=self.db_path)
                        else:
                            current_note = get_local_word_note(voc_id)
                    except Exception as local_read_error:
                        self.logger.warning(f"⚠️ {spell} 本地数据库读取失败: {local_read_error}")

                    current_status = int(current_note.get("sync_status", 0) or 0) if current_note else 0
                    last_synced_content = current_note.get("last_synced_content") if current_note else None

                # 兼容新状态：允许处理 0(unsynced) 的任务；其余状态(1/2/5)均跳过
                if current_status != 0:
                    self.logger.info(f"ℹ️ {spell} 当前sync_status={current_status}，跳过重复同步")
                    continue

                try:
                    # 相态 4（syncing）虚化为内存态广播，不再硬写数据库。
                    # 发出行级状态：正在同步
                    self.logger.info(
                        f"[RowStatus] {spell} 开始同步",
                        extra={
                            "event": "row_status",
                            "data": {
                                "rows": [
                                    {
                                        "item_id": str(spell).lower(),
                                        "status": "running",
                                        "phase": "syncing",
                                    }
                                ]
                            },
                        },
                    )

                
                    _task_started_at = time.time()
                    sync_result = self.momo.sync_interpretation(
                        voc_id,
                        interpretation,
                        tags=tags,
                        spell=spell,
                        force_create=True,
                        local_reference=interpretation,
                        return_details=True,
                    )
                    # PLAYBOOK B5：记录单条同步耗时（不区分成功/失败状态，都进窗口）
                    try:
                        _task_duration_ms = int((time.time() - _task_started_at) * 1000)
                        get_metrics_collector().record(
                            item.get("profile_name", "") or "_global",
                            "sync.task.duration_ms",
                            float(_task_duration_ms),
                        )
                    except Exception:
                        pass
                    sync_status = 1
                    match_confidence = None
                    match_reason = None
                    if isinstance(sync_result, dict):
                        sync_status = int(sync_result.get("sync_status", 0) or 0)
                        match_confidence = sync_result.get("match_confidence")
                        match_reason = sync_result.get("match_reason")
                    elif not sync_result:
                        sync_status = 0

                    if sync_status == 1:
                        synced_content = clean_for_maimemo(
                            sync_result.get("cloud_interpretation", "") if isinstance(sync_result, dict) else interpretation
                        ) or synced_content
                        # 积攒到写合并缓冲，由 _flush_pending_writes 统一批量刷盘
                        with self._flush_lock:
                            self._pending_synced.append((voc_id, spell))
                            self._pending_status.append((1, match_confidence, match_reason, synced_content, voc_id))
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
                        cloud_id = sync_result.get("cloud_id", "") if isinstance(sync_result, dict) else ""
                        cloud_text = sync_result.get("cloud_interpretation", "") if isinstance(sync_result, dict) else ""
                        
                        # 3-Way Merge 检测: 如果存在 last_synced_content，并且云端内容等于上次同步的内容，
                        # 说明云端未被用户手动修改，而是本系统之前的旧版本，允许强推更新。
                        is_local_update = False
                        if last_synced_content and cloud_id:
                            from database.utils import clean_for_maimemo
                            if clean_for_maimemo(cloud_text) == clean_for_maimemo(last_synced_content):
                                is_local_update = True
                        
                        if is_local_update:
                            self.logger.info(f"[Pipeline] {spell} - 3-Way Merge: 云端为旧版本释义，尝试更新覆盖")
                            update_res = self.momo.update_interpretation(cloud_id, interpretation, tags=tags)
                            if update_res and update_res.get("success"):
                                sync_status = 1
                                match_confidence = 1.0
                                match_reason = "3-way-merged"
                                synced_content = clean_for_maimemo(interpretation)
                                with self._flush_lock:
                                    self._pending_synced.append((voc_id, spell))
                                    self._pending_status.append((1, match_confidence, match_reason, synced_content, voc_id))
                                self.logger.info(f"[Pipeline] {spell} - 4. 墨墨同步完成: 3-Way Merge 覆盖成功并入库")
                            else:
                                self.logger.warning(f"[Pipeline] ⚠️ {spell} - 3-Way Merge: 尝试覆盖失败，回退冲突态")
                                # 保持 sync_status = 2 继续走冲突逻辑
                                is_local_update = False

                        if not is_local_update:
                            try:
                                if self.db_path:
                                    mark_processed(voc_id, spell, db_path=self.db_path)
                                else:
                                    mark_processed(voc_id, spell)
                            except Exception as persist_error:
                                self.logger.warning(f"⚠️ {spell} 冲突态 processed 持久化失败: {persist_error}")
                            if self.db_path:
                                ok = set_note_sync_status(voc_id, 2, db_path=self.db_path, match_confidence=match_confidence, match_reason=match_reason)
                            else:
                                ok = set_note_sync_status(voc_id, 2, match_confidence=match_confidence, match_reason=match_reason)
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

                        # 非法资源 ID 属于不可重试失败：写回 5=failed，避免反复重试刷屏。
                        if reason in {"invalid_res_id", "common_invalid_res_id"}:
                            if self.db_path:
                                ok = set_note_sync_status(voc_id, 5, db_path=self.db_path, match_confidence=match_confidence, match_reason=reason)
                            else:
                                ok = set_note_sync_status(voc_id, 5, match_confidence=match_confidence, match_reason=reason)
                            if not ok:
                                self.logger.warning(f"⚠️ {spell} 非法 voc_id 状态写回未命中")
                            self.logger.warning(f"⚠️ {spell} voc_id={voc_id} 在墨墨侧非法，已标记为 failed 并停止重试")
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

                        # 其他非成功结果（瞬态失败），最多重试 3 次
                        retry_count = int(item.get("retry_count", 0))
                        if retry_count < 3:
                            self.logger.warning(f"⚠️ {spell} 墨墨同步未完成 ({reason})，准备后台第 {retry_count + 1} 次重试...")
                            item["retry_count"] = retry_count + 1
                            self.sync_queue.put((priority, self._next_seq(), item))
                            self.sync_queue.task_done()
                            task_done_manually = True
                            
                            self.logger.info(
                                f"[RowStatus] {spell} 同步重试中",
                                extra={
                                    "event": "row_status",
                                    "data": {
                                        "rows": [
                                            {
                                                "item_id": str(spell).lower(),
                                                "status": "warning",
                                                "phase": "sync_retry",
                                                "error": f"第 {retry_count + 1} 次重试中",
                                            }
                                        ]
                                    },
                                },
                            )
                            # 休眠一小段时间避免重试风暴
                            time.sleep(1.0)
                            continue

                        # 重试超限，写回 5=failed 并通知前端
                        if self.db_path:
                            ok = set_note_sync_status(voc_id, 5, db_path=self.db_path, match_confidence=match_confidence, match_reason=reason or "sync_incomplete")
                        else:
                            ok = set_note_sync_status(voc_id, 5, match_confidence=match_confidence, match_reason=reason or "sync_incomplete")
                        if not ok:
                            self.logger.warning(f"⚠️ {spell} sync_status=5 写回未命中")
                        self.logger.warning(f"⚠️ {spell} 墨墨同步多次重试失败，已标记 failed")
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

            # 每轮循环末检查是否需要刷写缓冲
            self._maybe_flush()

        # 退出前最终刷写
        self._flush_pending_writes()
        self._sync_worker_stopped = True

    def _maybe_flush(self):
        """定量/定时触发批量刷盘。"""
        with self._flush_lock:
            pending_count = len(self._pending_synced) + len(self._pending_status)
        if pending_count <= 0:
            return
        elapsed = time.time() - self._last_flush_ts
        if pending_count >= self._flush_batch_size or elapsed >= self._flush_interval_s:
            self._flush_pending_writes()

    def _flush_pending_writes(self):
        """将积攒的终态写入合并为批量事务一次性刷盘。"""
        with self._flush_lock:
            synced_batch = list(self._pending_synced)
            status_batch = list(self._pending_status)
            self._pending_synced.clear()
            self._pending_status.clear()
            self._last_flush_ts = time.time()

        if not synced_batch and not status_batch:
            return

        # 1. 批量写 processed 标记
        if synced_batch:
            try:
                db_kw = {"db_path": self.db_path} if self.db_path else {}
                if not mark_processed_batch(synced_batch, **db_kw):
                    self.logger.warning(f"⚠️ 批量 processed 标记写入返回 False（{len(synced_batch)} 条）")
            except Exception as e:
                self.logger.warning(f"⚠️ 批量 processed 标记写入失败: {e}")

        # 2. 批量写 sync_status 终态
        if status_batch:
            try:
                db_kw = {"db_path": self.db_path} if self.db_path else {}
                if not update_sync_status_batch([], match_items=status_batch, **db_kw):
                    self.logger.warning(f"⚠️ 批量 sync_status 写入返回 False（{len(status_batch)} 条）")
            except Exception as e:
                self.logger.warning(f"⚠️ 批量 sync_status 写入失败: {e}")

        total = len(synced_batch) + len(status_batch)
        if total > 0:
            self.logger.info(f"[SyncFlush] 批量刷盘完成: {len(synced_batch)} 条 processed + {len(status_batch)} 条 status")

    def flush_pending_syncs(self, context_name: str):
        # 先刷写积攒的终态
        self._flush_pending_writes()
        pending_count = self.sync_queue.qsize()
        if pending_count > 0:
            self.logger.info(f"🔁 还有 {pending_count} 个 {context_name} 结果正在后台同步，可继续其他操作。")

    def shutdown(self):
        pending_count = self.sync_queue.qsize()
        self.logger.info(f"退出前关闭后台同步线程，剩余任务 {pending_count} 个...")
        self._stop_event.set()
        self.sync_worker_thread.join(timeout=5.0)
        # 确保 worker 退出后残余缓冲也被刷写
        self._flush_pending_writes()
        if self.sync_worker_thread.is_alive():
            self.logger.warning("后台同步线程未在 5 秒内结束")
        else:
            self.logger.info("✅ 后台同步线程已平滑退出")
