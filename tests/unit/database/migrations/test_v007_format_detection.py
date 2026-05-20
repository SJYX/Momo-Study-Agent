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
        assert not os.path.exists(tmp_db)
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

    def test_no_preinit_schema_called(self, tmp_db):
        """Ensure _preinit_schema is NOT called — pyturso should bootstrap from remote."""
        from database.migrations.V007_migrate_db_format import pre_connect_migrate

        sidecar = tmp_db + "-info"
        with open(sidecar, "wb") as f:
            f.write(b'{"replica_id": "abc"}')
        result = pre_connect_migrate(tmp_db)
        # After migration, db file should be DELETED (not recreated with pre-init schema)
        assert not os.path.exists(tmp_db)
