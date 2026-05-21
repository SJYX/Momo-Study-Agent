from __future__ import annotations

"""Libsql embedded-replica backend implementation.

Wraps the existing libsql.connect logic from database/connection.py into
a TursoBackend-compliant class.  This module must NOT import from
database.connection (circular-import risk).
"""

import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

# ── libsql availability (集中探针) ──
from database.backends import HAS_LIBSQL

# ── helpers from database.utils (no circular import) ──
from database.utils import _cleanup_stale_sidecars, _debug_log


# ═══════════════════════════════════════════════════════════════
# Helper functions (moved from database/connection.py)
# ═══════════════════════════════════════════════════════════════


def _query_turso_db_size(url: str) -> int:
    """Query Turso API for database total size (bytes). Returns 0 on failure."""
    try:
        import requests
    except ImportError:
        return 0

    api_token = os.getenv("TURSO_API_TOKEN", "")
    org = os.getenv("TURSO_ORGANIZATION", "")
    if not api_token:
        return 0

    # Parse DB name from URL: libsql://db-name-org.region.turso.io
    host = url.replace("libsql://", "").replace("https://", "")
    subdomain = host.split(".")[0]

    if not org:
        parts = subdomain.rsplit("-", 1)
        if len(parts) == 2:
            org = parts[1]
        else:
            return 0

    # db name = subdomain minus "-{org}" suffix
    if subdomain.endswith(f"-{org}"):
        db_name = subdomain[: -(len(org) + 1)]
    else:
        db_name = subdomain

    try:
        _debug_log(f"[libsql] 查询云端数据库大小 (org={org}, db={db_name})", level="INFO", module="database.backends._libsql")
        resp = requests.get(
            f"https://api.turso.tech/v1/organizations/{org}/databases/{db_name}",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=10,
        )
        if not resp.ok:
            _debug_log(f"[libsql] Turso API 返回 {resp.status_code}，跳过大小查询", level="WARNING", module="database.backends._libsql")
            return 0

        data = resp.json()
        db_info = data.get("database", data)

        size = (
            db_info.get("size")
            or db_info.get("Size")
            or db_info.get("size_bytes")
            or db_info.get("db_size")
            or 0
        )
        if not size:
            usage = db_info.get("usage", db_info.get("Usage", {}))
            if isinstance(usage, dict):
                size = usage.get("storage_bytes") or usage.get("size") or 0

        size = int(size)
        if size > 0:
            _debug_log(f"[libsql] 云端数据库总大小: {size / 1024 / 1024:.1f} MB", level="INFO", module="database.backends._libsql")
        return size
    except Exception as e:
        _debug_log(f"[libsql] 查询数据库大小失败（可忽略）: {e}", level="WARNING", module="database.backends._libsql")
        return 0


def _start_pull_monitor(db_path: str, total_bytes: int) -> Optional[subprocess.Popen]:
    """Start subprocess to monitor initial pull download progress. Returns None on failure."""
    # __file__ = database/backends/_libsql.py → 3x dirname to reach project root
    _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    monitor_script = os.path.join(_project_root, "scripts", "_pull_monitor.py")
    if not os.path.exists(monitor_script):
        _debug_log("[libsql] 监控脚本不存在，跳过进度显示", level="WARNING", module="database.backends._libsql")
        return None

    try:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen(
            [sys.executable, monitor_script, db_path, str(total_bytes), str(os.getpid())],
            stdout=sys.stdout,
            stderr=sys.stderr,
            env=env,
        )
        return proc
    except Exception as e:
        _debug_log(f"[libsql] 启动监控子进程失败（可忽略）: {e}", level="WARNING", module="database.backends._libsql")
        return None


# ═══════════════════════════════════════════════════════════════
# TursoBackend implementation
# ═══════════════════════════════════════════════════════════════


