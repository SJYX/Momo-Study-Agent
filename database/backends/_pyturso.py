from __future__ import annotations

"""Pyturso sync backend implementation.

Wraps turso.sync.connect() into a TursoBackend-compliant class.
This module must NOT import from database.connection (circular-import risk).
"""

import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

# ── pyturso availability (集中探针) ──
from database.backends import HAS_PYTURSO

# ── helpers from database.utils (no circular import) ──
from database.utils import _debug_log

# ── V007 format migration (lazy-imported inside connect) ──


# ═══════════════════════════════════════════════════════════════
# TursoBackend implementation
# ═══════════════════════════════════════════════════════════════


class PytursoBackend:
    """TursoBackend implementation wrapping turso.sync (pyturso)."""

    name = "pyturso"

    @contextmanager
    def op_lock_for(self, conn: Any) -> Iterator[None]:
        """pyturso 引擎原生 MVCC，无需外部锁。"""
        yield

    def is_supported(self) -> bool:
        """Check whether turso.sync is importable at runtime."""
        return HAS_PYTURSO

    def connect(
        self,
        db_path: str,
        url: str,
        token: str,
        *,
        do_sync: bool = False,
    ) -> Any:
        """Create a pyturso Turso Sync connection.

        Lifecycle per official Turso Sync docs:
          1. V007 format migration (before pyturso opens the file)
          2. turso.sync.connect() — auto-bootstraps from remote when local db is empty
             (bootstrap_if_empty=True default; NO explicit pull needed after connect)
          3. For existing databases: pull() to fetch latest remote changes
          4. If do_sync: push -> pull -> checkpoint (full sync cycle)
        """
        if not HAS_PYTURSO:
            raise RuntimeError("pyturso is not available")

        import turso

        final_url = url.replace("libsql://", "https://")
        _debug_log(
            f"[pyturso] db_path={db_path}, url={final_url[:50]}...",
            module="database.backends._pyturso",
        )

        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        # 清理残留 sidecar（.db 不存在时），防止 V007 格式检测误判
        if not os.path.exists(db_path):
            from database.utils import _cleanup_stale_sidecars
            _cleanup_stale_sidecars(os.path.abspath(db_path))

        db_label = "Hub" if "hub" in os.path.basename(db_path).lower() else "主库"

        # ── Step 1: V007 format migration (仅当文件真实存在且包含数据时才执行) ──
        # 拦截掉空文件生成，保护 pyturso 的 bootstrap 机制
        try:
            if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
                from database.migrations.V007_migrate_db_format import pre_connect_migrate

                pre_connect_migrate(db_path)
            else:
                _debug_log(
                    f"[{db_label}] 这是一个新库或空库，跳过 V007 历史迁移...",
                    level="INFO",
                    module="database.backends._pyturso",
                )
        except Exception as e:
            _debug_log(
                f"[{db_label}] V007: 格式迁移失败（非致命，继续尝试连接）: {e}",
                level="WARNING",
                module="database.backends._pyturso",
            )

        # Track whether db file exists BEFORE connect — determines if bootstrap runs.
        # Use a stricter check: file must exist, be non-empty, and look like a SQLite file.
        def _is_valid_sqlite(fp: str) -> bool:
            try:
                if not os.path.exists(fp) or os.path.getsize(fp) == 0:
                    return False
                with open(fp, "rb") as f:
                    header = f.read(16)
                return bool(header and header.startswith(b"SQLite format 3"))
            except Exception:
                return False

        db_existed_before = _is_valid_sqlite(db_path)

        # ── Step 2: Create pyturso sync connection ──
        # Official docs: "On the first run, the local database is automatically
        # bootstrapped from the remote." No explicit pull needed after connect.
        _t0 = time.time()
        db = turso.sync.connect(
            db_path,
            remote_url=final_url,
            auth_token=token,
        )
        _elapsed = time.time() - _t0
        _debug_log(
            f"[{db_label}] turso.sync.connect 完成 (耗时 {_elapsed:.1f}s)",
            level="INFO",
            module="database.backends._pyturso",
        )

        try:
            db.execute("PRAGMA busy_timeout=30000;")
            db.execute("PRAGMA synchronous=NORMAL;")
        except Exception as e:
            _debug_log(
                f"pyturso PRAGMA 配置失败（可忽略）: {e}",
                level="WARNING",
                module="database.backends._pyturso",
            )

        # ── Step 2.5: Checkpoint to flush bootstrap WAL data to main db file ──
        # pyturso's connect() may leave bootstrap data in WAL without checkpointing.
        # Without this, the .db file has invalid btree pages (corruption).
        # Also creates the .db-info sidecar that pyturso uses for sync state.
        try:
            db.checkpoint()
            _debug_log(
                f"[{db_label}] connect 后 checkpoint 完成",
                level="INFO",
                module="database.backends._pyturso",
            )
        except Exception as e:
            _debug_log(
                f"[{db_label}] connect 后 checkpoint 失败（非致命）: {e}",
                level="WARNING",
                module="database.backends._pyturso",
            )

        # ── Step 3: Pull for existing databases (bootstrap already handled new ones) ──
        if db_existed_before and not do_sync:
            try:
                _debug_log(
                    f"[{db_label}] 数据库已存在，pull 远端最新变更…",
                    level="INFO",
                    module="database.backends._pyturso",
                )
                changed = db.pull()

                # 若 pull 真正应用了远端变更，立即 checkpoint 将 WAL 数据落盘到主文件，
                # 避免返回后未落盘导致外部工具打开 .db 时出现 corrupted/empty 情况。
                try:
                    if changed:
                        db.checkpoint()
                        _debug_log(
                            f"[{db_label}] pull 之后执行 checkpoint 落盘成功",
                            level="INFO",
                            module="database.backends._pyturso",
                        )
                except Exception as e:
                    _debug_log(
                        f"[{db_label}] pull 后 checkpoint 失败（非致命）: {e}",
                        level="WARNING",
                        module="database.backends._pyturso",
                    )

                _debug_log(
                    f"[{db_label}] pull 完成 (changed={changed})",
                    level="INFO",
                    module="database.backends._pyturso",
                )
            except Exception as e:
                _debug_log(
                    f"[{db_label}] pull 失败（非致命）: {e}",
                    level="WARNING",
                    module="database.backends._pyturso",
                )

        # ── Step 4: Full sync cycle if requested ──
        if do_sync:
            try:
                db.push()
                db.pull()
                db.checkpoint()
                _debug_log(
                    f"[{db_label}] 同步完成 (push→pull→checkpoint)",
                    level="INFO",
                    module="database.backends._pyturso",
                )
            except Exception as e:
                _debug_log(
                    f"[{db_label}] 同步失败: {e}",
                    level="WARNING",
                    module="database.backends._pyturso",
                )

        db._momo_db_role = "hub" if "hub" in os.path.basename(db_path).lower() else "main"
        return db

    def do_sync_on(self, conn: Any) -> None:
        """Trigger a full sync cycle (push → pull → checkpoint) on an existing pyturso connection."""
        if hasattr(conn, "pull"):
            try:
                conn.push()
                conn.pull()
                conn.checkpoint()
            except Exception as e:
                _debug_log(
                    f"[pyturso] do_sync_on 失败: {e}",
                    level="WARNING",
                    module="database.backends._pyturso",
                )
