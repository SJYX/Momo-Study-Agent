"""
database/session.py: 数据库上下文管理器与装饰器，消除冗余模板代码。
"""
from typing import Any, Callable, List, Optional, TypeVar
from contextlib import contextmanager
import functools
import time

from database import connection
from database.utils import _is_sqlite_data_corruption_error, _debug_log, _backup_broken_database_file, _hash_fingerprint
from database.schema import _create_tables
import config as _config
from config import DATA_DIR
from core.logger import get_logger

T = TypeVar('T')

class DBSession:
    """包装了连接与 backend 的会话对象。

    PytursoBackend 使用原生 MVCC 并发，无需外部锁。
    """

    def __init__(self, conn: Any, backend: Any = None):
        self.conn = conn
        self._backend = backend

    def fetchall(self, sql: str, params: tuple = ()) -> List[Any]:
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[Any]:
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchone()
        finally:
            cur.close()

    def execute(self, sql: str, params: tuple = ()) -> None:
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
        finally:
            cur.close()
        self.conn.commit()

    def executemany(self, sql: str, params_list: List[tuple]) -> None:
        cur = self.conn.cursor()
        try:
            cur.executemany(sql, params_list)
        finally:
            cur.close()
        self.conn.commit()


def _attempt_auto_recovery(db_path: str) -> bool:
    """尝试自动修复损坏的 SQLite 数据库，优先使用云端数据重建，否则重新创建空表。"""
    try:
        from database.execution_engine import _release_db_file_handles_for_recovery
        _release_db_file_handles_for_recovery(db_path)
        backup_path = _backup_broken_database_file(db_path, "检测到本地数据库损坏，已备份本地数据库")
        if not backup_path:
            _debug_log("损坏库备份未完成（源文件可能被占用），继续尝试云端/本地重建", level="WARNING", module="database.session")

        ctx = connection._resolve_conn_context(db_path)
        if (connection.HAS_PYTURSO) and ctx.get("url") and ctx.get("token"):
            _debug_log(f"尝试从 Turso 云端重建损坏的数据库: {db_path}", level="INFO", module="database.session")
            repair_conn = connection._get_conn(db_path, allow_local_fallback=False, do_sync=True)
            try:
                repair_conn.close()
            except Exception:
                pass
            return True

        _debug_log(f"没有云端凭证，尝试在本地重建空的数据库表: {db_path}", level="INFO", module="database.session")
        local_conn = connection._get_local_conn(db_path)
        try:
            _create_tables(local_conn.cursor())
            local_conn.commit()
        finally:
            try:
                local_conn.close()
            except Exception:
                pass
        return True
    except Exception as recovery_error:
        _debug_log(f"数据库自动恢复彻底失败: {recovery_error}", level="ERROR", module="database.session")
        return False


def with_read_session(default_return: Any = None, fallback_on_corruption: bool = True):
    """
    提供读连接会话的装饰器。
    
    业务函数需提供形如 `session: DBSession = None` 的参数（如果没有，装饰器会通过 kwargs 注入）。
    自动处理底层连接的获取、并发锁的包裹、异常（包括 SQLite 损坏兜底）以及单例的释放。
    包含一次自动重建损坏数据库并重试的机制。
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # 如果外界直接传了 session，就复用
            if 'session' in kwargs and kwargs['session'] is not None:
                return func(*args, **kwargs)
                
            db_path = kwargs.get('db_path') or _config.DB_PATH
            _recovery_attempted = kwargs.pop('_recovery_attempted', False)
            c = None
            from database.backends import get_active_backend
            try:
                started = time.time()
                c = connection._get_read_conn(db_path)
                session = DBSession(c, backend=get_active_backend())
                kwargs['session'] = session
                
                res = func(*args, **kwargs)
                
                elapsed = int((time.time() - started) * 1000)
                if elapsed > 100:  # slow query logging
                    _debug_log(f"Slow Query in {func.__name__}: {elapsed}ms", level="DEBUG")
                    
                return res
            except Exception as e:
                # schema changed → invalidate pool + retry with fresh connection
                if "schema changed" in str(e).lower() and not _recovery_attempted:
                    _debug_log(
                        f"{func.__name__} 检测到 schema 变更，重建读连接后重试",
                        level="WARNING",
                        module=func.__module__,
                    )
                    try:
                        from database.connection import _invalidate_read_conn_pool
                        _invalidate_read_conn_pool(db_path)
                    except Exception:
                        try:
                            if c is not None:
                                c.close()
                        except Exception:
                            pass
                    kwargs.pop("session", None)
                    kwargs["_recovery_attempted"] = True
                    return wrapper(*args, **kwargs)

                if fallback_on_corruption and _is_sqlite_data_corruption_error(e):
                    if not _recovery_attempted:
                        get_logger().warning_throttled(
                            f"{func.__name__}_corruption_recovery",
                            f"{func.__name__} 检测到数据损坏: {e}，正在尝试自动恢复...",
                            module=func.__module__,
                        )

                        # 确保关闭损坏的连接后再恢复
                        try:
                            if c is not None:
                                c.close()
                        except Exception:
                            pass

                        if _attempt_auto_recovery(db_path):
                            kwargs.pop('session', None)  # 移除旧的 session
                            kwargs['_recovery_attempted'] = True
                            return wrapper(*args, **kwargs) # 重试

                    get_logger().error_throttled(
                        f"{func.__name__}_corruption_final",
                        f"{func.__name__} 数据损坏且恢复失败: {e}",
                        module=func.__module__,
                    )
                    return default_return
                _debug_log(f"{func.__name__} 异常: {e}", level="WARNING", module=func.__module__)
                return default_return
            finally:
                try:
                    if c is not None:
                        c.close()
                except Exception:
                    pass
        return wrapper
    return decorator


def with_write_session(default_return: Any = None, fallback_on_corruption: bool = True):
    """提供直接写连接会话的装饰器（如果是通过 execution_engine，可能走 queue_write）"""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            if 'session' in kwargs and kwargs['session'] is not None:
                return func(*args, **kwargs)
                
            db_path = kwargs.get('db_path') or _config.DB_PATH
            c = None
            from database.backends import get_active_backend
            try:
                c = connection._get_conn(db_path)
                session = DBSession(c, backend=get_active_backend())
                kwargs['session'] = session
                
                res = func(*args, **kwargs)
                
                from database.execution_engine import _mark_main_db_needs_sync
                _mark_main_db_needs_sync(db_path=db_path, conn=c)
                
                return res
            except Exception as e:
                if fallback_on_corruption and _is_sqlite_data_corruption_error(e):
                    get_logger().warning_throttled(
                        f"{func.__name__}_corruption",
                        f"{func.__name__} 写入数据损坏异常: {e}",
                        module=func.__module__,
                    )
                    return default_return
                _debug_log(f"{func.__name__} 写入异常: {e}", level="WARNING", module=func.__module__)
                return default_return
            finally:
                try:
                    if c is not None:
                        c.close()
                except Exception:
                    pass
        return wrapper
    return decorator