class LibsqlBackend:
    """TursoBackend implementation wrapping libsql embedded replicas."""

    name = "libsql"

    def __init__(self):
        self._main_lock = threading.Lock()
        self._hub_lock = threading.Lock()

    @contextmanager
    def op_lock_for(self, conn: Any) -> Iterator[None]:
        """根据连接类型分发到 main 或 hub 锁。"""
        lock = self._resolve_lock(conn)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def _resolve_lock(self, conn: Any) -> threading.Lock:
        """判断 conn 属于 main 还是 hub，返回对应锁。"""
        role = getattr(conn, "_momo_db_role", None)
        if role == "hub":
            return self._hub_lock
        return self._main_lock

    def is_supported(self) -> bool:
        """Check whether the libsql C library is importable at runtime."""
        return HAS_LIBSQL

    def connect(
        self,
        db_path: str,
        url: str,
        token: str,
        *,
        do_sync: bool = False,
    ) -> Any:
        """Create an embedded-replica connection via libsql.connect.

        Mirrors the logic previously in database.connection._connect_embedded_replica.
        """
        if not HAS_LIBSQL:
            raise RuntimeError("libsql is not available")

        final_url = url.replace("libsql://", "https://")
        _debug_log(
            f"[libsql] db_path={db_path}, url={final_url[:50]}..., do_sync={do_sync}",
            module="database.backends._libsql",
        )

        # ── sidecar cleanup ──
        has_existing_db = os.path.exists(db_path)
        has_metadata = os.path.exists(db_path + "-info") if has_existing_db else False

        if not has_existing_db:
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            _cleanup_stale_sidecars(os.path.abspath(db_path))
        elif not has_metadata:
            try:
                db_size = os.path.getsize(db_path)
            except OSError:
                db_size = 0
            _debug_log(
                f"[libsql] .db 文件存在 ({db_size} 字节) 但无元数据，"
                f"删除后重新拉取云端数据",
                level="WARNING",
                module="database.backends._libsql",
            )
            try:
                os.remove(db_path)
                has_existing_db = False
            except OSError:
                pass
            _cleanup_stale_sidecars(os.path.abspath(db_path))

        needs_initial_pull = not has_existing_db or not has_metadata
        monitor_proc = None

        db_label = "Hub" if "hub" in os.path.basename(db_path).lower() else "主库"

        if needs_initial_pull:
            total_size = _query_turso_db_size(url)
            if total_size > 0:
                _debug_log(
                    f"[{db_label}] 本地无有效副本（db={'存在' if has_existing_db else '不存在'}, "
                    f"metadata={'存在' if has_metadata else '不存在'}），正在连接云端并执行 initial pull...",
                    level="INFO",
                    module="database.backends._libsql",
                )
            else:
                _debug_log(
                    f"[{db_label}] 本地无有效副本，正在连接云端并执行 initial pull... "
                    f"（未配置 TURSO_API_TOKEN，仅显示绝对大小）",
                    level="INFO",
                    module="database.backends._libsql",
                )
            monitor_proc = _start_pull_monitor(db_path, total_size)
        else:
            _debug_log(f"[{db_label}] 本地已有副本，正在连接...", level="INFO", module="database.backends._libsql")

        _t0 = time.time()
        try:
            conn = libsql.connect(
                db_path,
                sync_url=final_url,
                auth_token=token,
                timeout=30.0,
                _check_same_thread=False,
            )
        except Exception as e:
            _debug_log(
                f"[{db_label}] libsql.connect 失败: {type(e).__name__}: {e}",
                level="ERROR",
                module="database.backends._libsql",
            )
            raise
        finally:
            if monitor_proc is not None:
                try:
                    monitor_proc.terminate()
                    monitor_proc.wait(timeout=3)
                except Exception:
                    try:
                        monitor_proc.kill()
                    except Exception:
                        pass

        _elapsed = time.time() - _t0

        try:
            final_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        except OSError:
            final_size = 0

        if needs_initial_pull:
            _debug_log(
                f"[{db_label}] 连接完成，本地 DB: {final_size / 1024 / 1024:.1f} MB (耗时 {_elapsed:.1f}s)",
                level="INFO",
                module="database.backends._libsql",
            )
        else:
            _debug_log(f"[{db_label}] libsql.connect 返回成功 (耗时 {_elapsed:.1f}s)", level="INFO", module="database.backends._libsql")

        try:
            conn.execute("PRAGMA busy_timeout=30000;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except Exception as e:
            _debug_log(f"Embedded Replica PRAGMA 配置失败（可忽略）: {e}", level="WARNING", module="database.backends._libsql")

        # Post-pull WAL checkpoint for stability
        if needs_initial_pull:
            try:
                _debug_log(f"[{db_label}] 初始 pull 后执行 WAL CHECKPOINT 稳定化...", level="INFO", module="database.backends._libsql")
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                _debug_log(f"[{db_label}] WAL CHECKPOINT 完成，连接已稳定", level="INFO", module="database.backends._libsql")
            except Exception as e:
                _debug_log(f"[{db_label}] WAL CHECKPOINT 失败（可忽略）: {e}", level="WARNING", module="database.backends._libsql")

        if do_sync and hasattr(conn, "sync"):
            # Lazy imports to avoid circular dependency
            try:
                from database.execution_engine import clear_db_syncing, set_db_syncing

                set_db_syncing(phase="initial_sync")
            except ImportError:
                set_db_syncing = None  # type: ignore[assignment]
                clear_db_syncing = None  # type: ignore[assignment]

            _debug_log("[libsql] 执行 conn.sync()...", module="database.backends._libsql")
            _t1 = time.time()
            try:
                conn.sync()
            finally:
                _sync_elapsed = time.time() - _t1
                _debug_log(f"[libsql] conn.sync() 完成 (耗时 {_sync_elapsed:.1f}s)", level="INFO", module="database.backends._libsql")
                if clear_db_syncing is not None:
                    clear_db_syncing()

        conn._momo_db_role = "hub" if "hub" in os.path.basename(db_path).lower() else "main"
        return conn

    def do_sync_on(self, conn: Any) -> None:
        """Trigger a sync on an existing embedded-replica connection."""
        if hasattr(conn, "sync"):
            conn.sync()
