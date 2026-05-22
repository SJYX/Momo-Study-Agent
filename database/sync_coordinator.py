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
    ):
        self.db_path = db_path
        self._backend = backend
        self._debounce = debounce_seconds

        self._last_write_ts = 0.0
        self._timer: Optional[threading.Timer] = None
        self._timer_lock = threading.Lock()
        self._sync_lock = threading.Lock()  # Guards _do_sync serialization

    def mark_dirty(self) -> None:
        """Called after a successful write. Starts/resets the debounce timer."""
        self._last_write_ts = time.time()

        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce, self._check_and_sync)
            self._timer.daemon = True
            self._timer.start()

    def shutdown(self) -> None:
        """Cancel any pending timer. Called during profile cleanup."""
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _wait_for_writes_drained(self, timeout: float = 3.0) -> bool:
        """Wait for the writer daemon's write queue to drain before starting sync.

        pyturso sync (push→pull→checkpoint) and writer daemon (BEGIN IMMEDIATE)
        race for the write lock on the same DB file. We wait for the queue to
        be empty so the writer daemon has finished its current batch.

        Returns True if queue drained within timeout, False if still has items.
        """
        from database.execution_engine import _write_queue
        deadline = time.time() + timeout
        while time.time() < deadline:
            if _write_queue.empty():
                return True
            time.sleep(0.1)
        return False

    def _check_and_sync(self) -> None:
        """Timer callback: check if debounce has passed, then sync.

        Uses non-blocking acquire to prevent concurrent _do_sync.
        If another _do_sync is running, this callback simply exits —
        the running sync will pick up the latest writes, and any
        subsequent mark_dirty() will start a fresh timer.

        Before syncing, waits for the writer daemon queue to drain to
        avoid disk I/O errors from concurrent write lock contention.
        """
        now = time.time()

        if (now - self._last_write_ts) < self._debounce:
            # New writes arrived very recently; reset timer for remaining window
            remaining = self._debounce - (now - self._last_write_ts)
            with self._timer_lock:
                self._timer = threading.Timer(remaining, self._check_and_sync)
                self._timer.daemon = True
                self._timer.start()
            return

        # Non-blocking: skip if another sync is already in progress
        if not self._sync_lock.acquire(blocking=False):
            return

        try:
            # Wait for writer queue to drain before starting sync
            if not self._wait_for_writes_drained(timeout=3.0):
                from database.utils import _debug_log
                _debug_log(
                    f"写队列未排空，延迟同步 (db={os.path.basename(self.db_path)})",
                    level="WARNING",
                    module="database.sync_coordinator",
                )
            self._do_sync()
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
                with backend.op_lock_for(conn):
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
