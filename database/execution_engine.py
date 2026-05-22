"""
database/execution_engine.py: 专职处理并发队列、写操作防冲突以及定时同步。
从 connection.py 解耦出来的执行引擎层。
"""
import os
import threading
import time
from typing import Any, Dict, List, Tuple, Optional

import config as _config
# 稍后我们需要依赖底层的连接管理功能，所以要向 connection.py 拿连接单例。
# 注意：不再从 connection 导入 DB_PATH（Phase 6.4 起它不在 connection 模块级了）；
# 直接读 `_config.DB_PATH` 让 switch_user 立即生效。HUB_DB_PATH 仍是静态可缓存的。
from database.connection import (
    _get_dedicated_write_conn,
    _close_main_write_conn_singleton,
    _close_hub_write_conn_singleton,
    _is_main_db_path,
    _get_local_conn,
    HUB_DB_PATH,
)
from core.logger import get_logger
from database.backends import get_active_backend

# DB 级别的 Embedded Replica 同步状态（供前端展示）
_db_syncing = False
_db_sync_progress: Dict[str, Any] = {}  # {"started_at": float, "phase": str}

# 慢阈值（毫秒）：批写超过此值会被打成 WARNING（Phase 4.5 P95<100ms 对齐）
_SLOW_BATCH_WRITE_MS = 100

def set_db_syncing(phase: str = "") -> None:
    """标记 DB 正在同步（嵌入式副本的 conn.sync() 进行中）。"""
    global _db_syncing, _db_sync_progress
    _db_syncing = True
    _db_sync_progress = {"started_at": time.time(), "phase": phase}


def clear_db_syncing() -> None:
    """清除 DB 同步标记。"""
    global _db_syncing, _db_sync_progress
    _db_syncing = False
    _db_sync_progress = {}


def get_db_sync_status() -> Dict[str, Any]:
    """返回 DB 同步状态，供 health endpoint 使用。"""
    return {
        "syncing": _db_syncing,
        **(_db_sync_progress if _db_syncing else {}),
    }


def _debug_log(msg: str, level: str = "DEBUG") -> None:
    try:
        logger = get_logger()
        func = getattr(logger, level.lower(), None)
        if callable(func):
            func(msg, module="database.execution_engine")
        else:
            logger.debug(msg)
    except Exception:
        pass


def _queue_write_operation(sql: str, args: Tuple = (), op_type: str = "insert_or_replace", db_path: Optional[str] = None) -> bool:
    """入队单条写操作。已弃用，因为在 pyturso 下所有写入同步直写。"""
    return False


def _queue_batch_write_operation(sql: str, args_list: List[Tuple], db_path: Optional[str] = None) -> bool:
    """入队批量写操作。已弃用，因为在 pyturso 下所有写入同步直写。"""
    return False


def init_concurrent_system() -> None:
    """并发系统初始化。在 pyturso 本地同步直写模式下仅输出日志。"""
    _debug_log("并发系统初始化完成（本地直写模式已就绪）", level="INFO")


def cleanup_concurrent_system() -> None:
    """并发系统清理，释放底层单例写连接句柄。"""
    _close_main_write_conn_singleton()
    _close_hub_write_conn_singleton()
    _debug_log("并发系统清理完成", level="INFO")


def _release_db_file_handles_for_recovery(db_path: str) -> None:
    import os
    abs_path = os.path.abspath(db_path or _config.DB_PATH)
    try:
        if abs_path == os.path.abspath(_config.DB_PATH):
            _close_main_write_conn_singleton()
        if abs_path == os.path.abspath(HUB_DB_PATH):
            _close_hub_write_conn_singleton()
    except Exception as singleton_error:
        _debug_log(f"恢复前释放写连接单例失败: {singleton_error}", level="WARNING")


def _mark_main_db_needs_sync(db_path: Optional[str] = None, conn: Any = None) -> None:
    """Notify the per-profile coordinator that a write occurred.

    Used by non-queued write paths (direct SQL via session.py decorators).
    """
    from database.sync_coordinator import mark_db_written

    if conn is not None:
        return
    elif not _is_main_db_path(db_path):
        return

    path = db_path or _config.DB_PATH
    mark_db_written(path)


def _execute_write_sql_sync(sql: str, params: tuple = (), db_path: Optional[str] = None, conn: Any = None) -> None:
    owned = conn is None
    target_conn = conn or _get_local_conn(db_path or _config.DB_PATH)
    try:
        cur = target_conn.cursor()
        try:
            cur.execute(sql, params)
        finally:
            cur.close()
        target_conn.commit()
        _mark_main_db_needs_sync(db_path=db_path, conn=target_conn)
    finally:
        if owned:
            try:
                target_conn.close()
            except Exception:
                pass


def _execute_batch_write_sql_sync(
    sql: str,
    args_list: List[Tuple],
    db_path: Optional[str] = None,
    conn: Any = None,
) -> None:
    if not args_list:
        return

    owned = conn is None
    target_conn = conn or _get_local_conn(db_path or _config.DB_PATH)
    t0 = time.time()
    try:
        cur = target_conn.cursor()
        try:
            cur.executemany(sql, args_list)
        finally:
            cur.close()
        target_conn.commit()

        # 耗时统计与 metrics 记录
        duration_ms = int((time.time() - t0) * 1000)
        is_slow = duration_ms >= _SLOW_BATCH_WRITE_MS
        try:
            logger = get_logger()
            msg = f"batch_write done | size={len(args_list)} | duration_ms={duration_ms}"
            kwargs = dict(
                module="database.execution_engine",
                batch_size=len(args_list),
                duration_ms=duration_ms,
                is_slow=is_slow,
            )
            if is_slow:
                logger.warning(msg + " | slow=true", **kwargs)
            else:
                logger.info(msg, **kwargs)
        except Exception:
            pass

        # PLAYBOOK B5：写入指标层，给 B3 闲时引擎与 /api/ops/metrics 用
        try:
            from core.metrics import get_metrics_collector
            from core.active_profile_registry import get_active
            get_metrics_collector().record(
                get_active() or "_global",
                "db.batch_write.duration_ms",
                float(duration_ms),
            )
        except Exception:
            pass

        _mark_main_db_needs_sync(db_path=db_path, conn=target_conn)
    finally:
        if owned:
            try:
                target_conn.close()
            except Exception:
                pass


def get_write_queue_stats() -> Dict[str, int]:
    """返回空 stats 以防兼容性破坏。"""
    return {
        "total_queued": 0,
        "total_written": 0,
        "total_errors": 0,
        "last_batch_size": 0,
    }
