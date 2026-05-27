"""Tests for _has_corrupt_sidecar_generation in database.backends._pyturso."""
import json
import os
import tempfile

import pytest

from database.backends._pyturso import _has_corrupt_sidecar_generation, _CORRUPT_GENERATION_THRESHOLD


@pytest.fixture
def tmp_db(tmp_path):
    """Return a temporary db path."""
    return str(tmp_path / "test.db")


def _write_sidecar(db_path, generation, wal_fragment=0):
    """Write a .db-info sidecar with the given generation."""
    info = {
        "version": "v1",
        "synced_revision": {
            "type": "v1",
            "revision": json.dumps({"generation": generation, "wal_fragment_no": wal_fragment}),
        },
    }
    with open(db_path + "-info", "w", encoding="utf-8") as f:
        json.dump(info, f)


def test_no_sidecar_returns_false(tmp_db):
    assert _has_corrupt_sidecar_generation(tmp_db) is False


def test_normal_generation_returns_false(tmp_db):
    _write_sidecar(tmp_db, generation=42)
    assert _has_corrupt_sidecar_generation(tmp_db) is False


def test_large_generation_returns_false(tmp_db):
    _write_sidecar(tmp_db, generation=999999)
    assert _has_corrupt_sidecar_generation(tmp_db) is False


def test_sentinel_generation_returns_true(tmp_db):
    _write_sidecar(tmp_db, generation=999999999999999928)
    assert _has_corrupt_sidecar_generation(tmp_db) is True


def test_another_sentinel_returns_true(tmp_db):
    _write_sidecar(tmp_db, generation=999999999999999996)
    assert _has_corrupt_sidecar_generation(tmp_db) is True


def test_threshold_boundary(tmp_db):
    _write_sidecar(tmp_db, generation=_CORRUPT_GENERATION_THRESHOLD - 1)
    assert _has_corrupt_sidecar_generation(tmp_db) is False

    _write_sidecar(tmp_db, generation=_CORRUPT_GENERATION_THRESHOLD + 1)
    assert _has_corrupt_sidecar_generation(tmp_db) is True


def test_corrupt_json_returns_false(tmp_db):
    """Corrupt sidecar file should not crash, just return False."""
    with open(tmp_db + "-info", "w") as f:
        f.write("not valid json{{{")
    assert _has_corrupt_sidecar_generation(tmp_db) is False
