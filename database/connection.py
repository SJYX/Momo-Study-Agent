
from __future__ import annotations
"""
database/connection.py: 负责全局 libsql 单例连接管理、后台双守护线程调度及进程锁控制。
"""
# -*- coding: utf-8 -*-
"""Database connection infrastructure.

This module centralizes connection lifecycle, background writer/sync daemons,
and Embedded Replica connection rules.

Critical WalConflict rule:
- In Embedded Replica mode, NEVER open extra local libsql read connections.
- All reads/writes must be funneled through a single process-level singleton
    connection per database file.
"""

import os
import queue
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import config as _config
DB_PATH = _config.DB_PATH
HUB_DB_PATH = _config.HUB_DB_PATH
TURSO_HUB_AUTH_TOKEN = _config.TURSO_HUB_AUTH_TOKEN
TURSO_HUB_DB_URL = _config.TURSO_HUB_DB_URL

try:
    import libsql

    HAS_LIBSQL = True
except ImportError:
    HAS_LIBSQL = False

try:
    from core.logger import get_logger
except ImportError:
    try:
        from .logger import get_logger  # type: ignore
    except ImportError:
        import logging

        def get_logger():
            return logging.getLogger(__name__)


# Optional utility imports (to be fully moved into database/utils.py later).
try:
    from .utils import (  # type: ignore
        _backup_broken_database_file,
        _is_sqlite_data_corruption_error,
        _is_sqlite_malformed_error,
    )
except Exception:

    def _is_sqlite_malformed_error(error: Exception) -> bool:
        msg = str(error or "").lower()
        return (
            "database disk image is malformed" in msg
            or "file is not a database" in msg
            or "malformed" in msg
        )

    def _is_sqlite_data_corruption_error(error: Exception) -> bool:
        return _is_sqlite_malformed_error(error)

    def _backup_broken_database_file(db_path: str, warning_message: str) -> Optional[str]:
        _debug_log(f"{warning_message}: {db_path}", level="WARNING")
        return None


# Runtime cloud credentials (kept mutable to support profile loading workflows).
TURSO_DB_URL = None
TURSO_AUTH_TOKEN = None
TURSO_DB_HOSTNAME = None
TURSO_TEST_DB_URL = os.getenv("TURSO_TEST_DB_URL")
TURSO_TEST_AUTH_TOKEN = os.getenv("TURSO_TEST_AUTH_TOKEN")
TURSO_TEST_DB_HOSTNAME = os.getenv("TURSO_TEST_DB_HOSTNAME")


# Background write/sync system state is now in database/execution_engine.py

_main_write_conn_singleton: Any = None
_main_write_conn_lock = threading.Lock()
_main_write_conn_op_lock = threading.RLock()

_hub_write_conn_singleton: Any = None
_hub_write_conn_lock = threading.Lock()
_hub_write_conn_op_lock = threading.RLock()

_throttled_log_state: Dict[str, float] = {}
_throttled_log_lock = threading.Lock()


# Schema callback registry to avoid circular imports with database/schema.py
_schema_init_callbacks: Dict[str, Optional[Callable[[Any], None]]] = {
    "main": None,
    "hub": None,
}


def register_schema_initializers(
    main_initializer: Optional[Callable[[Any], None]] = None,
    hub_initializer: Optional[Callable[[Any], None]] = None,
) -> None:
    """Register schema initialization callbacks lazily.

    This avoids importing business/schema modules from connection.py directly.
    """
    if main_initializer is not None:
        _schema_init_callbacks["main"] = main_initializer
    if hub_initializer is not None:
        _schema_init_callbacks["hub"] = hub_initializer


def _debug_log(msg: str, start_time: Optional[float] = None, level: str = "DEBUG") -> None:
    elapsed = f" | Time: {int((time.time() - start_time) * 1000)}ms" if start_time else ""
    text = f"{msg}{elapsed}"
    try:
        logger = get_logger()
        func = getattr(logger, level.lower(), None)
        if callable(func):
            try:
                func(text, module="database.connection")
            except TypeError:
                func(text)
        else:
            logger.debug(text)
    except Exception:
        pass


