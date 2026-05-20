# V007 Corruption Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix V007 migration corruption caused by `_preinit_schema()` creating conflicting local schema before pyturso bootstrap, and fix unreliable format detection when sidecar files are missing.

**Architecture:** Remove `_preinit_schema()` so pyturso bootstraps into a clean slate from remote. Fix `_detect_format()` to return "unknown" (not "turso_sync") when no sidecar exists. Add stale sidecar cleanup to `PytursoBackend.connect()` for parity with `LibsqlBackend`.

**Tech Stack:** Python 3.12, sqlite3, pytest, pyturso (turso.sync), libsql

---

## Files to Modify

| File | Change |
|------|--------|
| `database/migrations/V007_migrate_db_format.py` | Fix `_detect_format()`, remove `_preinit_schema()`, fix `pre_connect_migrate()`, clean up `apply()` |
| `database/backends/_pyturso.py` | Add `_cleanup_stale_sidecars()` call before V007 |
| `tests/unit/database/migrations/test_v007_format_detection.py` | New: unit tests for `_detect_format()` |
| `tests/unit/database/migrations/test_v007_pre_connect.py` | New: unit tests for `pre_connect_migrate()` |

---

### Task 1: Fix `_detect_format()` — no sidecar returns "unknown"

**Files:**
- Modify: `database/migrations/V007_migrate_db_format.py:24-67`
- Test: `tests/unit/database/migrations/test_v007_format_detection.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/database/migrations/test_v007_format_detection.py`:

```python
"""tests/unit/database/migrations/test_v007_format_detection.py: V007 format detection tests."""
from __future__ import annotations

import os
import sqlite3
import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Create a valid SQLite .db file at tmp_path/test.db."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()
    return db_path


class TestDetectFormat:
    def test_no_file_returns_no_file(self, tmp_path):
        from database.migrations.V007_migrate_db_format import _detect_format
        result = _detect_format(str(tmp_path / "nonexistent.db"))
        assert result == "no_file"

    def test_pyturso_sidecar_returns_turso_sync(self, tmp_db):
        from database.migrations.V007_migrate_db_format import _detect_format
        sidecar = tmp_db + "-info"
        with open(sidecar, "wb") as f:
            f.write(b'{"client_unique_id": "turso-sync-py-abc123"}')
        assert _detect_format(tmp_db) == "turso_sync"

    def test_libsql_sidecar_returns_libsql_embedded_replica(self, tmp_db):
        from database.migrations.V007_migrate_db_format import _detect_format
        sidecar = tmp_db + "-info"
        with open(sidecar, "wb") as f:
            f.write(b'{"replica_id": "abc", "sync_url": "libsql://..."}')
        assert _detect_format(tmp_db) == "libsql_embedded_replica"

    def test_valid_db_without_sidecar_returns_unknown(self, tmp_db):
        """KEY FIX: no sidecar → unknown, NOT turso_sync."""
        from database.migrations.V007_migrate_db_format import _detect_format
        assert _detect_format(tmp_db) == "unknown"

    def test_corrupt_db_without_sidecar_returns_unknown(self, tmp_path):
        from database.migrations.V007_migrate_db_format import _detect_format
        db_path = str(tmp_path / "corrupt.db")
        with open(db_path, "wb") as f:
            f.write(b"not a sqlite file at all")
        assert _detect_format(db_path) == "unknown"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/database/migrations/test_v007_format_detection.py -v --tb=short`
Expected: Some tests FAIL because current `_detect_format()` returns "turso_sync" for valid db without sidecar.

- [ ] **Step 3: Fix `_detect_format()` in V007_migrate_db_format.py**

Replace lines 24-67 with:

```python
def _detect_format(db_path: str) -> str:
    """Detect .db file format using sqlite3 + sidecar inspection.

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/database/migrations/test_v007_format_detection.py -v --tb=short`
Expected: All 5 tests PASS.

- [ ] **Step 5: Syntax check**

Run: `python -m py_compile database/migrations/V007_migrate_db_format.py`
Expected: No output (success).

---

### Task 2: Remove `_preinit_schema()` and fix `_migrate_libsql_to_turso()`

**Files:**
- Modify: `database/migrations/V007_migrate_db_format.py:70-154`

- [ ] **Step 1: Remove `_preinit_schema()` function**

Delete lines 104-153 (the entire `_preinit_schema` function).

- [ ] **Step 2: Simplify `_migrate_libsql_to_turso()`**

Replace lines 70-101 with:

