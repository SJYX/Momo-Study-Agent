from __future__ import annotations
"""database/connection/context.py: 连接管理的纯助手层。

包含模块级常量、backend 单例、日志助手、路径谓词、连接上下文解析等
**不持有可变状态、不调用其他子模块** 的辅助代码。

`factory.py` 与 `singleton.py` 都 import 自这里。它本身只 import 自
`database.backends` / `database.utils` / `core.logger`,无任何环依赖。
"""

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple  # noqa: F401 (re-export)

import config as _config

HUB_DB_PATH = _config.HUB_DB_PATH  # Hub 是全局静态库，不随 switch_user 变化，可缓存
TURSO_HUB_AUTH_TOKEN = _config.TURSO_HUB_AUTH_TOKEN
TURSO_HUB_DB_URL = _config.TURSO_HUB_DB_URL

# 注意：DB_PATH 不缓存到本模块级。switch_user 不会反向 patch database 子模块的全局；
# 所有需要"当前用户 DB 路径"的位置都直接读 `_config.DB_PATH`。

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


from database.utils import (
    _backup_broken_database_file,
    _is_sqlite_data_corruption_error,
    _is_sqlite_malformed_error,
    _normalize_turso_url,
)


TURSO_TEST_DB_URL = os.getenv("TURSO_TEST_DB_URL")
TURSO_TEST_AUTH_TOKEN = os.getenv("TURSO_TEST_AUTH_TOKEN")
TURSO_TEST_DB_HOSTNAME = os.getenv("TURSO_TEST_DB_HOSTNAME")


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

    This avoids importing business/schema modules from connection.* directly.
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
