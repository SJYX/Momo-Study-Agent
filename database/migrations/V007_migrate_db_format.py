"""
V007_migrate_db_format.py: Migrate .db from libsql Embedded Replica format to pyturso format.

This migration must run BEFORE `turso.sync.connect()` opens the database file,
because pyturso requires exclusive access and cannot coexist with an open connection.

Strategy:
  1. Detect format via sqlite3 (no remote_url needed)
  2. If already turso_sync or no file → no-op
  3. If libsql ER format → backup .db + delete sidecars → let pyturso bootstrap from remote

Called from `_connect_turso_sync()` before `turso.sync.connect()`.
"""
from __future__ import annotations
import os
import shutil
import sqlite3
from typing import Any

# SQLite internal table prefixes to filter during iterdump
_INTERNAL_PREFIXES = ("sqlite_sequence", "_litestream_", "sqlite_")


def _detect_format(db_path: str) -> str:
    """Detect .db file format using sqlite3 (no remote connection needed).

    Both libsql ER and pyturso create a .db-info sidecar file, but their
    contents differ:
    - pyturso: contains "turso-sync-py" in client_unique_id
    - libsql ER: contains replica_id, sync_url, etc.

    Returns:
        "turso_sync" — pyturso database, no migration needed
        "libsql_embedded_replica" — libsql ER format, needs migration
        "unknown" — file exists but format unclear
        "no_file" — file doesn't exist yet
    """
    if not os.path.exists(db_path):
        return "no_file"

    sidecar_path = db_path + "-info"
    has_sidecar = os.path.exists(sidecar_path)

    if has_sidecar:
        # Check sidecar content to distinguish pyturso from libsql ER
        try:
            with open(sidecar_path, "rb") as f:
                sidecar_data = f.read(4096)  # Read first 4KB — enough for format detection
            sidecar_text = sidecar_data.decode("utf-8", errors="replace")
            if "turso-sync-py" in sidecar_text:
                return "turso_sync"  # pyturso's own sidecar, not libsql ER
        except OSError:
            pass
        # Sidecar exists but not pyturso → treat as libsql ER
        return "libsql_embedded_replica"

    # No sidecar: verify it's a valid SQLite file
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        finally:
            conn.close()
        # WAL files present but no sidecar: likely pyturso format (pyturso uses WAL internally)
        return "turso_sync"
    except (sqlite3.DatabaseError, sqlite3.OperationalError):
        return "unknown"


def _migrate_libsql_to_turso(db_path: str, do_schema_migrations: bool = True) -> str:
    """Migrate libsql ER .db to pyturso-compatible format.

    Strategy: backup old file → delete sidecars → let pyturso create fresh file
    and bootstrap from remote.

    Returns: backup_path
    """
    backup_path = db_path + ".pre_pyturso.bak"
    shutil.copy2(db_path, backup_path)
    print(f"V007: Backed up {db_path} → {backup_path}")

    # Delete all libsql ER files
    for suffix in ("", "-info", "-wal", "-shm"):
        target = db_path + suffix
        if os.path.exists(target):
            try:
                os.remove(target)
                print(f"V007: Deleted {target}")
            except OSError as e:
                print(f"V007: Warning — failed to delete {target}: {e}")

    # After deletion, pyturso.connect() will do a clean bootstrap from remote.
    # Optionally pre-run schema migrations on the empty file so system_config
    # table exists before pyturso bootstrap pulls remote data.
    if do_schema_migrations:
        try:
            _preinit_schema(db_path)
        except Exception as e:
            print(f"V007: Warning — pre-init schema failed (non-fatal): {e}")

    return backup_path


def _preinit_schema(db_path: str) -> None:
    """Create empty DB with schema tables + system_config so migration runner works.

    This runs BEFORE pyturso.connect(), using plain sqlite3. pyturso will later
    bootstrap from remote and the schema will be reconciled.
    """
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    # Create system_config table (migration version tracking)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS system_config ("
        "  key TEXT PRIMARY KEY,"
        "  value TEXT,"
        "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )

    # Create minimal schema tables so migration runner can apply V001-V006
    conn.execute(
        "CREATE TABLE IF NOT EXISTS processed_words ("
        "  voc_id TEXT PRIMARY KEY,"
        "  spell TEXT,"
        "  status INTEGER DEFAULT 0,"
        "  last_synced_content TEXT,"
        "  sync_status INTEGER DEFAULT 0,"
        "  match_confidence REAL,"
        "  match_reason TEXT,"
        "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_word_notes ("
        "  voc_id TEXT PRIMARY KEY,"
        "  interpretation TEXT,"
        "  tags TEXT,"
        "  is_customized INTEGER DEFAULT 0,"
        "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    conn.commit()

    # Run migration V001-V006 (schema DDL/DML, idempotent)
    from database.migrations.runner import apply_migrations
    start_v, end_v = apply_migrations(conn)
    print(f"V007: Pre-init schema v{start_v} → v{end_v}")
    conn.close()


def apply(cur: Any) -> None:
    """Run V007 migration. Called from migration runner on the connection cursor.

    Note: This is the legacy entry point. The primary migration path is now
    `pre_connect_migrate()` which runs BEFORE pyturso.connect().
    This fallback detects format via the cursor's database path and skips
    if already migrated.
    """
    db_path = None
    try:
        row = cur.execute("PRAGMA database_list").fetchone()
        if row:
            db_path = row[2]
    except Exception:
        pass

    if not db_path or not os.path.exists(db_path):
        return

    fmt = _detect_format(db_path)
    if fmt in ("turso_sync", "no_file"):
        return  # Already compatible or no file to migrate

    # Format is libsql_embedded_replica but we're inside an open connection.
    # The actual migration should have been done by pre_connect_migrate().
    # Log a warning — the file may have been migrated already or pyturso
    # may have already overwritten the sidecar.
    print(f"V007: Legacy apply() detected {fmt} format for {db_path} — "
          "migration should have been done pre-connect via pre_connect_migrate()")


def pre_connect_migrate(db_path: str) -> dict:
    """Migrate database format BEFORE pyturso.connect() opens the file.

    This is the primary entry point called from `_connect_turso_sync()`.

    Returns dict with migration results:
        {"action": "migrated"|"skipped"|"no_file", "backup": path|None, "format": str}
    """
    fmt = _detect_format(db_path)

    if fmt == "no_file":
        return {"action": "no_file", "backup": None, "format": fmt}

    if fmt == "turso_sync":
        return {"action": "skipped", "backup": None, "format": fmt}

    if fmt == "libsql_embedded_replica":
        print(f"V007: Detected libsql ER format, migrating to pyturso: {db_path}")
        backup = _migrate_libsql_to_turso(db_path)
        return {"action": "migrated", "backup": backup, "format": fmt}

    # unknown format: backup and let pyturso start fresh
    print(f"V007: Unknown format, backing up and recreating: {db_path}")
    backup_path = db_path + ".pre_pyturso.bak"
    try:
        shutil.copy2(db_path, backup_path)
    except Exception:
        backup_path = None
    try:
        os.remove(db_path)
    except OSError:
        pass
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(db_path + suffix)
        except OSError:
            pass
    return {"action": "migrated", "backup": backup_path, "format": fmt}
