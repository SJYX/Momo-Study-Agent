"""tests/unit/database/test_sync_coordinator.py: ProfileSyncCoordinator timing tests.

Coordinator schedules sync via debounce + max_delay; tests focus on the
*scheduling* behavior (when does _do_sync fire?), not what _do_sync does
internally — that's the backend's contract, not the coordinator's.

Each test replaces `coord._do_sync` with a fake that records call timestamps,
isolating the coordinator's timer/lock state machine from the real DB.
"""
from __future__ import annotations

import threading
import time

import pytest

from database.sync_coordinator import ProfileSyncCoordinator


@pytest.fixture
def coord():
    """Coordinator with replaced _do_sync to count invocations.

    Tight windows (debounce=0.15s, max_delay=0.4s) keep tests fast while
    staying well above OS scheduler jitter (~10-20ms on Windows).
    """
    c = ProfileSyncCoordinator(
        db_path="dummy.db",
        backend=None,
        debounce_seconds=0.15,
        max_delay_seconds=0.4,
    )
    c.sync_calls: list[float] = []

    def _fake_do_sync():
        c.sync_calls.append(time.time())

    c._do_sync = _fake_do_sync  # type: ignore[method-assign]
    yield c
    # ensure no leftover timer threads
    c.shutdown(flush=False)


# ── Baseline: existing single-write behavior still works ──────────────────


def test_mark_dirty_fires_sync_after_debounce(coord):
    """Single mark_dirty fires _do_sync once after the debounce elapses."""
    coord.mark_dirty()
    time.sleep(0.3)  # > debounce (0.15)
    assert len(coord.sync_calls) == 1


# ── New: max_delay bounds the wait under continuous writes ────────────────


def test_continuous_writes_still_sync_after_max_delay(coord):
    """Writes faster than debounce must still trigger sync within max_delay.

    Bug fix target: pure debounce starves _do_sync under continuous writes,
    causing the local WAL to accumulate frames that pay off as a long
    push() on the next startup. max_delay forces a sync within a bounded
    window even when debounce keeps getting reset.
    """
    started_at = time.time()
    for _ in range(8):
        coord.mark_dirty()
        time.sleep(0.08)  # < debounce (0.15), so debounce would reset every iter
    # 8 * 0.08 = 0.64s elapsed; max_delay (0.4) should have forced ≥1 sync
    assert len(coord.sync_calls) >= 1
    # First sync should fire within max_delay + a small jitter tolerance
    first_sync_delay = coord.sync_calls[0] - started_at
    assert first_sync_delay <= 0.55, (
        f"first sync took {first_sync_delay:.3f}s, expected ≤ max_delay+tolerance"
    )


def test_first_dirty_window_resets_after_sync(coord):
    """After a successful sync, the next mark_dirty starts a fresh max_delay window.

    Otherwise _first_dirty_ts would carry over and the second batch would
    fire sync immediately, masking real backlog growth.
    """
    coord.mark_dirty()
    time.sleep(0.3)
    assert len(coord.sync_calls) == 1, "first cycle should sync"

    # Second batch of continuous writes; must again be bounded by max_delay
    second_batch_start = time.time()
    for _ in range(8):
        coord.mark_dirty()
        time.sleep(0.08)
    assert len(coord.sync_calls) >= 2, "second cycle should also sync"
    second_sync_delay = coord.sync_calls[-1] - second_batch_start
    assert second_sync_delay <= 0.55


# ── New: shutdown(flush=True) drains pending dirty ────────────────────────


def test_shutdown_flush_runs_pending_sync(coord):
    """shutdown(flush=True) executes _do_sync synchronously when dirty.

    Without this, Ctrl+C during the 5-second debounce window loses any
    writes that arrived in that window — they sit in the local WAL until
    next startup, where they pay off as a slow push().
    """
    coord.mark_dirty()
    # Don't wait for debounce — shutdown should still flush
    coord.shutdown(flush=True)
    assert len(coord.sync_calls) == 1


def test_shutdown_flush_noop_when_clean(coord):
    """shutdown(flush=True) with no pending dirty is a no-op (no spurious sync)."""
    coord.shutdown(flush=True)
    assert len(coord.sync_calls) == 0


def test_shutdown_default_does_not_flush(coord):
    """Default shutdown() preserves old behavior: cancel timer, no sync.

    Backward-compat guard: existing call sites use coord.shutdown() and
    rely on it being non-blocking and side-effect-free for sync.
    """
    coord.mark_dirty()
    coord.shutdown()  # flush=False default
    time.sleep(0.3)  # would have fired by now if timer wasn't cancelled
    assert len(coord.sync_calls) == 0
