# Pyturso Pull Inspection Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone script that uses `turso.sync` to pull `history-asher.db` and report local file artifacts created by pyturso.

**Architecture:** A small CLI script in `scripts/` that connects via pyturso, pulls + checkpoints, and prints a before/after artifact inventory. A minimal unit test covers local artifact listing logic without requiring network access.

**Tech Stack:** Python 3.12, pyturso (`turso.sync`), pytest

---

### Task 1: Add CLI script for pyturso pull inspection

**Files:**
- Create: `scripts/inspect_pyturso_pull.py`

- [ ] **Step 1: Write failing unit test for artifact listing helper**

Create `tests/unit/scripts/test_inspect_pyturso_pull.py` with a test that expects deterministic artifact listing for a temp directory.

```python
from pathlib import Path
from scripts.inspect_pyturso_pull import list_local_artifacts


def test_list_local_artifacts(tmp_path: Path) -> None:
    db = tmp_path / "history-asher.db"
    (tmp_path / "history-asher.db").write_bytes(b"db")
    (tmp_path / "history-asher.db-info").write_text("info", encoding="utf-8")
    (tmp_path / "history-asher.db-wal").write_bytes(b"wal")
    (tmp_path / "history-asher.db-shm").write_bytes(b"shm")

    artifacts = list_local_artifacts(db)
    names = [a["name"] for a in artifacts]

    assert names == [
        "history-asher.db",
        "history-asher.db-info",
        "history-asher.db-shm",
        "history-asher.db-wal",
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/unit/scripts/test_inspect_pyturso_pull.py -v
```

Expected: FAIL because `scripts.inspect_pyturso_pull` does not exist yet.

- [ ] **Step 3: Implement the script with artifact listing helper**

Create `scripts/inspect_pyturso_pull.py`:

```python
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import turso.sync


def list_local_artifacts(db_path: Path) -> list[dict[str, Any]]:
    base = db_path.name
    items: list[dict[str, Any]] = []
    for candidate in sorted(db_path.parent.glob(base + "*")):
        if candidate.is_file():
            stat = candidate.stat()
            items.append(
                {
                    "name": candidate.name,
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                }
            )
    return items


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect pyturso pull artifacts")
    parser.add_argument("--db-path", default="data/history-asher.db")
    parser.add_argument("--url", default="", help="Overrides TURSO_DB_URL")
    parser.add_argument("--token", default="", help="Overrides TURSO_AUTH_TOKEN")
    parser.add_argument("--no-pull", action="store_true", help="Connect only, skip pull/checkpoint")
    args = parser.parse_args()

    db_path = Path(args.db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    url = args.url.strip() or _require_env("TURSO_DB_URL")
    token = args.token.strip() or _require_env("TURSO_AUTH_TOKEN")

    before = list_local_artifacts(db_path)

    conn = turso.sync.connect(
        path=str(db_path),
        remote_url=url,
        remote_auth_token=token,
    )

    if not args.no_pull:
        conn.pull()
        conn.checkpoint()

    after = list_local_artifacts(db_path)

    print(
        json.dumps(
            {
                "db_path": str(db_path),
                "before": before,
                "after": after,
                "pulled": not args.no_pull,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
pytest tests/unit/scripts/test_inspect_pyturso_pull.py -v
```

Expected: PASS.

- [ ] **Step 5: Ensure pyturso dependency is present**

Check `requirements.txt` and ensure `pyturso` is listed. If missing, add this line:

```text
pyturso
```

- [ ] **Step 6: Commit**

```bash
git add scripts/inspect_pyturso_pull.py tests/unit/scripts/test_inspect_pyturso_pull.py requirements.txt
git commit -m "feat: 添加 pyturso 拉取检查脚本"
```

### Task 2: Add minimal usage doc

**Files:**
- Create: `docs/dev/inspect_pyturso_pull.md`

- [ ] **Step 1: Add usage documentation**

```md
# Inspect Pyturso Pull

This script connects with `turso.sync`, runs `pull()` and `checkpoint()`, and prints local artifact files.

## Usage

```bash
$env:TURSO_DB_URL = "libsql://..."
$env:TURSO_AUTH_TOKEN = "..."
python scripts/inspect_pyturso_pull.py --db-path data/history-asher.db
```

## Options
- `--no-pull` to connect without pulling
- `--url` / `--token` to override environment variables
```

- [ ] **Step 2: Commit**

```bash
git add docs/dev/inspect_pyturso_pull.md
git commit -m "docs: 添加 pyturso 拉取检查脚本说明"
```

---

## Self-Review Checklist
- [ ] The plan includes a test-first workflow and validates failure before implementation.
- [ ] All file paths and commands are explicit and ready to run.
- [ ] No placeholders or vague steps.
- [ ] The script does not require network access for tests.
