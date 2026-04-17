#!/usr/bin/env python3
"""Bulk-migrate Turso database groups within an organization.

Default mode is dry-run. Use --apply to execute changes.

Turso does not expose a stable in-place "move database to another group" endpoint.
This script supports two migration modes using documented create+seed APIs:

- clone: create a new DB in target group seeded from source DB.
- replace: clone to temp DB, delete source DB, recreate source name in target group,
  then delete temp DB.

Usage examples:
  python scripts/migrate_turso_db_group.py --target-group 123
    python scripts/migrate_turso_db_group.py --source-group default --target-group 123 --apply
    python scripts/migrate_turso_db_group.py --source-group default --target-group 123 --mode replace --apply --yes
  python scripts/migrate_turso_db_group.py --org my-org --token-env TURSO_MGMT_TOKEN --target-group 123 --apply
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from requests import RequestException

API_BASE = os.getenv("TURSO_API_BASE", "https://api.turso.tech/v1").rstrip("/")


def _render_progress(current: int, total: int, label: str = "", width: int = 24) -> str:
    if total <= 0:
        return label or "[----------] 0/0"

    done = min(max(current, 0), total)
    filled = int(round(width * done / total))
    bar = "#" * filled + "-" * (width - filled)
    prefix = f"{label} " if label else ""
    return f"{prefix}[{bar}] {done}/{total}"


def _show_progress(current: int, total: int, label: str = "") -> None:
    line = _render_progress(current, total, label=label)
    end = "\r" if sys.stdout.isatty() else "\n"
    print(line, end=end, flush=True)


def _show_db_stage(db_name: str, stage: str, current: int, total: int) -> None:
    _show_progress(current, total, label=f"{db_name}: {stage}")


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _trace(message: str) -> None:
    print(f"[{_ts()}] {message}", file=sys.stderr, flush=True)


def _step_start(db_name: str, step: str) -> float:
    _trace(f"{db_name}: {step} ...")
    return time.monotonic()


def _step_done(db_name: str, step: str, started_at: float) -> None:
    elapsed = time.monotonic() - started_at
    _trace(f"{db_name}: {step} done in {elapsed:.1f}s")


def _remove_sqlite_artifacts(base_path: Path) -> None:
    for artifact in base_path.parent.glob(f"{base_path.name}*"):
        if artifact.is_file():
            try:
                artifact.unlink()
            except Exception:
                pass


def _copy_sqlite_artifacts(source_base: Path, target_base: Path) -> None:
    target_base.parent.mkdir(parents=True, exist_ok=True)
    _remove_sqlite_artifacts(target_base)
    for artifact in source_base.parent.glob(f"{source_base.name}*"):
        if artifact.is_file():
            destination = target_base.parent / artifact.name
            shutil.copy2(artifact, destination)


def _sync_snapshot_worker(
    local_db_path: str,
    sync_url: str,
    auth_token: str,
    timeout: int,
    result_queue: "multiprocessing.queues.Queue[Tuple[bool, str]]",
) -> None:
    conn = None
    try:
        import libsql  # type: ignore

        conn = libsql.connect(local_db_path, sync_url=sync_url, auth_token=auth_token, timeout=timeout)
        if hasattr(conn, "sync"):
            conn.sync()
        result_queue.put((True, ""))
    except Exception as exc:
        result_queue.put((False, str(exc)))
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


class _ProgressPulse:
    def __init__(self, label: str, interval: float = 2.0) -> None:
        self.label = label
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._start_time = 0.0

    def __enter__(self) -> "_ProgressPulse":
        self._start_time = time.monotonic()
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop_event.set()
        self._thread.join(timeout=self.interval + 1.0)

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval):
            elapsed = int(time.monotonic() - self._start_time)
            suffix = f"({elapsed}s)" if elapsed >= 0 else ""
            line = f"{self.label} [working] {suffix}".rstrip()
            print(line, file=sys.stderr, flush=True)


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ[key] = value


def _load_repo_env_files() -> None:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    for name in (".env", ".env.local"):
        _load_env_file(repo_root / name)


@dataclass
class DbInfo:
    name: str
    group: str
    hostname: str = ""


class TursoGroupMigrator:
    def __init__(
        self,
        org: str,
        token: str,
        timeout: int = 20,
        snapshot_timeout: int = 300,
        snapshot_stall_timeout: int = 60,
    ) -> None:
        self.org = org
        self.timeout = timeout
        self.snapshot_timeout = snapshot_timeout
        self.snapshot_stall_timeout = snapshot_stall_timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        try:
            _trace(f"HTTP {method} {url}")
            return self.session.request(method, url, timeout=self.timeout, **kwargs)
        except RequestException as exc:
            msg = str(exc)
            if "NameResolutionError" in msg or "getaddrinfo failed" in msg:
                raise RuntimeError(
                    "无法解析 Turso API 域名 api.turso.tech。"
                    " 这是本机 DNS / 网络问题，不是 token 或脚本参数问题。"
                    " 可先检查 DNS、代理、公司网络，或临时设置 TURSO_API_BASE 指向可用的 API 入口。"
                ) from exc
            raise RuntimeError(f"Turso API request failed: {method} {url} | {msg}") from exc

    def list_databases(self) -> List[DbInfo]:
        url = f"{API_BASE}/organizations/{self.org}/databases"
        started_at = time.monotonic()
        _trace(f"Listing databases for org '{self.org}'")
        resp = self._request("GET", url)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to list databases: HTTP {resp.status_code} {resp.text[:300]}"
            )

        payload = resp.json() if resp.text else {}
        raw_dbs = payload.get("databases", []) if isinstance(payload, dict) else []

        dbs: List[DbInfo] = []
        for item in raw_dbs:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("Name")
            if not name:
                continue
            group = item.get("group") or item.get("Group") or ""
            hostname = item.get("hostname") or item.get("Hostname") or ""
            dbs.append(DbInfo(name=str(name), group=str(group), hostname=str(hostname)))
        _trace(f"Listed {len(dbs)} databases in {time.monotonic() - started_at:.1f}s")
        return dbs

    def get_database(self, db_name: str) -> DbInfo:
        url = f"{API_BASE}/organizations/{self.org}/databases/{db_name}"
        resp = self._request("GET", url)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to fetch database {db_name}: HTTP {resp.status_code} {resp.text[:300]}"
            )
        payload = resp.json() if resp.text else {}
        db_obj = payload.get("database") if isinstance(payload, dict) else None
        if not isinstance(db_obj, dict):
            db_obj = payload if isinstance(payload, dict) else {}

        name = db_obj.get("name") or db_obj.get("Name") or db_name
        group = db_obj.get("group") or db_obj.get("Group") or ""
        hostname = db_obj.get("hostname") or db_obj.get("Hostname") or ""
        return DbInfo(name=str(name), group=str(group), hostname=str(hostname))

    def get_database_group(self, db_name: str) -> str:
        url = f"{API_BASE}/organizations/{self.org}/databases/{db_name}"
        resp = self._request("GET", url)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to fetch database {db_name}: HTTP {resp.status_code} {resp.text[:300]}"
            )
        payload = resp.json() if resp.text else {}

        # API may return {"database": {...}} or direct object
        if isinstance(payload, dict) and isinstance(payload.get("database"), dict):
            db_obj = payload["database"]
        elif isinstance(payload, dict):
            db_obj = payload
        else:
            db_obj = {}

        group = db_obj.get("group") or db_obj.get("Group") or ""
        return str(group)

    def try_update_group(self, db_name: str, target_group: str) -> Tuple[bool, str]:
        # Different deployments may expose different endpoints for group mutation.
        candidates: Iterable[Tuple[str, str, Dict[str, Any]]] = [
            ("PATCH", f"{API_BASE}/organizations/{self.org}/databases/{db_name}", {"group": target_group}),
            ("POST", f"{API_BASE}/organizations/{self.org}/databases/{db_name}", {"group": target_group}),
            ("POST", f"{API_BASE}/organizations/{self.org}/databases/{db_name}/group", {"group": target_group}),
            ("POST", f"{API_BASE}/organizations/{self.org}/databases/{db_name}/move", {"group": target_group}),
        ]

        attempts: List[str] = []
        for method, url, body in candidates:
            resp = self._request(method, url, data=json.dumps(body))
            attempts.append(f"{method} {url} -> {resp.status_code}")
            if resp.status_code in (200, 201, 204):
                return True, "; ".join(attempts)

        return False, "; ".join(attempts)

    def create_database(
        self,
        name: str,
        group: str,
        seed_db_name: Optional[str] = None,
        for_upload: bool = False,
    ) -> DbInfo:
        url = f"{API_BASE}/organizations/{self.org}/databases"
        payload: Dict[str, Any] = {"name": name, "group": group}
        if seed_db_name:
            payload["seed"] = {"type": "database", "name": seed_db_name}
        elif for_upload:
            payload["seed"] = {"type": "database_upload"}

        _trace(
            f"Creating database '{name}' in group '{group}'"
            + (f" seeded from '{seed_db_name}'" if seed_db_name else "")
        )
        resp = self._request("POST", url, data=json.dumps(payload))
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"create database failed: {name} HTTP {resp.status_code} {resp.text[:300]}"
            )

        data = resp.json() if resp.text else {}
        db_obj = data.get("database") if isinstance(data, dict) else None
        if not isinstance(db_obj, dict):
            db_obj = data if isinstance(data, dict) else {}

        db_name = db_obj.get("name") or db_obj.get("Name") or name
        db_group = db_obj.get("group") or db_obj.get("Group") or group
        db_hostname = db_obj.get("hostname") or db_obj.get("Hostname") or ""
        return DbInfo(name=str(db_name), group=str(db_group), hostname=str(db_hostname))

    def delete_database(self, name: str) -> None:
        url = f"{API_BASE}/organizations/{self.org}/databases/{name}"
        _trace(f"Deleting database '{name}'")
        resp = self._request("DELETE", url)
        if resp.status_code not in (200, 202, 204):
            raise RuntimeError(
                f"delete database failed: {name} HTTP {resp.status_code} {resp.text[:300]}"
            )

    def create_database_token(self, db_name: str) -> str:
        url = f"{API_BASE}/organizations/{self.org}/databases/{db_name}/auth/tokens"
        _trace(f"Creating database token for '{db_name}'")
        resp = self._request("POST", url, data=json.dumps({}))
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"create database token failed: {db_name} HTTP {resp.status_code} {resp.text[:300]}"
            )
        payload = resp.json() if resp.text else {}
        token = payload.get("jwt") or payload.get("token")
        if not token:
            raise RuntimeError(f"create database token returned empty token for {db_name}")
        return str(token)

    def upload_database_file(self, hostname: str, db_token: str, file_path: Path) -> None:
        if not hostname:
            raise RuntimeError("upload_database_file missing database hostname")
        if not file_path.exists():
            raise RuntimeError(f"local sqlite file not found: {file_path}")

        url = f"https://{hostname}/v1/upload"
        _trace(f"Uploading '{file_path}' to '{hostname}'")
        headers = {
            "Authorization": f"Bearer {db_token}",
            "Content-Length": str(file_path.stat().st_size),
        }
        with file_path.open("rb") as fh:
            resp = requests.post(url, headers=headers, data=fh, timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(
                f"upload failed: {file_path} -> {hostname} HTTP {resp.status_code} {resp.text[:300]}"
            )

    def download_database_snapshot(self, db_name: str, out_file: Path) -> Path:
        """Download remote database to a local sqlite file using Embedded Replica sync."""
        try:
            import libsql  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "local sqlite file missing and libsql is not available for auto-download"
            ) from exc

        db = self.get_database(db_name)
        if not db.hostname:
            raise RuntimeError(f"cannot download {db_name}: empty hostname")

        token = self.create_database_token(db_name)
        sync_url = (
            db.hostname
            if db.hostname.startswith(("libsql://", "https://", "wss://"))
            else f"libsql://{db.hostname}"
        )

        out_file.parent.mkdir(parents=True, exist_ok=True)
        _trace(f"{db_name}: snapshot target -> {out_file}")

        last_error: Optional[Exception] = None
        for attempt in range(1, 3):
            with tempfile.TemporaryDirectory(prefix=f"{db_name}-snapshot-") as temp_dir:
                staging_base = Path(temp_dir) / out_file.name
                _trace(f"{db_name}: staging attempt {attempt} -> {staging_base}")

                conn = None
                try:
                    print(f"{db_name}: downloading snapshot started", file=sys.stderr, flush=True)
                    sync_started = time.monotonic()
                    _trace(f"{db_name}: libsql.connect(...), then sync()")

                    ctx = multiprocessing.get_context("spawn")
                    result_queue = ctx.Queue()
                    worker = ctx.Process(
                        target=_sync_snapshot_worker,
                        args=(str(staging_base), sync_url, token, self.timeout, result_queue),
                    )
                    worker.start()

                    last_size_bytes = -1
                    last_progress_at = time.monotonic()
                    while worker.is_alive():
                        elapsed = int(time.monotonic() - sync_started)
                        size_bytes = staging_base.stat().st_size if staging_base.exists() else 0
                        if size_bytes != last_size_bytes:
                            last_size_bytes = size_bytes
                            last_progress_at = time.monotonic()
                        size_mb = size_bytes / (1024 * 1024)
                        _trace(f"{db_name}: syncing... {elapsed}s, local size={size_mb:.1f}MB")

                        if elapsed >= self.snapshot_timeout:
                            worker.terminate()
                            worker.join(timeout=3.0)
                            raise RuntimeError(
                                "snapshot sync timeout "
                                f"after {self.snapshot_timeout}s; "
                                "you can retry with larger --snapshot-timeout or provide a local .db file"
                            )

                        stalled_for = time.monotonic() - last_progress_at
                        if stalled_for >= self.snapshot_stall_timeout:
                            worker.terminate()
                            worker.join(timeout=3.0)
                            raise RuntimeError(
                                "snapshot sync stalled "
                                f"for {int(stalled_for)}s (size stays {size_mb:.1f}MB); "
                                "network/region latency or remote sync issues likely"
                            )

                        worker.join(timeout=2.0)

                    worker.join(timeout=1.0)
                    ok = False
                    err = ""
                    if not result_queue.empty():
                        ok, err = result_queue.get()
                    elif worker.exitcode == 0:
                        ok = True
                    else:
                        err = f"sync worker exited with code {worker.exitcode}"

                    if not ok:
                        raise RuntimeError(err or "unknown sync error")

                    _trace(f"{db_name}: sync() finished in {time.monotonic() - sync_started:.1f}s")
                except Exception as exc:
                    last_error = exc
                    message = str(exc)
                    _trace(f"{db_name}: staging attempt {attempt} failed: {message}")
                    if attempt < 2 and (
                        "invalid local state" in message.lower()
                        or "metadata file does not" in message.lower()
                    ):
                        _trace(f"{db_name}: retrying with a fresh staging directory")
                        continue
                    raise
                finally:
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass

                _copy_sqlite_artifacts(staging_base, out_file)
                if not out_file.exists() or out_file.stat().st_size == 0:
                    raise RuntimeError(f"downloaded snapshot is empty: {out_file}")
                return out_file

        if last_error is not None:
            raise RuntimeError(f"download snapshot failed: {last_error}") from last_error
        raise RuntimeError(f"download snapshot failed for {db_name}")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk migrate Turso DB group.")
    parser.add_argument("--org", default=os.getenv("TURSO_ORG_SLUG", ""), help="Turso org slug")
    parser.add_argument(
        "--token-env",
        default="TURSO_MGMT_TOKEN",
        help="Environment variable name that stores Turso management token",
    )
    parser.add_argument("--source-group", default="default", help="Source group name")
    parser.add_argument("--target-group", required=True, help="Target group name")
    parser.add_argument(
        "--mode",
        choices=["clone", "replace"],
        default="clone",
        help="Migration mode: clone creates new DBs only; replace recreates same DB names in target group.",
    )
    parser.add_argument("--apply", action="store_true", help="Execute changes (default is dry-run)")
    parser.add_argument("--yes", action="store_true", help="Confirm destructive actions in replace mode")
    parser.add_argument(
        "--local-data-dir",
        default="",
        help="Directory containing local sqlite files for upload fallback (default: <repo>/data)",
    )
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds")
    parser.add_argument(
        "--snapshot-timeout",
        type=int,
        default=300,
        help="Max seconds allowed for one snapshot sync attempt",
    )
    parser.add_argument(
        "--snapshot-stall-timeout",
        type=int,
        default=60,
        help="Fail snapshot sync if local file size has no change for this many seconds",
    )
    return parser.parse_args(argv)


def _resolve_local_db_file(data_dir: Path, db_name: str) -> Optional[Path]:
    candidates = [
        data_dir / f"{db_name}.db",
        data_dir / f"{db_name}.sqlite",
    ]

    # Historical special case for hub database naming.
    if db_name == "momo-users-hub":
        candidates.insert(0, data_dir / "momo-users-hub.db")

    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


def _is_cross_group_seed_error(message: str) -> bool:
    m = message.lower()
    return "can only seed a database from others within the same group" in m


def main(argv: Optional[List[str]] = None) -> int:
    _load_repo_env_files()
    args = parse_args(argv)
    run_started = time.monotonic()
    _trace("Starting migration script")

    if not args.org:
        print("ERROR: missing org slug. Set TURSO_ORG_SLUG or pass --org.")
        return 2

    token = os.getenv(args.token_env, "").strip()
    if not token:
        print(
            "ERROR: missing management token. "
            f"Set {args.token_env} in environment, then retry."
        )
        return 2

    if args.source_group == args.target_group:
        print("No-op: source-group equals target-group.")
        return 0

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    data_dir = Path(args.local_data_dir).resolve() if args.local_data_dir else (repo_root / "data")

    if args.mode == "replace" and args.apply and not args.yes:
        print("ERROR: replace mode is destructive. Re-run with --yes to confirm.")
        return 2

    migrator = TursoGroupMigrator(
        org=args.org,
        token=token,
        timeout=args.timeout,
        snapshot_timeout=args.snapshot_timeout,
        snapshot_stall_timeout=args.snapshot_stall_timeout,
    )

    try:
        dbs = migrator.list_databases()
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    candidates = [db for db in dbs if db.group == args.source_group]
    print(
        f"Found {len(dbs)} databases in org '{args.org}'. "
        f"{len(candidates)} in source group '{args.source_group}'."
    )

    if not candidates:
        return 0

    for db in candidates:
        print(f"  - {db.name} ({db.group})")

    if not args.apply:
        print(f"\nDry-run only. mode={args.mode}. Re-run with --apply to execute migration.")
        return 0

    success = 0
    failed = 0
    total = len(candidates)

    for index, db in enumerate(candidates, start=1):
        db_started = time.monotonic()
        _trace(f"[{index}/{total}] begin '{db.name}' in group '{db.group}'")
        _show_db_stage(db.name, "checking", index - 1, total)
        ok, details = migrator.try_update_group(db.name, args.target_group)
        if ok:
            try:
                _show_db_stage(db.name, "verifying in-place move", index - 1, total)
                current_group = migrator.get_database_group(db.name)
            except Exception as exc:
                failed += 1
                print(f"[FAIL] {db.name} verify failed: {exc}")
                continue

            if current_group == args.target_group:
                success += 1
                print(f"[OK] {db.name}: {args.source_group} -> {current_group} (in-place)")
                continue

        # Fall back to create+seed strategy.
        try:
            if args.mode == "clone":
                clone_name = f"{db.name}-grp-{args.target_group}"
                try:
                    _show_db_stage(db.name, "creating clone", index - 1, total)
                    migrator.create_database(clone_name, args.target_group, seed_db_name=db.name)
                except Exception as seed_exc:
                    if not _is_cross_group_seed_error(str(seed_exc)):
                        raise
                    _show_db_stage(db.name, "resolving source copy", index - 1, total)
                    local_file = _resolve_local_db_file(data_dir, db.name)
                    if not local_file:
                        tmp_dir = Path(tempfile.gettempdir()) / "momo_turso_group_migration"
                        local_file = tmp_dir / f"{db.name}.db"
                        _show_db_stage(db.name, "downloading snapshot", index - 1, total)
                        local_file = migrator.download_database_snapshot(db.name, local_file)
                        print(f"[INFO] downloaded snapshot for {db.name} -> {local_file}")
                    else:
                        _trace(f"{db.name}: using existing local file '{local_file}'")
                    _show_db_stage(db.name, "uploading snapshot", index - 1, total)
                    new_db = migrator.create_database(clone_name, args.target_group, for_upload=True)
                    db_token = migrator.create_database_token(clone_name)
                    migrator.upload_database_file(new_db.hostname, db_token, local_file)

                _show_db_stage(db.name, "verifying clone", index - 1, total)
                current_group = migrator.get_database_group(clone_name)
                if current_group != args.target_group:
                    raise RuntimeError(
                        f"clone created but group is '{current_group}', expected '{args.target_group}'"
                    )
                success += 1
                print(
                    f"[OK] {db.name} cloned to {clone_name} in group {args.target_group} "
                    f"(in-place move unavailable: {details})"
                )
            else:
                temp_name = f"{db.name}-migrating-{args.target_group}"
                try:
                    _show_db_stage(db.name, "creating temp database", index - 1, total)
                    migrator.create_database(temp_name, args.target_group, seed_db_name=db.name)
                except Exception as seed_exc:
                    if not _is_cross_group_seed_error(str(seed_exc)):
                        raise
                    _show_db_stage(db.name, "resolving source copy", index - 1, total)
                    local_file = _resolve_local_db_file(data_dir, db.name)
                    if not local_file:
                        tmp_dir = Path(tempfile.gettempdir()) / "momo_turso_group_migration"
                        local_file = tmp_dir / f"{db.name}.db"
                        _show_db_stage(db.name, "downloading snapshot", index - 1, total)
                        local_file = migrator.download_database_snapshot(db.name, local_file)
                        print(f"[INFO] downloaded snapshot for {db.name} -> {local_file}")
                    else:
                        _trace(f"{db.name}: using existing local file '{local_file}'")
                    _show_db_stage(db.name, "uploading snapshot", index - 1, total)
                    temp_db = migrator.create_database(temp_name, args.target_group, for_upload=True)
                    temp_token = migrator.create_database_token(temp_name)
                    migrator.upload_database_file(temp_db.hostname, temp_token, local_file)

                _show_db_stage(db.name, "deleting original", index - 1, total)
                migrator.delete_database(db.name)
                _show_db_stage(db.name, "recreating original", index - 1, total)
                migrator.create_database(db.name, args.target_group, seed_db_name=temp_name)
                _show_db_stage(db.name, "cleaning temp", index - 1, total)
                migrator.delete_database(temp_name)

                _show_db_stage(db.name, "verifying replace", index - 1, total)
                current_group = migrator.get_database_group(db.name)
                if current_group != args.target_group:
                    raise RuntimeError(
                        f"replace finished but group is '{current_group}', expected '{args.target_group}'"
                    )
                success += 1
                print(
                    f"[OK] {db.name}: replaced into group {args.target_group} "
                    f"(via clone+recreate, in-place move unavailable: {details})"
                )
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {db.name} migration failed: {exc} | in-place attempts: {details}")

        _show_db_stage(db.name, "done", index, total)
        _trace(f"[{index}/{total}] '{db.name}' finished in {time.monotonic() - db_started:.1f}s")

    if total > 0:
        print()
    _trace(f"Run finished in {time.monotonic() - run_started:.1f}s")
    print(f"\nDone. success={success}, failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