def _debug_log_throttled(
    key: str,
    msg: str,
    interval_seconds: float = 30.0,
    start_time: Optional[float] = None,
    level: str = "DEBUG",
) -> None:
    now = time.time()
    should_log = False
    with _throttled_log_lock:
        last_ts = float(_throttled_log_state.get(key, 0.0) or 0.0)
        if now - last_ts >= float(interval_seconds):
            _throttled_log_state[key] = now
            should_log = True
    if should_log:
        _debug_log(msg, start_time=start_time, level=level)


def _normalize_turso_url(hostname: str) -> str:
    if not hostname:
        return ""
    raw = hostname.strip()
    if raw.startswith("libsql://") or raw.startswith("https://") or raw.startswith("wss://"):
        return raw
    if "." in raw or raw == "localhost":
        return f"libsql://{raw}"
    return f"libsql://{raw}"


def _is_main_db_path(db_path: Optional[str] = None) -> bool:
    target = os.path.abspath(db_path or DB_PATH)
    return target == os.path.abspath(DB_PATH)


def _is_hub_db_path(db_path: Optional[str] = None) -> bool:
    target = os.path.abspath(db_path or HUB_DB_PATH)
    return target == os.path.abspath(HUB_DB_PATH)


def _is_replica_metadata_missing_error(error: Exception) -> bool:
    msg = str(error or "").lower()
    return "db file exists but metadata file does not" in msg or (
        "local state is incorrect" in msg and "metadata" in msg
    )


def _resolve_conn_context(db_path: Optional[str] = None) -> Dict[str, Any]:
    path = db_path or DB_PATH
    target_abs = os.path.abspath(path)
    main_abs = os.path.abspath(DB_PATH)

    url = os.getenv("TURSO_DB_URL")
    token = os.getenv("TURSO_AUTH_TOKEN")
    hostname = os.getenv("TURSO_DB_HOSTNAME")

    if not url and hostname:
        url = _normalize_turso_url(hostname)

    is_test = bool(db_path and ("test_" in os.path.basename(db_path) or "test-" in os.path.basename(db_path)))
    if is_test:
        url = os.getenv("TURSO_TEST_DB_URL") or url
        token = os.getenv("TURSO_TEST_AUTH_TOKEN") or token

    from config import get_force_cloud_mode

    force_cloud_mode = bool(get_force_cloud_mode())
    if force_cloud_mode and not url:
        _debug_log("强制云端模式启用，但未发现 TURSO_DB_URL", level="WARNING")

    return {
        "db_path": path,
        "is_main_db": target_abs == main_abs,
        "is_test": is_test,
        "url": url,
        "token": token,
        "force_cloud_mode": force_cloud_mode,
    }


def _connect_embedded_replica(db_path: str, url: str, token: str, do_sync: bool = False) -> Any:
    if not HAS_LIBSQL:
        raise RuntimeError("libsql is not available")

    final_url = url.replace("libsql://", "https://")
    conn = libsql.connect(db_path, sync_url=final_url, auth_token=token)

    try:
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception as e:
        _debug_log(f"Embedded Replica PRAGMA 配置失败（可忽略）: {e}", level="WARNING")

    if do_sync and hasattr(conn, "sync"):
        conn.sync()
    return conn


def _close_main_write_conn_singleton() -> None:
    global _main_write_conn_singleton
    with _main_write_conn_lock:
        conn = _main_write_conn_singleton
        _main_write_conn_singleton = None

    if conn is None:
        return

    try:
        conn.close()
        _debug_log("主库 Embedded Replica 写连接单例已关闭", level="INFO")
    except Exception as e:
        _debug_log(f"关闭主库写连接单例失败: {e}", level="WARNING")


def _close_hub_write_conn_singleton() -> None:
    global _hub_write_conn_singleton
    with _hub_write_conn_lock:
        conn = _hub_write_conn_singleton
        _hub_write_conn_singleton = None

    if conn is None:
        return

    try:
        conn.close()
        _debug_log("Hub Embedded Replica 写连接单例已关闭", level="INFO")
    except Exception as e:
        _debug_log(f"关闭 Hub 写连接单例失败: {e}", level="WARNING")


