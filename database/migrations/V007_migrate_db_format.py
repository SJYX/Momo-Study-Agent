"""
V007_migrate_db_format.py: Detect and migrate .db format before pyturso.connect().

This migration runs BEFORE `turso.sync.connect()` opens the database file,
because pyturso requires exclusive access and cannot coexist with an open connection.

Strategy:
  1. Detect format via sidecar file inspection
  2. If already turso_sync or no file → no-op
  3. If libsql ER format or unknown → backup .db + delete all files → let pyturso bootstrap from remote

Called from `PytursoBackend.connect()` before `turso.sync.connect()`.
"""
from __future__ import annotations
import os
import shutil
from typing import Any


def _detect_format(db_path: str) -> str:
    """Detect .db file format using sidecar inspection.

    Returns:
        "turso_sync" — pyturso database (sidecar contains "turso-sync-py")
        "libsql_embedded_replica" — libsql ER format (sidecar exists but not pyturso)
        "unknown" — file exists but format cannot be determined (no sidecar or corrupt)
        "no_file" — file doesn't exist yet
    """
    if not os.path.exists(db_path):
        return "no_file"

    sidecar_path = db_path + "-info"
    has_sidecar = os.path.exists(sidecar_path)

    if has_sidecar:
        try:
            with open(sidecar_path, "rb") as f:
                sidecar_data = f.read(4096)
            sidecar_text = sidecar_data.decode("utf-8", errors="replace")
            if "turso-sync-py" in sidecar_text:
                return "turso_sync"
        except OSError:
            pass
        return "libsql_embedded_replica"

    # 无 sidecar → 无法确定格式，不应冒险当作 turso_sync
    return "unknown"


def _migrate_libsql_to_turso(db_path: str) -> str:
    """Backup old file + delete all db files. Let pyturso bootstrap from remote.

    Returns: backup_path
    """
    backup_path = db_path + ".pre_pyturso.bak"
    shutil.copy2(db_path, backup_path)

    for suffix in ("", "-info", "-wal", "-shm"):
        target = db_path + suffix
        if os.path.exists(target):
            try:
                os.remove(target)
            except OSError:
                pass

    return backup_path


def apply(cur: Any) -> None:
    """V007 migration entry point (called by runner).

    V007 is a pre-connect format migration handled by `pre_connect_migrate()`.
    By the time the runner calls this, format migration is already done.
    This is a no-op.
    """


def pre_connect_migrate(db_path: str) -> dict:
    """Migrate database format BEFORE pyturso.connect() opens the file.

    This is the primary entry point called from `PytursoBackend.connect()`.

    Returns dict with migration results:
        {"action": "migrated"|"skipped"|"no_file", "backup": path|None, "format": str}
    """
    fmt = _detect_format(db_path)

    if fmt == "no_file":
        return {"action": "no_file", "backup": None, "format": fmt}

    if fmt == "turso_sync":
        return {"action": "skipped", "backup": None, "format": fmt}

    # libsql_embedded_replica 或 unknown → 备份 + 删除，让 pyturso 从远端重新拉
    if fmt in ("libsql_embedded_replica", "unknown"):
        backup = _migrate_libsql_to_turso(db_path)
        return {"action": "migrated", "backup": backup, "format": fmt}

    return {"action": "skipped", "backup": None, "format": fmt}
