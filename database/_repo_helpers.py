from __future__ import annotations
"""
database/_repo_helpers.py: 仓储层共享小工具（行映射、写入分发、note upsert 参数组装）。

边界：
- 不依赖具体 repo 业务，只封装跨 repo 重复出现的模板代码。
- 写入分发函数 dispatch_write / dispatch_batch_write 采用延迟导入 connection 以避免循环依赖。
"""

from typing import Any, Callable, Dict, List, Optional, Tuple


def row_value(row: Any, idx: int, col: str) -> Any:
    """Extract a scalar from a DB row, supporting raw tuples and named-row objects (libsql/sqlite3)."""
    if isinstance(row, (tuple, list)):
        return row[idx]
    try:
        return row[col]
    except (KeyError, IndexError, TypeError):
        try:
            return row[idx]
        except Exception:
            return None


def row_to_dict(row: Any, fallback_columns: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Convert a DB row to a dict; supports libsql Row, sqlite3.Row, raw tuple, asdict()-able rows."""
    if not row:
        return None
    if hasattr(row, "keys"):
        return dict(zip(row.keys(), tuple(row)))
    if hasattr(row, "asdict"):
        return row.asdict()
    if fallback_columns and isinstance(row, (tuple, list)):
        return dict(zip(fallback_columns, row))
    return None


def rows_to_dicts(rows: List[Any], fallback_columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Map a list of rows through row_to_dict, dropping None entries."""
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        d = row_to_dict(r, fallback_columns=fallback_columns)
        if d is not None:
            out.append(d)
    return out


def dispatch_write(
    sql: str,
    args: Tuple,
    *,
    db_path: Optional[str] = None,
    conn: Any = None,
    op_type: str = "insert_or_replace",
    queue_full_log: Optional[Callable[[str], None]] = None,
    queue_full_message: str = "写入入队失败: 写队列已满",
) -> bool:
    """Dispatch a single write to either local-direct path or the write queue."""
    from . import connection

    if connection._should_use_local_only_connection(db_path, conn):
        connection._execute_write_sql_sync(sql, args, db_path=db_path, conn=conn)
        return True
    ok = connection._queue_write_operation(sql, args, op_type=op_type)
    if not ok and queue_full_log is not None:
        queue_full_log(queue_full_message)
    return ok


def dispatch_batch_write(
    sql: str,
    args_list: List[Tuple],
    *,
    db_path: Optional[str] = None,
    conn: Any = None,
    queue_full_log: Optional[Callable[[str], None]] = None,
    queue_full_message: str = "批量写入入队失败: 写队列已满",
) -> bool:
    """Dispatch a batch write to either local-direct path or the write queue."""
    from . import connection

    if connection._should_use_local_only_connection(db_path, conn):
        connection._execute_batch_write_sql_sync(sql, args_list, db_path=db_path, conn=conn)
        return True
    ok = connection._queue_batch_write_operation(sql, args_list)
    if not ok and queue_full_log is not None:
        queue_full_log(queue_full_message)
    return ok
