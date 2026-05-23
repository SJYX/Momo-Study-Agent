
from __future__ import annotations
"""
database/connection.py: 负责全局 turso.sync 单例连接管理、后台双守护线程调度及进程锁控制。
"""
# -*- coding: utf-8 -*-
"""Database connection infrastructure.

This module centralizes connection lifecycle, background writer/sync daemons,
and pyturso connection management.

Notes on pyturso semantics:
- pyturso uses MVCC, so multiple read connections to the same DB file are safe.
- The write singleton (`_main_write_conn_singleton`) is retained only for the
  do_sync=True path (init_db + explicit do_sync_on); other write paths open
  a fresh local connection each time via `_get_local_conn`.
"""

import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import config as _config
HUB_DB_PATH = _config.HUB_DB_PATH  # Hub 是全局静态库，不随 switch_user 变化，可缓存
TURSO_HUB_AUTH_TOKEN = _config.TURSO_HUB_AUTH_TOKEN
TURSO_HUB_DB_URL = _config.TURSO_HUB_DB_URL

# 注意：DB_PATH 不再缓存到本模块级。Phase 6.4 起 switch_user 不会反向 patch
# 任何 database 子模块的全局；所有需要"当前用户 DB 路径"的位置都直接读
# `_config.DB_PATH`（config 自己在 switch_user 时更新了模块级值）。

from database.backends import get_active_backend, HAS_PYTURSO

_backend = None  # Lazy init
_backend_lock = threading.Lock()


def _get_backend():
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = get_active_backend()
    return _backend

try:
    from core.logger import get_logger
except ImportError:
    try:
        from .logger import get_logger  # type: ignore
    except ImportError:
        import logging

        def get_logger():
            return logging.getLogger(__name__)


from .utils import (
    _backup_broken_database_file,
    _is_sqlite_data_corruption_error,
    _is_sqlite_malformed_error,
    _normalize_turso_url,
)


TURSO_TEST_DB_URL = os.getenv("TURSO_TEST_DB_URL")
TURSO_TEST_AUTH_TOKEN = os.getenv("TURSO_TEST_AUTH_TOKEN")
TURSO_TEST_DB_HOSTNAME = os.getenv("TURSO_TEST_DB_HOSTNAME")


# Background write/sync system state is now in database/execution_engine.py

_main_write_conn_singleton: Any = None
_main_write_conn_singleton_path: Optional[str] = None
_main_write_conn_last_check: float = 0
_main_write_conn_lock = threading.Lock()
_main_write_conn_init_lock = threading.Lock()

_hub_write_conn_singleton: Any = None
_hub_write_conn_lock = threading.Lock()
_hub_write_conn_init_lock = threading.Lock()


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




def _is_main_db_path(db_path: Optional[str] = None) -> bool:
    # Snapshot DB_PATH once to avoid TOCTOU race with prepare_for_task() patching
    current_db_path = _config.DB_PATH
    target = os.path.abspath(db_path or current_db_path)
    return target == os.path.abspath(current_db_path)


def _is_hub_db_path(db_path: Optional[str] = None) -> bool:
    target = os.path.abspath(db_path or HUB_DB_PATH)
    return target == os.path.abspath(HUB_DB_PATH)


def _is_replica_metadata_missing_error(error: Exception) -> bool:
    return False


def _resolve_conn_context(db_path: Optional[str] = None) -> Dict[str, Any]:
    path = db_path or _config.DB_PATH
    target_abs = os.path.abspath(path)
    main_abs = os.path.abspath(_config.DB_PATH)

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


