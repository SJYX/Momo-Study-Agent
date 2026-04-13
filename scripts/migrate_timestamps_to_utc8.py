#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-time timestamp migration script.

Goal:
- Convert common timestamp columns in local SQLite databases under data/ to ISO8601 UTC+8.
- Handles formats like:
  - 2026-04-11T14:15:04.814477+00:00
  - 2026-04-11T14:15:04Z
  - 2026-04-11 14:15:04

Usage:
  python scripts/migrate_timestamps_to_utc8.py --apply
  python scripts/migrate_timestamps_to_utc8.py --apply --no-backup
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

UTC_PLUS_8 = timezone(timedelta(hours=8))

CANDIDATE_TS_COLUMNS = {
    "created_at",
    "updated_at",
    "processed_at",
    "login_at",
    "logout_at",
    "last_activity_at",
    "timestamp",
    "run_at",
    "first_login_at",
    "last_login_at",
    "revoked_at",
    "last_failed_at",
    "last_password_change",
}


def parse_any_timestamp(raw: str) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        pass

    if dt is None:
        # Common sqlite format: "YYYY-MM-DD HH:MM:SS"
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    # Naive timestamps are treated as UTC historical values for consistency.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(UTC_PLUS_8)


def find_db_files(data_dir: Path) -> list[Path]:
    dbs = []
    for p in data_dir.rglob("*.db"):
        # skip backup-like names that are not active db files
        if p.name.endswith(".db"):
            dbs.append(p)
    return sorted(set(dbs))


def migrate_one_db(db_path: Path, apply: bool) -> tuple[int, int]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]

    scanned = 0
    changed = 0

    for table in tables:
        try:
            cur.execute(f"PRAGMA table_info({table})")
            cols = [row[1] for row in cur.fetchall()]
        except Exception:
            continue

        ts_cols = [c for c in cols if c in CANDIDATE_TS_COLUMNS]
        if not ts_cols:
            continue

        select_cols = ", ".join(["rowid"] + ts_cols)
        try:
            cur.execute(f"SELECT {select_cols} FROM {table}")
            rows = cur.fetchall()
        except Exception:
            continue

        for row in rows:
            rowid = row[0]
            updates = {}
            for idx, c in enumerate(ts_cols, start=1):
                scanned += 1
                old_val = row[idx]
                dt = parse_any_timestamp(old_val)
                if dt is None:
                    continue
                new_val = dt.isoformat()
                if str(old_val) != new_val:
                    updates[c] = new_val

            if updates:
                changed += len(updates)
                if apply:
                    set_clause = ", ".join([f"{k} = ?" for k in updates])
                    args = list(updates.values()) + [rowid]
                    cur.execute(f"UPDATE {table} SET {set_clause} WHERE rowid = ?", args)

    if apply:
        conn.commit()
    conn.close()
    return scanned, changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate local DB timestamps to UTC+8 ISO8601")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Without this flag, runs in dry-run mode.")
    parser.add_argument("--no-backup", action="store_true", help="Do not create .bak backup files before migration.")
    parser.add_argument("--data-dir", default="data", help="Data directory to scan for .db files")
    args = parser.parse_args()

    root = Path(args.data_dir).resolve()
    db_files = find_db_files(root)

    if not db_files:
        print(f"No .db files found under: {root}")
        return

    print(f"Found {len(db_files)} database(s) under {root}")

    total_scanned = 0
    total_changed = 0

    for db in db_files:
        if args.apply and not args.no_backup:
            backup_path = db.with_suffix(db.suffix + ".bak")
            if not backup_path.exists():
                shutil.copy2(db, backup_path)

        scanned, changed = migrate_one_db(db, apply=args.apply)
        total_scanned += scanned
        total_changed += changed
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"[{mode}] {db}: scanned={scanned}, changed={changed}")

    print(f"Done. scanned={total_scanned}, changed={total_changed}, apply={args.apply}")


if __name__ == "__main__":
    main()
