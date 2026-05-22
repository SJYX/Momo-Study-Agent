# database/sync_debouncer.py
"""去抖同步触发器：用户快速连续保存时合并为一次 sync。"""

from __future__ import annotations

import threading
from typing import Callable, Optional


class SyncDebouncer:
    """N 秒空闲后执行一次回调。连续调用 trigger() 会重置计时器。"""

    def __init__(self, delay: float = 1.5) -> None:
        self._delay = delay
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def trigger(self, fn: Callable[[], None]) -> None:
        """重置去抖计时器。已有待执行 timer 则取消并重建。"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, fn)
            self._timer.daemon = True
            self._timer.start()

    def flush(self, fn: Callable[[], None]) -> None:
        """立即执行（绕过去抖）。"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        fn()

    def shutdown(self) -> None:
        """取消待执行的 timer。"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


# ── 全局单例 ──

_instance: Optional[SyncDebouncer] = None
_instance_lock = threading.Lock()


def get_sync_debouncer() -> SyncDebouncer:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SyncDebouncer(delay=1.5)
    return _instance


def reset_sync_debouncer() -> None:
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.shutdown()
            _instance = None

