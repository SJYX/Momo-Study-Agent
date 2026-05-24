from __future__ import annotations
"""database/connection/singleton.py: 写连接单例 (主库 + Hub) 与其消费者。

pyturso 下写单例只在 `do_sync=True` 窄路径有意义 —— 即 init_db 的首次连接
与 do_sync_on(conn) 的显式触发,避免每次都重建一个 80~141s bootstrap
的连接。其他写路径走 `factory.py` 的 _get_local_conn 现开新连接 (MVCC
下安全,libsql 时代为避 WAL 互斥才必须用 singleton)。

依赖方向:本模块 import 自 `context`(纯助手) + `factory`(连接工厂)。
**factory 不反向 import 本模块**,只在函数体里 late import 才打破环。

模块级可变 globals (`_main_write_conn_singleton` 等) 的真实读取必须通过
本模块的属性访问 (`database.connection.singleton._main_write_conn_singleton`),
不能走 `from database.connection import _main_write_conn_singleton`(那会
变快照)。__init__.py 不 re-export 这些 globals,唯一外部消费者
(`web/backend/routers/ops.py`) 直接 import 本子模块。
"""

import os
import threading
import time
from typing import Any, Optional

import config as _config

from .context import (
    HAS_PYTURSO,
    HUB_DB_PATH,
    TURSO_HUB_AUTH_TOKEN,
    TURSO_HUB_DB_URL,
    _backup_broken_database_file,
    _debug_log,
    _get_backend,
    _is_sqlite_malformed_error,
    _resolve_conn_context,
)
from .factory import _get_local_conn, _get_hub_local_conn


# ---- write singleton 模块级状态 ----
_main_write_conn_singleton: Any = None
_main_write_conn_singleton_path: Optional[str] = None
_main_write_conn_last_check: float = 0
_main_write_conn_lock = threading.Lock()
_main_write_conn_init_lock = threading.Lock()

_hub_write_conn_singleton: Any = None
_hub_write_conn_lock = threading.Lock()
_hub_write_conn_init_lock = threading.Lock()


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


def _get_dedicated_write_conn(db_path: Optional[str] = None) -> Any:
    """打开一个独立的写连接。

    pyturso 模式 (当前唯一支持): 永远走 _get_local_conn 现开新连接,
    不复用 write singleton。这是因为 pyturso 用 MVCC,多个并发连接到
    同一 DB 文件是安全的;libsql 时代为了避开 WAL 互斥才必须用 singleton。

    Args:
        db_path: 目标 DB 路径,None 则用 _config.DB_PATH
    """
    path = db_path or _config.DB_PATH
    if _get_backend().name == "pyturso":
        return _get_local_conn(path)
    return _get_main_write_conn_singleton(do_sync=False)
