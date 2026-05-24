"""tests/unit/web/test_user_context_warm_path.py: Fix E5 — verify the warm-DB
path runs warmup synchronously and never enters db_init_in_progress.

The state machine
  not_started → db_init_in_progress → db_init_done → done

was designed for the cold pyturso bootstrap (60-150s) where SyncGate has
to absorb the wait. On warm restart, init_db is ~100ms and the
'db_init_in_progress' window is just long enough for the frontend to
hit a 503 and flash SyncGate. The warm path should skip the state
machine entirely.

These tests exercise the dispatch logic (_decide_warmup_mode) without
constructing a full UserContext, so they don't need to mock the whole
profile_config / logger / AI client / workflow stack.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from web.backend.user_context import UserContextManager


@dataclass
class _StubCtx:
    """Minimal stand-in for UserContext — _decide_warmup_mode only reads .db_path."""
    db_path: str = ""


@pytest.mark.unit
def test_decide_warmup_mode_returns_sync_when_db_file_exists(tmp_path):
    """Existing local DB file with size>0 → warm path."""
    db_file = tmp_path / "history-test.db"
    db_file.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)

    manager = UserContextManager()
    ctx = _StubCtx(db_path=str(db_file))

    assert manager._decide_warmup_mode(ctx) == "sync"


@pytest.mark.unit
def test_decide_warmup_mode_returns_async_when_db_missing(tmp_path):
    """No local DB file → cold path needs pyturso bootstrap → async + SyncGate."""
    db_file = tmp_path / "history-test.db"
    # Don't create the file

    manager = UserContextManager()
    ctx = _StubCtx(db_path=str(db_file))

    assert manager._decide_warmup_mode(ctx) == "async"


@pytest.mark.unit
def test_decide_warmup_mode_returns_async_when_db_empty(tmp_path):
    """Empty file (size=0) is treated as cold — pyturso may want to bootstrap."""
    db_file = tmp_path / "history-test.db"
    db_file.touch()  # exists but size=0

    manager = UserContextManager()
    ctx = _StubCtx(db_path=str(db_file))

    assert manager._decide_warmup_mode(ctx) == "async"


@pytest.mark.unit
def test_decide_warmup_mode_returns_async_when_db_path_empty():
    """Empty db_path string → async (defensive — should not happen in practice)."""
    manager = UserContextManager()
    ctx = _StubCtx(db_path="")

    assert manager._decide_warmup_mode(ctx) == "async"


@pytest.mark.unit
def test_warm_sync_warmup_transitions_state_directly_to_db_init_done(tmp_path, monkeypatch):
    """The warm-path helper should mark state as 'db_init_done' without ever
    going through 'db_init_in_progress' — so the readiness middleware never
    sees the in_progress window and never returns 503.
    """
    db_file = tmp_path / "history-test.db"
    db_file.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)

    manager = UserContextManager()

    # Stub _warmup_sync (the body — calls init_db + prepare_for_task) so this
    # test focuses on state transitions, not init_db internals.
    monkeypatch.setattr(manager, "_warmup_sync", lambda ctx: None)
    monkeypatch.setattr(manager, "_warmup_async", lambda ctx: None)

    ctx = _StubCtx(db_path=str(db_file))
    ctx.profile_name = "test_warm"
    ctx.logger = type("L", (), {"warning": staticmethod(lambda *a, **kw: None)})()

    manager._run_warm_warmup(ctx)

    # Right after the call returns, state must already be db_init_done — not
    # db_init_in_progress (which would trigger SyncGate via the 503 middleware).
    state = manager._warmup_state.get("test_warm")
    assert state in ("db_init_done", "done"), (
        f"warm warmup should mark state ready immediately, got {state!r}"
    )
