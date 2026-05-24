from __future__ import annotations
"""database/connection/factory.py: 连接工厂与读路径分发。

按"如何打开一条连接"的职责切片:
- 本地连接: _get_local_conn / _get_local_read_conn / _get_hub_local_conn
- 云端 Hub: _get_hub_conn (cloud-or-local 自适应)
- 读路径分发: _get_read_conn / _get_read_conn_impl / _should_use_local_only_connection
- 通用 getter: _get_conn (do_sync=True 才走单例)
- 业务工具: _run_with_managed_connection / _hub_fetch_one_dict / _hub_fetch_all_dicts
- 兜底声明: is_hub_configured / set_runtime_cloud_credentials

依赖方向:本模块只 import 自 `context`,不 import 自 `singleton`。需要写单例
的位置(`_get_conn` 的 do_sync 路径、`_get_hub_conn`)走**函数体内 late import**
避免循环 import。
"""

import os
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional, Tuple  # noqa: F401

import config as _config

from .context import (
    HAS_PYTURSO,
    HUB_DB_PATH,
    TURSO_HUB_AUTH_TOKEN,
    TURSO_HUB_DB_URL,
    _backup_broken_database_file,
    _debug_log,
    _get_backend,
    _is_main_db_path,
    _is_sqlite_data_corruption_error,
    _is_sqlite_malformed_error,
    _resolve_conn_context,
    _row_to_dict,
    _schema_init_callbacks,
    get_logger,
)


def _get_local_read_conn(db_path: Optional[str] = None) -> Any:
    """打开一个只读连接。

    在 pyturso 模式下，统一使用免 pull 的 pyturso 引擎连接，以防与标准 sqlite3 冲突损坏数据。
    在普通 SQLite 模式下，打开轻量级只读 sqlite3 连接。
    """
    path = db_path or _config.DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    ctx = _resolve_conn_context(path)
    if (HAS_PYTURSO) and ctx.get("url") and ctx.get("token"):
        conn = _get_backend().connect(path, ctx["url"], ctx["token"], do_sync=False, do_pull=False)
        try:
            conn.execute("PRAGMA query_only=ON;")
        except Exception:
            pass
        return conn

    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=2000;")
    conn.execute("PRAGMA query_only=ON;")
    return conn