def _close_main_write_conn_singleton() -> None:
    global _main_write_conn_singleton, _main_write_conn_singleton_path
    with _main_write_conn_lock:
        conn = _main_write_conn_singleton
        _main_write_conn_singleton = None
        _main_write_conn_singleton_path = None

    if conn is None:
        return

    try:
        conn.close()
        _debug_log(f"主库 {_get_backend().name} 写连接单例已关闭", level="INFO")
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
        _debug_log(f"Hub {_get_backend().name} 写连接单例已关闭", level="INFO")
    except Exception as e:
        _debug_log(f"关闭 Hub 写连接单例失败: {e}", level="WARNING")




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
    global _main_write_conn_singleton, _main_write_conn_singleton_path, _main_write_conn_last_check

    # 1. 第一阶段：快速获取当前单例引用并执行路径校验
    with _main_write_conn_lock:
        conn = _main_write_conn_singleton
        if conn is not None:
            current_path = os.path.abspath(_config.DB_PATH)
            if _main_write_conn_singleton_path and os.path.abspath(_main_write_conn_singleton_path) != current_path:
                _debug_log(f"主库单例路径切换: {_main_write_conn_singleton_path} -> {current_path}", level="INFO")
                try:
                    conn.close()
                except Exception:
                    pass
                _main_write_conn_singleton = None
                _main_write_conn_singleton_path = None
                conn = None

    # 2. 第二阶段：如果已有单例，在【锁外】进行健康检查（仅持操作锁）
    if conn is not None:
        try:
            now = time.time()
            if now - _main_write_conn_last_check > 1.0:
                conn.execute("SELECT 1")
                _main_write_conn_last_check = now
            if do_sync:
                _get_backend().do_sync_on(conn)
        except BaseException as health_error:
            _debug_log(f"主库写连接单例健康检查失败，准备重建: {health_error}", level="WARNING")
            with _main_write_conn_lock:
                if _main_write_conn_singleton is conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    _main_write_conn_singleton = None
                    _main_write_conn_singleton_path = None
            conn = None

    # 3. 第三阶段：如果不存在，进入初始化串行锁进行双重检查创建
    if conn is None:
        with _main_write_conn_init_lock:
            # 双重检查
            with _main_write_conn_lock:
                conn = _main_write_conn_singleton
            
            if conn is None:
                ctx = _resolve_conn_context(_config.DB_PATH)
                if not (ctx.get("url") and ctx.get("token") and (HAS_PYTURSO)):
                    return _get_local_conn(_config.DB_PATH)

                last_error = None
                for attempt in range(max_retries):
                    if attempt > 0:
                        _debug_log(f"主库写连接单例 重试 {attempt+1}/{max_retries}…", level="INFO")
                    try:
                        conn = _get_backend().connect(_config.DB_PATH, ctx["url"], ctx["token"], do_sync=do_sync)
                        with _main_write_conn_lock:
                            _main_write_conn_singleton = conn
                            _main_write_conn_singleton_path = os.path.abspath(_config.DB_PATH)
                            _debug_log(f"主库 {_get_backend().name} 写连接单例已创建 ({_main_write_conn_singleton_path})", level="INFO")
                        break
                    except Exception as e:
                        last_error = e
                        if _is_sqlite_malformed_error(e):
                            _backup_broken_database_file(_config.DB_PATH, "主库副本状态损坏，已备份后重试")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue
                        break
                
                if conn is None:
                    raise last_error or RuntimeError(f"无法创建主库 {_get_backend().name} 写连接单例")

    return conn



def _get_hub_write_conn_singleton(
    do_sync: bool = False,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> Any:
    global _hub_write_conn_singleton

    if not (TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN and (HAS_PYTURSO)):
        return _get_hub_local_conn()

    # 1. 第一阶段：获取当前 Hub 单例引用
    with _hub_write_conn_lock:
        conn = _hub_write_conn_singleton

    # 2. 第二阶段：健康检查（锁外进行，仅持操作锁）
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            if do_sync:
                _get_backend().do_sync_on(conn)
        except BaseException as health_error:
            _debug_log(f"Hub 写连接单例健康检查失败，准备重建: {health_error}", level="WARNING")
            with _hub_write_conn_lock:
                if _hub_write_conn_singleton is conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    _hub_write_conn_singleton = None
            conn = None

    # 3. 第三阶段：如果不存在，进入初始化串行锁进行双重检查创建
    if conn is None:
        with _hub_write_conn_init_lock:
            # 双重检查
            with _hub_write_conn_lock:
                conn = _hub_write_conn_singleton

            if conn is None:
                last_error = None
                for attempt in range(max_retries):
                    try:
                        _debug_log(f"[_get_hub_write_conn_singleton] 尝试 {attempt+1}/{max_retries}，连接 Hub...")
                        conn = _get_backend().connect(HUB_DB_PATH, TURSO_HUB_DB_URL, TURSO_HUB_AUTH_TOKEN, do_sync=do_sync)
                        _debug_log("[_get_hub_write_conn_singleton] backend.connect 返回成功")
                        with _hub_write_conn_lock:
                            _hub_write_conn_singleton = conn
                            _debug_log(f"Hub {_get_backend().name} 写连接单例已创建", level="INFO")
                        break
                    except Exception as e:
                        last_error = e
                        _debug_log(f"[_get_hub_write_conn_singleton] 尝试 {attempt+1} 失败: {e}", level="WARNING")
                        if _is_sqlite_malformed_error(e):
                            _backup_broken_database_file(HUB_DB_PATH, "Hub 副本状态损坏，已备份后重试")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue
                        break
                
                if conn is None:
                    raise last_error or RuntimeError(f"无法创建 Hub {_get_backend().name} 写连接单例")

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


def _get_dedicated_write_conn(db_path: Optional[str] = None) -> Any:
    path = db_path or _config.DB_PATH
    if _get_backend().name == "pyturso":
        return _get_local_conn(path)
    return _get_main_write_conn_singleton(do_sync=False)


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

# Re-exported for external consumers:
#   - database/_repo_helpers.py accesses 4 names via connection.X
#   - core/study_flow.py imports init_concurrent_system / cleanup_concurrent_system
from database.execution_engine import (
    _queue_write_operation,
    _queue_batch_write_operation,
    _execute_write_sql_sync,
    _execute_batch_write_sql_sync,
    init_concurrent_system,
    cleanup_concurrent_system,
)
