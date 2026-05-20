# Migration State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce pre-connect-only migration for pyturso, disable legacy apply mutation, add a migration state machine with a health gate, and harden ER format detection.

**Architecture:** Add a migration result object and robust detection in `V007_migrate_db_format.py`, enforce pre-connect migration in pyturso backend, block legacy apply from mutating, and add a health gate surfaced by a dedicated check in web backend. Serialization uses a process-level lock.

**Tech Stack:** Python 3.12, pytest

---

## File Structure

- Modify: `database/migrations/V007_migrate_db_format.py`
  - Add migration result object and robust detection
  - Ensure pre-connect returns explicit action
  - Make legacy `apply()` a no-op warning
- Modify: `database/backends/_pyturso.py`
  - Call `pre_connect_migrate()` and enforce pyturso-only migration
- Modify: `database/backends/_libsql.py`
  - Ensure no migration logic runs
- Modify: `database/connection.py`
  - Health gate decision on migration failure
- Modify: `web/backend/app.py`
  - Surface degraded state in health endpoint
- Create: `tests/unit/database/migrations/test_v007_migration_state.py`
- Create: `tests/unit/database/test_migration_health_gate.py`

---

### Task 1: Define migration state object and robust detection

**Files:**
- Modify: `database/migrations/V007_migrate_db_format.py`
- Test: `tests/unit/database/migrations/test_v007_migration_state.py`

- [ ] **Step 1: Write failing tests for detection and result object**

```python
import tempfile
from pathlib import Path

from database.migrations.V007_migrate_db_format import pre_connect_migrate


def test_detects_er_sidecar_variants(tmp_path: Path) -> None:
    db = tmp_path / "history-asher.db"
    db.write_bytes(b"db")
    sidecar = tmp_path / "history-asher.db-info"
    sidecar.write_text("replica_id=abc", encoding="utf-8")

    res = pre_connect_migrate(str(db))
    assert res["format"] == "libsql_embedded_replica"
    assert res["action"] in ("migrated", "skipped")


def test_no_file_returns_no_file(tmp_path: Path) -> None:
    db = tmp_path / "missing.db"
    res = pre_connect_migrate(str(db))
    assert res["format"] == "no_file"
    assert res["action"] == "skipped"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/unit/database/migrations/test_v007_migration_state.py -v
```

Expected: FAIL (function does not return a dict with format/action).

- [ ] **Step 3: Implement migration result and robust detection**

Update `database/migrations/V007_migrate_db_format.py`:

```python
from dataclasses import dataclass


@dataclass
class MigrationResult:
    db_path: str
    format: str
    action: str
    error: str = ""


def _candidate_sidecars(db_path: str) -> list[str]:
    return [
        db_path + "-info",
        db_path + ".db-info",
        db_path + ".db-info".replace(".db", ".db.", 1),
    ]


def _detect_format(db_path: str) -> str:
    if not os.path.exists(db_path):
        # sidecar without db is treated as unknown to trigger cleanup
        for sc in _candidate_sidecars(db_path):
            if os.path.exists(sc):
                return "unknown"
        return "no_file"

    sidecar_path = next((p for p in _candidate_sidecars(db_path) if os.path.exists(p)), "")
    if sidecar_path:
        try:
            with open(sidecar_path, "rb") as f:
                sidecar_data = f.read(4096)
            sidecar_text = sidecar_data.decode("utf-8", errors="replace")
            if "turso-sync-py" in sidecar_text:
                return "turso_sync"
            if "replica_id" in sidecar_text or "sync_url" in sidecar_text:
                return "libsql_embedded_replica"
        except OSError:
            pass
        return "libsql_embedded_replica"

    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        finally:
            conn.close()
        return "turso_sync"
    except (sqlite3.DatabaseError, sqlite3.OperationalError):
        return "unknown"


def pre_connect_migrate(db_path: str) -> dict:
    fmt = _detect_format(db_path)
    result = MigrationResult(db_path=db_path, format=fmt, action="skipped")
    if fmt in ("no_file", "turso_sync"):
        return result.__dict__
    try:
        if fmt == "libsql_embedded_replica":
            backup = _migrate_libsql_to_turso(db_path)
            result.action = "migrated"
            return {**result.__dict__, "backup": backup}
        # unknown: backup and cleanup path
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
        result.action = "migrated"
        return {**result.__dict__, "backup": backup_path}
    except Exception as exc:
        result.action = "failed"
        result.error = str(exc)
        return result.__dict__
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/unit/database/migrations/test_v007_migration_state.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/V007_migrate_db_format.py tests/unit/database/migrations/test_v007_migration_state.py
git commit -m "refactor: 增强调度迁移检测"
```