def _get_local_conn(db_path: Optional[str] = None) -> Any:
    path = db_path or _config.DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    ctx = _resolve_conn_context(path)
    is_pyturso_cloud = bool((HAS_PYTURSO) and ctx.get("url") and ctx.get("token"))

    def _open_local_connection() -> Any:
        if is_pyturso_cloud:
            return _get_backend().connect(path, ctx["url"], ctx["token"], do_sync=False, do_pull=False)
        conn = sqlite3.connect(path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        conn.text_factory = lambda b: b.decode("utf-8", "replace")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA wal_autocheckpoint=1000;")
        return conn

    try:
        return _open_local_connection()
    except Exception as error:
        if not _is_sqlite_malformed_error(error):
            raise

        backup_path = _backup_broken_database_file(path, "检测到本地数据库损坏，已备份本地数据库")
        if not backup_path:
            raise

        ctx = _resolve_conn_context(path)
        if (HAS_PYTURSO) and ctx.get("url") and ctx.get("token"):
            try:
                _debug_log(f"本地数据库损坏后，尝试通过云端副本重建: {path}", level="WARNING")
                return _get_conn(path, allow_local_fallback=False)
            except Exception as recovery_error:
                _debug_log(f"通过云端副本重建本地数据库失败，改为重新初始化空库: {recovery_error}", level="WARNING")

        conn = _open_local_connection()
        main_initializer = _schema_init_callbacks.get("main")
        if callable(main_initializer):
            try:
                main_initializer(conn)
                conn.commit()
            except Exception:
                conn.close()
                raise
        return conn


def _get_hub_local_conn() -> Any:
    path = HUB_DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def _open_local_connection() -> Any:
        if (HAS_PYTURSO) and TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN:
            return _get_backend().connect(path, TURSO_HUB_DB_URL, TURSO_HUB_AUTH_TOKEN, do_sync=False, do_pull=False)
        conn = sqlite3.connect(path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        conn.text_factory = lambda b: b.decode("utf-8", "replace")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    try:
        return _open_local_connection()
    except Exception as error:
        if not _is_sqlite_malformed_error(error):
            raise

        backup_path = _backup_broken_database_file(path, "检测到 Hub 本地数据库损坏，已备份本地数据库")
        if not backup_path:
            raise

        if (HAS_PYTURSO) and TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN:
            try:
                _debug_log(f"Hub 本地数据库损坏后，尝试通过云端副本重建: {path}", level="WARNING")
                from .singleton import _get_hub_write_conn_singleton
                return _get_hub_write_conn_singleton(do_sync=True)
            except Exception as recovery_error:
                _debug_log(f"通过云端副本重建 Hub 本地数据库失败，改为重新初始化空库: {recovery_error}", level="WARNING")

        conn = _open_local_connection()
        hub_initializer = _schema_init_callbacks.get("hub")
        if callable(hub_initializer):
            try:
                hub_initializer(conn)
                conn.commit()
            except Exception:
                conn.close()
                raise
        return conn


def _should_use_local_only_connection(db_path: Optional[str] = None, conn: Any = None) -> bool:
    if conn is not None:
        return True

    path = db_path or _config.DB_PATH
    if os.path.abspath(path) != os.path.abspath(_config.DB_PATH):
        return True

    ctx = _resolve_conn_context(path)
    return not (ctx.get("url") and ctx.get("token") and (HAS_PYTURSO))


def _wrap_and_track_connection(_db_path: str, conn: Any, _read_only: bool) -> Any:
    return conn


def _get_read_conn(
    db_path: Optional[str],
    max_retries: int = 3,
    retry_delay: float = 1.0,
    allow_local_fallback: bool = True,
) -> Any:
    return _get_read_conn_impl(
        db_path or _config.DB_PATH,
        max_retries=max_retries,
        retry_delay=retry_delay,
        allow_local_fallback=allow_local_fallback,
    )


def _get_read_conn_impl(
    db_path: str,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    allow_local_fallback: bool = True,
) -> Any:
    """Resolve read connection.

    In pyturso mode, we always read from the local sqlite3 read-only connection
    to achieve best concurrency under WAL.
    """
    ctx = _resolve_conn_context(db_path)
    db_path = ctx["db_path"]

    if _should_use_local_only_connection(db_path):
        conn = _get_local_conn(db_path)
        return _wrap_and_track_connection(db_path, conn, True)

    try:
        conn = _get_local_read_conn(db_path)
        return _wrap_and_track_connection(db_path, conn, True)
    except Exception as e:
        _debug_log(f"打开本地只读连接失败，尝试回退到 standard 连接: {e}", level="WARNING")

    if allow_local_fallback and (not ctx["force_cloud_mode"] or ctx["is_test"]):
        conn = _get_local_conn(db_path)
        return _wrap_and_track_connection(db_path, conn, True)

    raise RuntimeError("无法连接到只读数据库")


def _get_conn(
    db_path: str,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    allow_local_fallback: bool = True,
    do_sync: bool = False,
) -> Any:
    ctx = _resolve_conn_context(db_path)
    db_path = ctx["db_path"]

    # 只有当 do_sync=True 时，才获取云端同步单例连接
    if do_sync and _is_main_db_path(db_path) and ctx.get("url") and ctx.get("token") and (HAS_PYTURSO):
        from .singleton import _get_main_write_conn_singleton
        return _get_main_write_conn_singleton(do_sync=do_sync, max_retries=max_retries, retry_delay=retry_delay)

    # 否则在常规业务读写时，直接使用本地连接即可
    return _get_local_conn(db_path)


def is_hub_configured() -> bool:
    return bool(TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN)


def _get_hub_conn(max_retries: int = 3, retry_delay: float = 1.0) -> Any:
    from config import get_force_cloud_mode

    if get_force_cloud_mode() and not is_hub_configured():
        raise RuntimeError("强制云端模式已启用，但未配置 TURSO_HUB_DB_URL/TURSO_HUB_AUTH_TOKEN")
    if get_force_cloud_mode() and not (HAS_PYTURSO):
        raise RuntimeError("强制云端模式已启用，但 turso.sync (pyturso) 不可用")

    if TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN and (HAS_PYTURSO):
        _debug_log("[_get_hub_conn] 检测到云端 Hub 配置，尝试连接...")
        last_error = None
        for attempt in range(max_retries):
            try:
                _debug_log(f"[_get_hub_conn] 尝试 {attempt+1}/{max_retries}，调用 _get_hub_write_conn_singleton...")
                from .singleton import _get_hub_write_conn_singleton
                result = _get_hub_write_conn_singleton(
                    do_sync=False,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                )
                _debug_log("[_get_hub_conn] 云端 Hub 连接成功")
                return result
            except Exception as e:
                last_error = e
                _debug_log(f"[_get_hub_conn] 尝试 {attempt+1} 失败: {e}", level="WARNING")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    _debug_log(f"云端 Hub 连接失败，回退本地: {e}", level="WARNING")
        if get_force_cloud_mode():
            raise RuntimeError(f"强制云端模式连接 Hub 失败 (已尝试 {max_retries} 次): {last_error}")

    _debug_log("[_get_hub_conn] 无云端配置，使用本地 Hub 连接")
    if not get_force_cloud_mode():
        return _get_hub_local_conn()

    raise RuntimeError("强制云端模式已启用，但无法连接到云端 Hub 数据库")


def _run_with_managed_connection(
    optional_conn: Any,
    conn_factory: Callable[[], Any],
    operation: Callable[[Any], Any],
) -> Any:
    owned = optional_conn is None
    target_conn = optional_conn or conn_factory()

    try:
        result = operation(target_conn)
        if owned:
            target_conn.commit()
        return result
    finally:
        if owned:
            try:
                target_conn.close()
            except Exception:
                pass


def _hub_fetch_one_dict(sql: str, params: tuple = ()) -> Optional[dict]:
    """Hub single-row read."""
    try:
        hub_conn = _get_hub_local_conn()
        cur = hub_conn.cursor()
        try:
            cur.execute(sql, params)
            row = cur.fetchone()
        finally:
            cur.close()
        hub_conn.commit()
        try:
            hub_conn.close()
        except Exception:
            pass
        return _row_to_dict(cur, row) if row else None
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            get_logger().warning_throttled(
                "hub_fetch_one_dict_corruption",
                f"_hub_fetch_one_dict 数据损坏异常: {e}",
                module="database.connection",
            )
            return None
        _debug_log(f"_hub_fetch_one_dict 异常: {e}", level="WARNING")
        return None


def _hub_fetch_all_dicts(sql: str, params: tuple = ()) -> List[dict]:
    """Hub multi-row read."""
    try:
        hub_conn = _get_hub_local_conn()
        cur = hub_conn.cursor()
        try:
            cur.execute(sql, params)
            rows = cur.fetchall()
        finally:
            cur.close()
        hub_conn.commit()
        try:
            hub_conn.close()
        except Exception:
            pass
        return [_row_to_dict(cur, row) for row in rows]
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            get_logger().warning_throttled(
                "hub_fetch_all_dicts_corruption",
                f"_hub_fetch_all_dicts 数据损坏异常: {e}",
                module="database.connection",
            )
            return []
        _debug_log(f"_hub_fetch_all_dicts 异常: {e}", level="WARNING")
        return []


def set_runtime_cloud_credentials(_url: Optional[str], _token: Optional[str], _hostname: Optional[str] = None) -> None:
    """No-op kept for backward compat — cloud credentials are now read via os.getenv() in _resolve_conn_context."""