def _is_main_write_singleton_conn(conn: Any) -> bool:
    with _main_write_conn_lock:
        return conn is not None and conn is _main_write_conn_singleton


def _is_hub_write_singleton_conn(conn: Any) -> bool:
    with _hub_write_conn_lock:
        return conn is not None and conn is _hub_write_conn_singleton


def _get_singleton_conn_op_lock(conn: Any):
    if _is_main_write_singleton_conn(conn):
        return _main_write_conn_op_lock
    if _is_hub_write_singleton_conn(conn):
        return _hub_write_conn_op_lock
    return None


def _get_local_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def _open_local_connection() -> sqlite3.Connection:
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
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as error:
        if not _is_sqlite_malformed_error(error):
            raise

        backup_path = _backup_broken_database_file(path, "检测到本地数据库损坏，已备份本地数据库")
        if not backup_path:
            raise

        ctx = _resolve_conn_context(path)
        if HAS_LIBSQL and ctx.get("url") and ctx.get("token"):
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


def _get_hub_local_conn() -> sqlite3.Connection:
    path = HUB_DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def _open_local_connection() -> sqlite3.Connection:
        conn = sqlite3.connect(path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        conn.text_factory = lambda b: b.decode("utf-8", "replace")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    try:
        return _open_local_connection()
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as error:
        if not _is_sqlite_malformed_error(error):
            raise

        backup_path = _backup_broken_database_file(path, "检测到 Hub 本地数据库损坏，已备份本地数据库")
        if not backup_path:
            raise

        if HAS_LIBSQL and TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN:
            try:
                _debug_log(f"Hub 本地数据库损坏后，尝试通过云端副本重建: {path}", level="WARNING")
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


def _get_main_write_conn_singleton(
    do_sync: bool = False,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> Any:
    global _main_write_conn_singleton

    ctx = _resolve_conn_context(DB_PATH)
    if not (ctx.get("url") and ctx.get("token") and HAS_LIBSQL):
        return _get_local_conn(DB_PATH)

    with _main_write_conn_lock:
        if _main_write_conn_singleton is not None:
            try:
                with _main_write_conn_op_lock:
                    _main_write_conn_singleton.execute("SELECT 1")
                    if do_sync and hasattr(_main_write_conn_singleton, "sync"):
                        _main_write_conn_singleton.sync()
                return _main_write_conn_singleton
            except BaseException as health_error:
                _debug_log(f"主库写连接单例健康检查失败，准备重建: {health_error}", level="WARNING")
                try:
                    _main_write_conn_singleton.close()
                except Exception:
                    pass
                _main_write_conn_singleton = None

    last_error = None
    for attempt in range(max_retries):
        try:
            conn = _connect_embedded_replica(DB_PATH, ctx["url"], ctx["token"], do_sync=do_sync)
            with _main_write_conn_lock:
                if _main_write_conn_singleton is None:
                    _main_write_conn_singleton = conn
                    _debug_log("主库 Embedded Replica 写连接单例已创建", level="INFO")
                    return _main_write_conn_singleton

                try:
                    conn.close()
                except Exception:
                    pass
                return _main_write_conn_singleton
        except Exception as e:
            last_error = e
            if _is_replica_metadata_missing_error(e) or _is_sqlite_malformed_error(e):
                _backup_broken_database_file(DB_PATH, "主库副本状态损坏，已备份后重试")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            break

    raise last_error or RuntimeError("无法创建主库 Embedded Replica 写连接单例")


def _get_hub_write_conn_singleton(
    do_sync: bool = False,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> Any:
    global _hub_write_conn_singleton

    if not (TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN and HAS_LIBSQL):
        return _get_hub_local_conn()

    with _hub_write_conn_lock:
        if _hub_write_conn_singleton is not None:
            try:
                with _hub_write_conn_op_lock:
                    _hub_write_conn_singleton.execute("SELECT 1")
                    if do_sync and hasattr(_hub_write_conn_singleton, "sync"):
                        _hub_write_conn_singleton.sync()
                return _hub_write_conn_singleton
            except BaseException as health_error:
                _debug_log(f"Hub 写连接单例健康检查失败，准备重建: {health_error}", level="WARNING")
                try:
                    _hub_write_conn_singleton.close()
                except Exception:
                    pass
                _hub_write_conn_singleton = None

    last_error = None
    for attempt in range(max_retries):
        try:
            conn = _connect_embedded_replica(HUB_DB_PATH, TURSO_HUB_DB_URL, TURSO_HUB_AUTH_TOKEN, do_sync=do_sync)
            with _hub_write_conn_lock:
                if _hub_write_conn_singleton is None:
                    _hub_write_conn_singleton = conn
                    _debug_log("Hub Embedded Replica 写连接单例已创建", level="INFO")
                    return _hub_write_conn_singleton

                try:
                    conn.close()
                except Exception:
                    pass
                return _hub_write_conn_singleton
        except Exception as e:
            last_error = e
            if _is_replica_metadata_missing_error(e) or _is_sqlite_malformed_error(e):
                _backup_broken_database_file(HUB_DB_PATH, "Hub 副本状态损坏，已备份后重试")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            break

    raise last_error or RuntimeError("无法创建 Hub Embedded Replica 写连接单例")


def _should_use_local_only_connection(db_path: Optional[str] = None, conn: Any = None) -> bool:
    if conn is not None:
        return True

    path = db_path or DB_PATH
    if os.path.abspath(path) != os.path.abspath(DB_PATH):
        return True

    ctx = _resolve_conn_context(path)
    return not (ctx.get("url") and ctx.get("token") and HAS_LIBSQL)


def _wrap_and_track_connection(_db_path: str, conn: Any, _read_only: bool) -> Any:
    return conn


def _get_read_conn(
    db_path: Optional[str],
    max_retries: int = 3,
    retry_delay: float = 1.0,
    allow_local_fallback: bool = True,
) -> Any:
    return _get_read_conn_impl(
        db_path or DB_PATH,
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

    CRITICAL WalConflict fix:
    - Embedded Replica mode must return main write singleton directly.
    - Never open extra local libsql read connections.
    """
    ctx = _resolve_conn_context(db_path)
    db_path = ctx["db_path"]

    if _should_use_local_only_connection(db_path):
        conn = _get_local_conn(db_path)
        return _wrap_and_track_connection(db_path, conn, True)

    if (ctx["is_main_db"] or ctx["is_test"]) and ctx["url"] and ctx["token"] and HAS_LIBSQL:
        last_error = None
        for attempt in range(max_retries):
            try:
                conn = _get_main_write_conn_singleton(do_sync=False, max_retries=max_retries, retry_delay=retry_delay)
                return _wrap_and_track_connection(db_path, conn, True)
            except Exception as e:
                last_error = e
                if _is_replica_metadata_missing_error(e) or _is_sqlite_malformed_error(e):
                    _backup_broken_database_file(db_path, "Embedded Replica 本地状态损坏，已备份并重试")
                if attempt < max_retries - 1:
                    _debug_log(
                        f"Embedded Replica 读连接失败 (尝试 {attempt + 1})，{retry_delay} 秒后重试: {e}",
                        level="WARNING",
                    )
                    time.sleep(retry_delay)
                else:
                    _debug_log(f"Embedded Replica 读连接失败 (已尝试 {max_retries} 次): {e}", level="WARNING")

        if ctx["force_cloud_mode"]:
            raise RuntimeError(f"强制云端模式读连接失败 (已尝试 {max_retries} 次): {last_error}")

    if allow_local_fallback and (not ctx["force_cloud_mode"] or ctx["is_test"]):
        conn = _get_local_conn(db_path)
        return _wrap_and_track_connection(db_path, conn, True)

    raise RuntimeError("强制云端模式已启用，但无法连接到云端数据库")


def _get_conn(
    db_path: str,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    allow_local_fallback: bool = True,
    do_sync: bool = False,
) -> Any:
    ctx = _resolve_conn_context(db_path)
    db_path = ctx["db_path"]

    if _is_main_db_path(db_path) and ctx.get("url") and ctx.get("token") and HAS_LIBSQL:
        return _get_main_write_conn_singleton(do_sync=do_sync, max_retries=max_retries, retry_delay=retry_delay)

    if _should_use_local_only_connection(db_path):
        return _get_local_conn(db_path)

    if (ctx["is_main_db"] or ctx["is_test"]) and ctx["url"] and ctx["token"] and HAS_LIBSQL:
        last_error = None
        for attempt in range(max_retries):
            try:
                conn = _connect_embedded_replica(db_path, ctx["url"], ctx["token"], do_sync=do_sync)
                return _wrap_and_track_connection(db_path, conn, False)
            except Exception as e:
                last_error = e
                if _is_replica_metadata_missing_error(e) or _is_sqlite_malformed_error(e):
                    _backup_broken_database_file(db_path, "Embedded Replica 本地状态损坏，已备份并重试")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                break

        if ctx["force_cloud_mode"]:
            raise RuntimeError(f"强制云端模式连接失败 (已尝试 {max_retries} 次): {last_error}")

    if allow_local_fallback and (not ctx["force_cloud_mode"] or ctx["is_test"]):
        return _get_local_conn(db_path)

    raise RuntimeError("强制云端模式已启用，但无法连接到云端数据库")


def _get_cloud_conn(url: str, token: str, db_path: str = None, max_retries: int = 3):
    """Compatibility helper: establish Embedded Replica connection for a specific cloud target."""
    if not url or not token:
        raise ValueError("Turso URL and token are required")

    local_path = db_path or DB_PATH

    if _is_main_db_path(local_path):
        return _get_main_write_conn_singleton(do_sync=False)

    last_error = None
    for attempt in range(max_retries):
        try:
            return _connect_embedded_replica(local_path, url, token, do_sync=True)
        except Exception as e:
            last_error = e
            if _is_replica_metadata_missing_error(e) or _is_sqlite_malformed_error(e):
                _backup_broken_database_file(local_path, "Embedded Replica 状态损坏，已备份后重试")
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            break
    raise last_error or RuntimeError(f"无法建立云端连接: {url}")


def is_hub_configured() -> bool:
    return bool(TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN)


def _get_hub_conn(max_retries: int = 3, retry_delay: float = 1.0) -> Any:
    from config import get_force_cloud_mode

    if get_force_cloud_mode() and not is_hub_configured():
        raise RuntimeError("强制云端模式已启用，但未配置 TURSO_HUB_DB_URL/TURSO_HUB_AUTH_TOKEN")
    if get_force_cloud_mode() and not HAS_LIBSQL:
        raise RuntimeError("强制云端模式已启用，但 libsql 不可用")

    if TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN and HAS_LIBSQL:
        last_error = None
        for attempt in range(max_retries):
            try:
                return _get_hub_write_conn_singleton(
                    do_sync=False,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                )
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    _debug_log(f"云端 Hub 连接失败，回退本地: {e}", level="WARNING")
        if get_force_cloud_mode():
            raise RuntimeError(f"强制云端模式连接 Hub 失败 (已尝试 {max_retries} 次): {last_error}")

    if not get_force_cloud_mode():
        return _get_hub_local_conn()

    raise RuntimeError("强制云端模式已启用，但无法连接到云端 Hub 数据库")


def _get_dedicated_write_conn(db_path: Optional[str] = None) -> Any:
    _ = db_path
    return _get_main_write_conn_singleton(do_sync=False)


def _run_with_managed_connection(
    optional_conn: Any,
    conn_factory: Callable[[], Any],
    operation: Callable[[Any], Any],
) -> Any:
    owned = optional_conn is None
    target_conn = optional_conn or conn_factory()
    conn_lock = _get_singleton_conn_op_lock(target_conn)

    try:
        if conn_lock is not None:
            with conn_lock:
                result = operation(target_conn)
                if owned:
                    target_conn.commit()
        else:
            result = operation(target_conn)
            if owned:
                target_conn.commit()
        return result
    finally:
        if owned:
            try:
                if not _is_main_write_singleton_conn(target_conn) and not _is_hub_write_singleton_conn(target_conn):
                    target_conn.close()
            except Exception:
                pass


def _row_to_dict(cursor: Any, row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "asdict"):
        try:
            return row.asdict()
        except Exception:
            pass

    try:
        return dict(zip(row.keys(), tuple(row)))
    except AttributeError:
        if hasattr(row, "astuple") and hasattr(cursor, "description") and cursor.description:
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row.astuple()))
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))


def _hub_fetch_one_dict(sql: str, params: tuple = ()) -> Optional[dict]:
    """Hub single-row read.

    CRITICAL WalConflict fix:
    - Embedded Replica mode reuses hub write singleton.
    - No standalone local libsql read connections are created.
    """
    try:
        if TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN and HAS_LIBSQL:
            hub_conn = _get_hub_write_conn_singleton(do_sync=False)
        else:
            hub_conn = _get_hub_local_conn()

        conn_lock = _get_singleton_conn_op_lock(hub_conn)
        cur = hub_conn.cursor()
        try:
            if conn_lock is not None:
                with conn_lock:
                    try:
                        cur.execute(sql, params)
                        row = cur.fetchone()
                    finally:
                        cur.close()
                    hub_conn.commit()
            else:
                try:
                    cur.execute(sql, params)
                    row = cur.fetchone()
                finally:
                    cur.close()
                hub_conn.commit()
        finally:
            if conn_lock is None:
                try:
                    hub_conn.close()
                except Exception:
                    pass
        return _row_to_dict(cur, row) if row else None
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "hub_fetch_one_dict_corruption",
                f"_hub_fetch_one_dict 数据损坏异常: {e}",
                level="WARNING",
            )
            return None
        _debug_log(f"_hub_fetch_one_dict 异常: {e}", level="WARNING")
        return None


def _hub_fetch_all_dicts(sql: str, params: tuple = ()) -> List[dict]:
    """Hub multi-row read.

    CRITICAL WalConflict fix:
    - Embedded Replica mode reuses hub write singleton.
    - No standalone local libsql read connections are created.
    """
    try:
        if TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN and HAS_LIBSQL:
            hub_conn = _get_hub_write_conn_singleton(do_sync=False)
        else:
            hub_conn = _get_hub_local_conn()

        conn_lock = _get_singleton_conn_op_lock(hub_conn)
        cur = hub_conn.cursor()
        try:
            if conn_lock is not None:
                with conn_lock:
                    try:
                        cur.execute(sql, params)
                        rows = cur.fetchall()
                    finally:
                        cur.close()
                    hub_conn.commit()
            else:
                try:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
                finally:
                    cur.close()
                hub_conn.commit()
        finally:
            if conn_lock is None:
                try:
                    hub_conn.close()
                except Exception:
                    pass
        return [_row_to_dict(cur, row) for row in rows]
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "hub_fetch_all_dicts_corruption",
                f"_hub_fetch_all_dicts 数据损坏异常: {e}",
                level="WARNING",
            )
            return []
        _debug_log(f"_hub_fetch_all_dicts 异常: {e}", level="WARNING")
        return []


def set_runtime_cloud_credentials(url: Optional[str], token: Optional[str], hostname: Optional[str] = None) -> None:
    """Allow outer modules to update runtime main DB cloud credentials safely."""
    global TURSO_DB_URL, TURSO_AUTH_TOKEN, TURSO_DB_HOSTNAME
    TURSO_DB_URL = (url or "").strip() or None
    TURSO_AUTH_TOKEN = (token or "").strip() or None
    TURSO_DB_HOSTNAME = (hostname or "").strip() or None

# Imported from execution engine to maintain backward compatibility
from database.execution_engine import (
    _write_queue,
    _writer_daemon_stop_event,
    _write_queue_stats,
    _execute_batch_writes_unlocked,
    _execute_batch_writes,
    _writer_daemon,
    _sync_daemon,
    _start_writer_daemon,
    _start_sync_daemon,
    _stop_writer_daemon,
    _stop_sync_daemon,
    _queue_write_operation,
    _queue_batch_write_operation,
    init_concurrent_system,
    cleanup_concurrent_system,
    _release_db_file_handles_for_recovery,
    _mark_main_db_needs_sync,
    _execute_write_sql_sync,
    _execute_batch_write_sql_sync,
    get_write_queue_stats
)
