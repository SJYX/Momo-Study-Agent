#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Turso cloud DB migration helper.

Purpose:
1. Ensure target database exists (create if needed)
2. Pull source cloud DB data into local cache via sync_databases
3. Push local cache data to target cloud DB via sync_databases
4. Update profile env to point to target DB

Example:
    python scripts/migrate_turso_cloud_db.py --user Asher --source-db momo-study --target-db history-asher
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = BASE_DIR / "data" / "profiles"
GLOBAL_ENV_PATH = BASE_DIR / ".env"


def _read_env_file(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def _set_or_add_env_key(path: Path, key: str, value: str) -> None:
    lines = []
    found = False
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[i] = f"{key}={value}"
            found = True

    if not found:
        lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _normalize_turso_url(hostname_or_url: str) -> str:
    raw = (hostname_or_url or "").strip()
    if not raw:
        return ""
    if raw.startswith("libsql://"):
        return raw
    if "://" in raw:
        # Keep host part only
        host = raw.split("://", 1)[1].split("/", 1)[0]
        return f"libsql://{host}"
    return f"libsql://{raw}"


def _turso_headers(mgmt_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {mgmt_token}",
        "Content-Type": "application/json",
    }


def _list_databases(org_slug: str, mgmt_token: str) -> Dict[str, dict]:
    url = f"https://api.turso.tech/v1/organizations/{org_slug}/databases"
    resp = requests.get(url, headers=_turso_headers(mgmt_token), timeout=20)
    resp.raise_for_status()
    dbs = resp.json().get("databases", [])

    by_name: Dict[str, dict] = {}
    for db in dbs:
        name = (db.get("name") or db.get("Name") or "").strip()
        if name:
            by_name[name] = db
    return by_name


def _create_database(org_slug: str, mgmt_token: str, db_name: str, group: str) -> dict:
    url = f"https://api.turso.tech/v1/organizations/{org_slug}/databases"
    payload = {"name": db_name, "group": group}
    resp = requests.post(url, headers=_turso_headers(mgmt_token), json=payload, timeout=20)
    if resp.status_code in (200, 201):
        return resp.json().get("database", {})
    if resp.status_code == 409:
        dbs = _list_databases(org_slug, mgmt_token)
        return dbs.get(db_name, {})
    raise RuntimeError(f"Create database failed: {resp.status_code} {resp.text}")


def _create_db_token(org_slug: str, mgmt_token: str, db_name: str) -> str:
    url = f"https://api.turso.tech/v1/organizations/{org_slug}/databases/{db_name}/auth/tokens"
    resp = requests.post(url, headers=_turso_headers(mgmt_token), json={}, timeout=20)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Create db token failed for {db_name}: {resp.status_code} {resp.text}")
    payload = resp.json()
    token = (payload.get("jwt") or payload.get("token") or "").strip()
    if not token:
        raise RuntimeError(f"Create db token returned empty token for {db_name}")
    return token


def _build_hostname(db: dict, db_name: str, org_slug: str) -> str:
    return (
        (db.get("hostname") or db.get("Hostname") or "").strip()
        or f"{db_name}-{org_slug}.aws-us-east-1.turso.io"
    )


def _run_sync_with_current_profile(user: str, phase_label: str) -> Dict[str, object]:
    env = os.environ.copy()
    env["MOMO_USER"] = user
    cmd = [
        sys.executable,
        "-c",
        "from database.momo_words import sync_databases; import json; print(json.dumps(sync_databases(dry_run=False), ensure_ascii=False))",
    ]
    result = subprocess.run(cmd, cwd=str(BASE_DIR), env=env, capture_output=True, text=True)

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    # Try parse last json object from stdout
    parsed: Dict[str, object] = {}
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    if result.returncode != 0:
        raise RuntimeError(
            f"{phase_label} failed (rc={result.returncode}). stdout={stdout[-600:]}; stderr={stderr[-600:]}"
        )

    if not parsed:
        raise RuntimeError(f"{phase_label} did not return sync stats. stdout={stdout[-600:]}")

    status = str(parsed.get("status", "ok"))
    if status != "ok":
        reason = parsed.get("reason", "")
        raise RuntimeError(f"{phase_label} returned status={status}, reason={reason}")

    return parsed


def _update_profile_cloud_config(profile_path: Path, db_name: str, hostname: str, db_url: str, token: str) -> None:
    _set_or_add_env_key(profile_path, "TURSO_DB_NAME", db_name)
    _set_or_add_env_key(profile_path, "TURSO_DB_HOSTNAME", hostname)
    _set_or_add_env_key(profile_path, "TURSO_DB_URL", db_url)
    _set_or_add_env_key(profile_path, "TURSO_AUTH_TOKEN", token)


def migrate(user: str, source_db: str, target_db: str, group: str, keep_backup: bool) -> None:
    profile_path = PROFILES_DIR / f"{user}.env"
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    cfg = _read_env_file(GLOBAL_ENV_PATH)
    org_slug = (cfg.get("TURSO_ORG_SLUG") or "").strip()
    mgmt_token = (cfg.get("TURSO_MGMT_TOKEN") or "").strip()
    if not org_slug or not mgmt_token:
        raise RuntimeError("Missing TURSO_ORG_SLUG or TURSO_MGMT_TOKEN in .env")

    print(f"[1/6] Listing databases in org={org_slug} ...")
    dbs = _list_databases(org_slug, mgmt_token)

    if source_db not in dbs:
        raise RuntimeError(f"Source db not found in Turso org: {source_db}")

    print(f"[2/6] Ensuring target db exists: {target_db}")
    if target_db in dbs:
        target_meta = dbs[target_db]
    else:
        target_meta = _create_database(org_slug, mgmt_token, target_db, group)

    source_meta = dbs[source_db]

    source_host = _build_hostname(source_meta, source_db, org_slug)
    target_host = _build_hostname(target_meta, target_db, org_slug)
    source_url = _normalize_turso_url(source_host)
    target_url = _normalize_turso_url(target_host)

    print("[3/6] Creating short-lived auth tokens ...")
    source_token = _create_db_token(org_slug, mgmt_token, source_db)
    target_token = _create_db_token(org_slug, mgmt_token, target_db)

    backup_path = profile_path.with_suffix(profile_path.suffix + f".mig-{int(time.time())}.bak")
    shutil.copy2(profile_path, backup_path)
    print(f"[4/6] Profile backup created: {backup_path}")

    try:
        print(f"[5/6] Pull source cloud -> local ({source_db})")
        _update_profile_cloud_config(profile_path, source_db, source_host, source_url, source_token)
        old_stats = _run_sync_with_current_profile(user, "source->local sync")
        print(f"    source stats: {old_stats}")

        print(f"[6/6] Push local -> target cloud ({target_db})")
        _update_profile_cloud_config(profile_path, target_db, target_host, target_url, target_token)
        new_stats = _run_sync_with_current_profile(user, "local->target sync")
        print(f"    target stats: {new_stats}")

        print("Migration finished. Profile now points to target db.")
    except Exception:
        # rollback profile for safety
        shutil.copy2(backup_path, profile_path)
        print("Migration failed. Profile restored from backup.")
        raise
    finally:
        if not keep_backup:
            try:
                backup_path.unlink(missing_ok=True)
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Turso cloud DB to a standardized database name.")
    parser.add_argument("--user", required=True, help="Profile username, e.g. Asher")
    parser.add_argument("--source-db", required=True, help="Existing source database name, e.g. momo-study")
    parser.add_argument("--target-db", required=True, help="Target standardized db name, e.g. history-asher")
    parser.add_argument("--group", default="default", help="Turso DB group when creating target")
    parser.add_argument("--keep-backup", action="store_true", help="Keep profile backup file after success")
    args = parser.parse_args()

    migrate(
        user=args.user,
        source_db=args.source_db,
        target_db=args.target_db,
        group=args.group,
        keep_backup=args.keep_backup,
    )


if __name__ == "__main__":
    main()
