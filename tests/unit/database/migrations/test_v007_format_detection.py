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


@pytest.fixture
def tmp_app_db(tmp_path):
    """Create a valid SQLite .db with our application table."""
    db_path = str(tmp_path / "app.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE ai_word_notes (voc_id TEXT PRIMARY KEY, spelling TEXT)"
    )
    conn.execute("INSERT INTO ai_word_notes VALUES ('v1', 'hello')")
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

    def test_non_pyturso_sidecar_returns_unknown(self, tmp_db):
        from database.migrations.V007_migrate_db_format import _detect_format

        sidecar = tmp_db + "-info"
        with open(sidecar, "wb") as f:
            f.write(b'{"replica_id": "abc", "sync_url": "libsql://..."}')
        assert _detect_format(tmp_db) == "unknown"

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

    def test_libsql_db_gets_quarantined_as_unknown(self, tmp_path):
        from database.migrations.V007_migrate_db_format import pre_connect_migrate

        db_path = str(tmp_path / "libsql.db")
        conn = sqlite3.connect(db_path)
        conn.commit()
        conn.close()

        sidecar = db_path + "-info"
        with open(sidecar, "wb") as f:
            f.write(b'{"replica_id": "abc"}')
        result = pre_connect_migrate(db_path)
        assert result["action"] == "migrated"
        assert result["format"] == "unknown"
        assert not os.path.exists(db_path)
        assert result["backup"] is not None
        assert os.path.exists(result["backup"])

    def test_unknown_format_with_app_tables_is_preserved(self, tmp_app_db):
        """CRITICAL: unknown format + valid app data → PRESERVE, don't delete."""
        from database.migrations.V007_migrate_db_format import pre_connect_migrate

        result = pre_connect_migrate(tmp_app_db)
        assert result["action"] == "preserved"
        assert result["format"] == "unknown"
        # Database file MUST still exist
        assert os.path.exists(tmp_app_db)
        # Data must be intact
        conn = sqlite3.connect(tmp_app_db)
        row = conn.execute("SELECT spelling FROM ai_word_notes WHERE voc_id='v1'").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "hello"

    def test_unknown_format_with_empty_tables_is_preserved(self, tmp_path):
        """Unknown format + has tables but no data → still PRESERVE (structure exists)."""
        from database.migrations.V007_migrate_db_format import pre_connect_migrate

        db_path = str(tmp_path / "empty_app.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE ai_word_notes (voc_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        result = pre_connect_migrate(db_path)
        assert result["action"] == "preserved"
        assert os.path.exists(db_path)

    def test_unknown_format_empty_db_gets_migrated(self, tmp_path):
        """Unknown format + valid SQLite but no user tables → migrate (quarantine)."""
        from database.migrations.V007_migrate_db_format import pre_connect_migrate

        # Create a truly empty SQLite file (no user tables at all)
        db_path = str(tmp_path / "empty.db")
        conn = sqlite3.connect(db_path)
        conn.commit()
        conn.close()

        result = pre_connect_migrate(db_path)
        assert result["action"] == "migrated"
        assert result["format"] == "unknown"
        # Original file should be gone (renamed to quarantine)
        assert not os.path.exists(db_path)
        assert result["backup"] is not None
        assert os.path.exists(result["backup"])

    def test_unknown_format_corrupt_file_gets_migrated(self, tmp_path):
        """Unknown format + corrupt file → migrate (quarantine)."""
        from database.migrations.V007_migrate_db_format import pre_connect_migrate

        db_path = str(tmp_path / "corrupt.db")
        with open(db_path, "wb") as f:
            f.write(b"not sqlite at all")

        result = pre_connect_migrate(db_path)
        assert result["action"] == "migrated"
        assert result["format"] == "unknown"
        assert not os.path.exists(db_path)
        assert result["backup"] is not None

    def test_no_preinit_schema_called(self, tmp_path):
        """Ensure _preinit_schema is NOT called — pyturso should bootstrap from remote."""
        from database.migrations.V007_migrate_db_format import pre_connect_migrate

        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.commit()
        conn.close()

        sidecar = db_path + "-info"
        with open(sidecar, "wb") as f:
            f.write(b'{"replica_id": "abc"}')
        result = pre_connect_migrate(db_path)
        # After quarantine, db file should be DELETED (renamed)
        assert result["format"] == "unknown"
        assert not os.path.exists(db_path)