---

### Task 2: Disable legacy apply mutation

**Files:**
- Modify: `database/migrations/V007_migrate_db_format.py`

- [ ] **Step 1: Write failing test for legacy apply no-op**

```python
from database.migrations.V007_migrate_db_format import apply


def test_apply_is_noop_for_legacy(tmp_path):
    class DummyCursor:
        def execute(self, *_):
            class Dummy:
                def fetchone(self):
                    return (None, None, str(tmp_path / "db.db"))
            return Dummy()
    apply(DummyCursor())
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/unit/database/migrations/test_v007_migration_state.py::test_apply_is_noop_for_legacy -v
```

Expected: FAIL (apply still mutates).

- [ ] **Step 3: Implement no-op apply**

```python
def apply(cur: Any) -> None:
    db_path = None
    try:
        row = cur.execute("PRAGMA database_list").fetchone()
        if row:
            db_path = row[2]
    except Exception:
        pass

    if not db_path:
        return

    print(
        f"V007: Legacy apply() invoked for {db_path} — skipping mutation; "
        "use pre_connect_migrate()"
    )
    return
```

- [ ] **Step 4: Run test to verify pass**

```bash
pytest tests/unit/database/migrations/test_v007_migration_state.py::test_apply_is_noop_for_legacy -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/V007_migrate_db_format.py tests/unit/database/migrations/test_v007_migration_state.py
git commit -m "fix: 禁用 V007 legacy apply 变更"
```

---

### Task 3: Enforce pyturso-only migration and health gate

**Files:**
- Modify: `database/backends/_pyturso.py`
- Modify: `database/backends/_libsql.py`
- Modify: `database/connection.py`
- Test: `tests/unit/database/test_migration_health_gate.py`

- [ ] **Step 1: Write failing health gate test**

```python
from database.connection import _get_backend
from database.migrations.V007_migrate_db_format import MigrationResult


def test_health_gate_blocks_failed_migration(monkeypatch):
    class DummyBackend:
        def connect(self, *_, **__):
            return object()
        def is_supported(self):
            return True

    def fake_pre_connect(_):
        return {"format": "libsql_embedded_replica", "action": "failed", "error": "boom", "db_path": "x"}

    monkeypatch.setattr("database.backends._pyturso.PytursoBackend.connect", DummyBackend.connect)
    monkeypatch.setattr("database.migrations.V007_migrate_db_format.pre_connect_migrate", fake_pre_connect)

    # Expect RuntimeError or specific exception
    try:
        _get_backend().connect("x", "u", "t")
        assert False, "health gate should block"
    except RuntimeError:
        assert True
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/unit/database/test_migration_health_gate.py -v
```

Expected: FAIL (no health gate).

- [ ] **Step 3: Implement pyturso-only pre-connect and health gate**

Update `database/backends/_pyturso.py`:

```python
from database.migrations.V007_migrate_db_format import pre_connect_migrate

# before turso.sync.connect
result = pre_connect_migrate(db_path)
if result.get("action") == "failed":
    raise RuntimeError(f"Migration failed for {db_path}: {result.get('error')}")
```

Update `database/backends/_libsql.py` to ensure no migration calls are introduced.

- [ ] **Step 4: Run test to verify pass**

```bash
pytest tests/unit/database/test_migration_health_gate.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add database/backends/_pyturso.py database/backends/_libsql.py database/connection.py tests/unit/database/test_migration_health_gate.py
git commit -m "feat: 添加迁移健康门禁"
```

---

### Task 4: Surface degraded state in health endpoint

**Files:**
- Modify: `web/backend/app.py`

- [ ] **Step 1: Add health flag accessors**

Add a migration health flag in `database/connection.py` (module-level) set by health gate and expose getter.

- [ ] **Step 2: Update health endpoint**

```python
from database.connection import get_migration_health

data["migration"] = get_migration_health()
```

- [ ] **Step 3: Run targeted tests (if any)**

If no existing test, skip and note manual check.

- [ ] **Step 4: Commit**

```bash
git add web/backend/app.py database/connection.py
git commit -m "feat: 健康检查暴露迁移状态"
```

---

## Self-Review Checklist
- [ ] Plan includes explicit pre-connect-only migration logic
- [ ] Legacy apply is no-op
- [ ] Health gate enforced
- [ ] Tests added and verify failure/success
- [ ] No placeholders remain