```python
def _migrate_libsql_to_turso(db_path: str) -> str:
    """Backup old file + delete all libsql/pyturso files. Let pyturso bootstrap from remote.

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
```

- [ ] **Step 3: Verify no other code references `_preinit_schema`**

Run: `python -c "import database.migrations.V007_migrate_db_format; print('OK')"`
Expected: `OK` (no ImportError from removed function).

- [ ] **Step 4: Verify existing tests still pass**

Run: `python -m pytest tests/unit/database/migrations/ -v --tb=short`
Expected: All existing tests PASS. `_preinit_schema` was only called from within V007 itself.

---

### Task 3: Fix `pre_connect_migrate()` — "unknown" format goes to rebuild

**Files:**
- Modify: `database/migrations/V007_migrate_db_format.py:187-224`

- [ ] **Step 1: Write additional test for `pre_connect_migrate()`**

Add to `tests/unit/database/migrations/test_v007_format_detection.py`:

```python
class TestPreConnectMigrate:
    def test_no_file_returns_no_file_action(self, tmp_path):
        from database.migrations.V007_migrate_db_format import pre_connect_migrate
        result = pre_connect_migrate(str(tmp_path / "nonexistent.db"))
        assert result["action"] == "no_file"
        assert result["format"] == "no_file"

    def test_pyturso_db_returns_skipped(self, tmp_db):
        from database.migrations.V007_migrate_db_format import pre_connect_migrate
        sidecar = tmp_db + "-info"
        with open(sidecar, "wb") as f:
            f.write(b'{"client_unique_id": "turso-sync-py-abc"}')
        result = pre_connect_migrate(tmp_db)
        assert result["action"] == "skipped"
        assert result["format"] == "turso_sync"

    def test_libsql_db_gets_migrated(self, tmp_db):
        from database.migrations.V007_migrate_db_format import pre_connect_migrate
        sidecar = tmp_db + "-info"
        with open(sidecar, "wb") as f:
            f.write(b'{"replica_id": "abc"}')
        result = pre_connect_migrate(tmp_db)
        assert result["action"] == "migrated"
        assert result["format"] == "libsql_embedded_replica"
        # Original db should be deleted
        assert not os.path.exists(tmp_db)
        # Backup should exist
        assert result["backup"] is not None
        assert os.path.exists(result["backup"])

    def test_unknown_format_gets_migrated(self, tmp_db):
        """KEY FIX: unknown format (no sidecar) → backup + delete, NOT treated as turso_sync."""
        from database.migrations.V007_migrate_db_format import pre_connect_migrate
        result = pre_connect_migrate(tmp_db)
        assert result["action"] == "migrated"
        assert result["format"] == "unknown"
        assert not os.path.exists(tmp_db)
        assert result["backup"] is not None

    def test_no_preinit_schema_called(self, tmp_db, tmp_path):
        """Ensure _preinit_schema is NOT called — pyturso should bootstrap from remote."""
        from database.migrations.V007_migrate_db_format import pre_connect_migrate
        sidecar = tmp_db + "-info"
        with open(sidecar, "wb") as f:
            f.write(b'{"replica_id": "abc"}')
        result = pre_connect_migrate(tmp_db)
        # After migration, db file should be DELETED (not recreated with pre-init schema)
        assert not os.path.exists(tmp_db)
```

- [ ] **Step 2: Run tests to verify current failures**

Run: `python -m pytest tests/unit/database/migrations/test_v007_format_detection.py::TestPreConnectMigrate -v --tb=short`
Expected: Some FAIL (unknown format test, no_preinit_schema test).

- [ ] **Step 3: Fix `pre_connect_migrate()`**

Replace the function with:

```python
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

    # libsql_embedded_replica 或 unknown → 备份 + 删除，让 pyturso 从远端重新拉
    if fmt in ("libsql_embedded_replica", "unknown"):
        backup = _migrate_libsql_to_turso(db_path)
        return {"action": "migrated", "backup": backup, "format": fmt}

    return {"action": "skipped", "backup": None, "format": fmt}
```

- [ ] **Step 4: Run all V007 tests**

Run: `python -m pytest tests/unit/database/migrations/test_v007_format_detection.py -v --tb=short`
Expected: All tests PASS.

---

### Task 4: Clean up V007 `apply()` legacy entry point

**Files:**
- Modify: `database/migrations/V007_migrate_db_format.py:156-184`

- [ ] **Step 1: Simplify `apply()` to a clean no-op**

Replace lines 156-184 with:

