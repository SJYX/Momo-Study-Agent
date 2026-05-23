"""
V007_migrate_db_format.py: Detect and migrate .db format before pyturso.connect().

This migration runs BEFORE `turso.sync.connect()` opens the database file,
because pyturso requires exclusive access and cannot coexist with an open connection.

Strategy:
  1. Detect format via sidecar file inspection
  2. If already turso_sync or no file → no-op
  3. If libsql ER format → backup (rename) + delete → let pyturso bootstrap from remote
  4. If unknown format → probe SQLite for app tables AND data readability:
     - Has readable app tables → preserve in place (valid local DB, pyturso can use it)
     - Has tables but all malformed → quarantine (failed bootstrap residue)
     - No tables / corrupt → backup (rename) + delete

Called from `PytursoBackend.connect()` before `turso.sync.connect()`.

Safety guarantees:
  - NEVER delete a file that contains readable application data
  - Use rename instead of copy+delete for atomic backup
  - Deep-probe: checks COUNT(*) on each table, not just sqlite_master
"""
from __future__ import annotations
import os
import shutil
import sqlite3
from typing import Any, Optional


def _detect_format(db_path: str) -> str:
    """Detect .db file format using sidecar inspection.

    Returns:
        "turso_sync" — pyturso database (sidecar contains "turso-sync-py")
        "unknown" — file exists but format cannot be determined (no sidecar or non-pyturso sidecar)
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

    # 无 sidecar 或不属于 pyturso 的 sidecar → 均判定为 unknown 格式
    return "unknown"


def _has_application_tables(db_path: str) -> bool:
    """Check if a SQLite file contains our application tables AND ALL are readable.

    Two-phase probe:
      1. Check sqlite_master for application tables (lightweight)
      2. Verify ALL tables are readable via COUNT(*) (deep probe)

    Returns True only if tables exist AND every single one is readable.
    If ANY table is malformed (btreeInitPage errors), returns False —
    the file is a corrupted bootstrap artifact and should be quarantined.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", timeout=2.0, uri=True)
        try:
            cur = conn.cursor()

            # Phase 1: 检查 sqlite_master 中是否有应用表
            cur.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
            app_tables = [r[0] for r in cur.fetchall()]

            if not app_tables:
                return False

            # Phase 2: 深度探测——ALL 表必须可读
            # 任何一张表 malformed → 整个文件是损坏的 bootstrap 产物
            for table_name in app_tables:
                try:
                    cur.execute(
                        f"SELECT COUNT(*) FROM [{table_name}]"  # noqa: S608
                    )
                    cur.fetchone()
                except Exception:
                    # 任意核心表不可读 → 判定为损坏
                    return False

            return True
        finally:
            conn.close()
    except Exception:
        return False


def _is_valid_sqlite_file(db_path: str) -> bool:
    """Quick check: does the file start with the SQLite magic header?"""
    try:
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            return False
        with open(db_path, "rb") as f:
            header = f.read(16)
        return bool(header and header.startswith(b"SQLite format 3"))
    except Exception:
        return False


def _safely_quarantine(db_path: str, reason: str = "") -> str:
    """Rename the database file to a quarantine path instead of deleting.

    Uses atomic os.replace to avoid leaving half-deleted files.

    Returns: quarantine path
    """
    import time
    ts = int(time.time())
    quarantine_path = f"{db_path}.quarantined_{ts}.bak"

    # Clean up any previous quarantine with same pattern (keep latest)
    import glob
    for old in glob.glob(f"{db_path}.quarantined_*.bak"):
        try:
            os.remove(old)
        except OSError:
            pass

    # Atomic rename
    os.replace(db_path, quarantine_path)

    # Also remove sidecar files
    for suffix in ("-info", "-wal", "-shm"):
        sidecar = db_path + suffix
        if os.path.exists(sidecar):
            try:
                os.remove(sidecar)
            except OSError:
                pass

    return quarantine_path





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
        {"action": "migrated"|"skipped"|"no_file"|"preserved", "backup": path|None, "format": str}

    Actions:
        no_file   — file doesn't exist, nothing to do
        skipped   — already turso_sync format, no action needed
        migrated  — was libsql ER format, backed up + deleted for pyturso bootstrap
        preserved — was unknown format but contains valid app data, kept in place
    """
    fmt = _detect_format(db_path)

    if fmt == "no_file":
        return {"action": "no_file", "backup": None, "format": fmt}

    if fmt == "turso_sync":
        return {"action": "skipped", "backup": None, "format": fmt}



    if fmt == "unknown":
        # CRITICAL: Don't blindly delete. Probe the file for application data.
        #
        # Scenario 1: Local-only user created via Web wizard (no cloud, no sidecar).
        #   → Has ai_word_notes table → PRESERVE. pyturso can use raw SQLite files.
        #
        # Scenario 2: Corrupt or empty file with no sidecar.
        #   → No tables / not valid SQLite → quarantine + delete.
        #
        # Scenario 3: Old libsql ER whose sidecar was deleted.
        #   → No app tables → quarantine (safer than instant delete).
        if _is_valid_sqlite_file(db_path) and _has_application_tables(db_path):
            # Valid local database with real data — keep it in place.
            # pyturso.sync.connect() can use existing SQLite files without a sidecar;
            # it will create the sidecar on first connect.
            return {"action": "preserved", "backup": None, "format": fmt}

        # No useful data — quarantine (rename) instead of instant delete.
        # This gives users a recovery path if the probe was wrong.
        quarantine = _safely_quarantine(db_path, reason="unknown_format_no_data")
        return {"action": "migrated", "backup": quarantine, "format": fmt}

    return {"action": "skipped", "backup": None, "format": fmt}
