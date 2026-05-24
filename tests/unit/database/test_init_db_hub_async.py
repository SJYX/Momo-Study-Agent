"""tests/unit/database/test_init_db_hub_async.py: verify Hub init is off the
SyncGate critical path.

init_db must return without waiting for init_users_hub_tables() to complete.
Hub is independent of main-DB schema state; the only consumer of Hub
(/api/users/*) is exempt from the readiness gate, so a slow Hub connect
must not delay SyncGate dismissal.
"""
from __future__ import annotations

import threading
import time

import pytest


@pytest.mark.unit
def test_init_db_does_not_block_on_hub_init(tmp_path, monkeypatch):
    """init_db returns fast even when init_users_hub_tables is slow."""
    # Force local-only path so we skip the cloud connect (which has its own
    # network cost we don't want polluting this timing test).
    monkeypatch.delenv("TURSO_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TURSO_DB_HOSTNAME", raising=False)

    import database.schema

    hub_started = threading.Event()
    hub_finished = threading.Event()

    def slow_hub() -> bool:
        hub_started.set()
        time.sleep(2.0)
        hub_finished.set()
        return True

    monkeypatch.setattr(database.schema, "init_users_hub_tables", slow_hub)

    db_path = str(tmp_path / "test.db")

    started_at = time.time()
    database.schema.init_db(db_path)
    elapsed = time.time() - started_at

    # init_db must return well before slow_hub's 2s sleep finishes
    assert elapsed < 1.0, (
        f"init_db took {elapsed:.2f}s, expected fast return — "
        "is Hub init still synchronous on the critical path?"
    )
    # Hub init must have been kicked off (thread started)
    assert hub_started.wait(timeout=2.0), "Hub init thread was never started"
    # Hub init is still running — init_db didn't wait for it
    assert not hub_finished.is_set(), (
        "Hub init somehow finished before assertion; was sleep too short?"
    )
    # Wait for Hub thread to finish to avoid leaking it into other tests
    assert hub_finished.wait(timeout=5.0), "Hub init thread never finished"
