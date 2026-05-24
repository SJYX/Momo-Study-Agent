"""
database/sync_coordinator.py: Per-profile DB sync coordinator.

Replaces the global _sync_daemon polling loop with per-profile
threading.Timer-based event-driven sync.

Each profile gets its own ProfileSyncCoordinator instance.
When a write completes, the writer daemon calls coordinator.mark_dirty(),
which starts (or resets) a 5-second debounce timer. When the timer fires,
the coordinator executes push→pull→checkpoint for that specific db_path.

No polling, no global dict, no cross-profile state sharing.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional


# ── Global registry: db_path → ProfileSyncCoordinator ──
_coordinators: Dict[str, ProfileSyncCoordinator] = {}
_registry_lock = threading.Lock()


def get_sync_coordinator(db_path: str) -> Optional["ProfileSyncCoordinator"]:
    """Look up the coordinator for a given db_path."""
    abs_path = os.path.abspath(db_path)
    with _registry_lock:
        return _coordinators.get(abs_path)


def mark_db_written(db_path: str) -> None:
    """Convenience: find coordinator for db_path and call mark_dirty().
    No-op if no coordinator is registered (e.g. CLI path before init).
    """
    coord = get_sync_coordinator(db_path)
    if coord is not None:
        coord.mark_dirty()


class ProfileSyncCoordinator:
    """Per-profile DB sync coordinator with debounce timer.

    Design:
    - mark_dirty() sets _last_write_ts and starts a Timer(5.0)
    - Timer callback acquires _sync_lock (non-blocking) to prevent
      concurrent _do_sync on the same profile
    - After each sync, checks if new writes arrived during sync;
      if so, starts a fresh timer for the remaining debounce window

    Thread safety:
    - _last_write_ts: protected by _sync_lock during read in _check_and_sync
    - _timer: protected by _timer_lock (only one active timer at a time)
    - _sync_lock: non-reentrant, ensures at most one _do_sync per profile
    """

    def __init__(
        self,
        db_path: str,
        backend: Any,
        debounce_seconds: float = 5.0,
        max_delay_seconds: float = 30.0,
    ):
        self.db_path = db_path
        self._backend = backend
        self._debounce = debounce_seconds
        self._max_delay = max_delay_seconds

        self._last_write_ts = 0.0
        # _first_dirty_ts: time of the first mark_dirty since the last successful
        # sync; bounds the wait under continuous writes (debounce keeps resetting,
        # but max_delay forces a sync within max_delay seconds of this timestamp).
        # Cleared back to None after a successful _do_sync.
        self._first_dirty_ts: Optional[float] = None
        self._timer: Optional[threading.Timer] = None
        self._timer_lock = threading.Lock()
        self._sync_lock = threading.Lock()  # Guards _do_sync serialization

    def mark_dirty(self) -> None:
        """Called after a successful write. Starts/resets the debounce timer.

        max_delay safety net: under continuous writes (mark_dirty faster than
        debounce), the timer would keep getting reset and _do_sync would
        starve. Each call computes its timer delay as
            min(debounce, _first_dirty_ts + max_delay - now)
        so even a continuous stream of writes forces a sync within max_delay
        of the first un-synced write.
        """
        now = time.time()
        self._last_write_ts = now

        with self._timer_lock:
            if self._first_dirty_ts is None:
                self._first_dirty_ts = now
            max_remaining = max(0.0, (self._first_dirty_ts + self._max_delay) - now)
            delay = min(self._debounce, max_remaining)

            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(delay, self._check_and_sync)
            self._timer.daemon = True
            self._timer.start()

    def shutdown(self, flush: bool = False) -> None:
        """Cancel any pending timer. Called during profile cleanup.

        Args:
            flush: When True, synchronously run one push+pull+checkpoint cycle
                if there is pending dirty data, so writes in the open debounce
                window do not get deferred to the next startup. Use this from
                lifespan shutdown / atexit hooks.
        """
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        if not flush:
            return
        if self._first_dirty_ts is None:
            return

        # Blocking acquire: wait for any in-flight _check_and_sync to finish.
        # If it already drained the dirty data, _first_dirty_ts would now be
        # None and we'd skip — but re-check after the lock in case another
        # sync just completed.
        with self._sync_lock:
            if self._first_dirty_ts is None:
                return
            try:
                self._do_sync()
                self._first_dirty_ts = None
            finally:
                # _do_sync may re-arm a retry timer in its failure path;
                # cancel it so it doesn't fire after shutdown.
                with self._timer_lock:
                    if self._timer is not None:
                        self._timer.cancel()
                        self._timer = None

    def _check_and_sync(self) -> None:
        """Timer callback: check if debounce has passed, then sync.

        Uses non-blocking acquire to prevent concurrent _do_sync.
        If another _do_sync is running, this callback simply exits —
        the running sync will pick up the latest writes, and any
        subsequent mark_dirty() will start a fresh timer.

        max_delay override: if (now - _first_dirty_ts) >= max_delay, we
        fall through to sync even if the debounce window has new writes.
        Otherwise continuous writes would re-arm the timer forever.
        """
        now = time.time()

        max_delay_reached = (
            self._first_dirty_ts is not None
            and (now - self._first_dirty_ts) >= self._max_delay
        )

        if (now - self._last_write_ts) < self._debounce and not max_delay_reached:
            # New writes arrived very recently AND max_delay not yet hit —
            # wait for the shorter of (debounce remaining, max_delay remaining).
            remaining = self._debounce - (now - self._last_write_ts)
            if self._first_dirty_ts is not None:
                max_remaining = max(0.0, (self._first_dirty_ts + self._max_delay) - now)
                remaining = min(remaining, max_remaining)
            with self._timer_lock:
                self._timer = threading.Timer(remaining, self._check_and_sync)
                self._timer.daemon = True
                self._timer.start()
            return

        # Non-blocking: skip if another sync is already in progress
        if not self._sync_lock.acquire(blocking=False):
            return

        try:
            sync_started_at = time.time()
            self._do_sync()
            # Success: clear the "first dirty since last sync" window so the
            # next mark_dirty starts a fresh max_delay timer. If writes arrived
            # during _do_sync (last_write_ts > sync_started_at), the post-sync
            # re-arm below will pick them up.
            if self._last_write_ts <= sync_started_at:
                self._first_dirty_ts = None
            else:
                # Writes during sync; track those as the new first-dirty window.
                self._first_dirty_ts = sync_started_at
        finally:
            self._sync_lock.release()

            # Post-sync check: writes may have arrived during sync
            if (time.time() - self._last_write_ts) >= self._debounce:
                # Still dirty — start another cycle
                with self._timer_lock:
                    self._timer = threading.Timer(self._debounce, self._check_and_sync)
                    self._timer.daemon = True
                    self._timer.start()

    def _do_sync(self) -> None:
        """Execute push → pull → checkpoint."""
        from database.backends import get_active_backend
        from database.connection import _get_main_write_conn_singleton, _close_main_write_conn_singleton
        from database.utils import _debug_log

        backend = self._backend or get_active_backend()
        base = os.path.basename(self.db_path)

        try:
            _orig_db_path = __import__("config").DB_PATH
            if self.db_path != _orig_db_path:
                __import__("config").DB_PATH = self.db_path
            try:
                conn = _get_main_write_conn_singleton(do_sync=False)
            finally:
                if self.db_path != _orig_db_path:
                    __import__("config").DB_PATH = _orig_db_path

            sync_started_at = time.time()

            from database.execution_engine import set_db_syncing, clear_db_syncing
            set_db_syncing(phase="idle_sync")
            try:
                backend.do_sync_on(conn)
            finally:
                clear_db_syncing()

            sync_duration_ms = int((time.time() - sync_started_at) * 1000)
            is_slow = sync_duration_ms >= 500  # _SLOW_SYNC_MS
            try:
                from core.logger import get_logger
                logger = get_logger()
                msg = f"idle_sync done | db={base} | duration_ms={sync_duration_ms}"
                kwargs = dict(
                    module="database.sync_coordinator",
                    duration_ms=sync_duration_ms,
                    is_slow=is_slow,
                )
                if is_slow:
                    logger.warning(msg + " | slow=true", **kwargs)
                else:
                    logger.info(msg, **kwargs)
            except Exception:
                pass

            # PLAYBOOK B5: metrics
            try:
                from core.metrics import get_metrics_collector
                from core.active_profile_registry import get_active
                get_metrics_collector().record(
                    get_active() or "_global",
                    "db.idle_sync.duration_ms",
                    float(sync_duration_ms),
                )
            except Exception:
                pass

        except BaseException as e:
            _debug_log(
                f"闲时后台自动同步失败 (db_path={self.db_path[:30]}...): {e}",
                level="WARNING",
                module="database.sync_coordinator",
            )
            # On failure, start a retry timer (exponential backoff could be added here)
            with self._timer_lock:
                self._timer = threading.Timer(self._debounce, self._check_and_sync)
                self._timer.daemon = True
                self._timer.start()