```python
def apply(cur: Any) -> None:
    """V007 migration entry point (called by runner).

    V007 is a pre-connect format migration handled by `pre_connect_migrate()`.
    By the time the runner calls this, format migration is already done.
    This is a no-op.
    """
```

- [ ] **Step 2: Syntax check**

Run: `python -m py_compile database/migrations/V007_migrate_db_format.py`
Expected: No output (success).

- [ ] **Step 3: Verify runner still works**

Run: `python -m pytest tests/unit/database/migrations/test_runner.py -v --tb=short`
Expected: All existing runner tests PASS (target_version still returns 7, apply is no-op).

---

### Task 5: Add sidecar cleanup to `PytursoBackend.connect()`

**Files:**
- Modify: `database/backends/_pyturso.py:69-83`

- [ ] **Step 1: Add stale sidecar cleanup before V007**

In `PytursoBackend.connect()`, after line 69 (`os.makedirs(...)`) and before line 73 (V007 comment), insert:

```python
        # 清理残留 sidecar（.db 不存在时），防止 V007 格式检测误判
        if not os.path.exists(db_path):
            from database.utils import _cleanup_stale_sidecars
            _cleanup_stale_sidecars(os.path.abspath(db_path))
```

The full connect method should have this flow after the `os.makedirs` line:

```python
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        # 清理残留 sidecar（.db 不存在时），防止 V007 格式检测误判
        if not os.path.exists(db_path):
            from database.utils import _cleanup_stale_sidecars
            _cleanup_stale_sidecars(os.path.abspath(db_path))

        db_label = "Hub" if "hub" in os.path.basename(db_path).lower() else "主库"

        # ── Step 1: V007 format migration (before pyturso opens the file) ──
```

- [ ] **Step 2: Syntax check**

Run: `python -m py_compile database/backends/_pyturso.py`
Expected: No output (success).

- [ ] **Step 3: Verify no import cycle**

Run: `python -c "from database.backends._pyturso import PytursoBackend; print('OK')"`
Expected: `OK`

---

### Task 6: End-to-end regression verification

- [ ] **Step 1: Run full unit test suite**

Run: `python -m pytest tests/unit/ -v --tb=short -m "not slow"`
Expected: All tests PASS.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short -m "not slow"`
Expected: All tests PASS.

- [ ] **Step 3: Compile all modified files**

Run:
```bash
python -m py_compile database/migrations/V007_migrate_db_format.py
python -m py_compile database/backends/_pyturso.py
```
Expected: No output (success).

- [ ] **Step 4: Commit**

```bash
git add database/migrations/V007_migrate_db_format.py database/backends/_pyturso.py tests/unit/database/migrations/test_v007_format_detection.py
git commit -m "fix(v007): remove _preinit_schema corruption + fix format detection

- _detect_format(): no sidecar → 'unknown' instead of false 'turso_sync'
- Remove _preinit_schema() which created conflicting schema before pyturso bootstrap
- pre_connect_migrate(): 'unknown' format now triggers backup + rebuild
- PytursoBackend.connect(): add stale sidecar cleanup for parity with LibsqlBackend
- Clean up legacy apply() to no-op (pre-connect migration handles everything)

RC1: _preinit_schema created tables with 'spell' column while _create_tables uses
'spelling', causing schema mismatch when pyturso bootstrap pulled remote data.
RC2: valid SQLite without sidecar was falsely detected as turso_sync format.
RC3: PytursoBackend lacked sidecar cleanup, allowing stale files to cause false detection."
```

---

## Self-Review

**Spec coverage:**
- RC1 (_preinit_schema conflict) → Task 2 removes it ✓
- RC2 (unreliable format detection) → Task 1 fixes it ✓
- RC3 (missing sidecar cleanup) → Task 5 adds it ✓
- RC4 (schema inconsistency) → Task 2 removes _preinit_schema, eliminating inconsistency ✓
- Change 1 (_detect_format fix) → Task 1 ✓
- Change 2 (_migrate_libsql_to_turso fix) → Task 2 ✓
- Change 3 (pre_connect_migrate fix) → Task 3 ✓
- Change 4 (PytursoBackend cleanup) → Task 5 ✓
- Change 5 (delete _preinit_schema) → Task 2 ✓
- Change 6 (clean up apply()) → Task 4 ✓

**Placeholder scan:** No TBD/TODO/fill-in found. All code blocks are complete.

**Type consistency:** `_detect_format()` returns `str`, `_migrate_libsql_to_turso()` returns `str` (backup path), `pre_connect_migrate()` returns `dict` — all consistent with existing signatures.
