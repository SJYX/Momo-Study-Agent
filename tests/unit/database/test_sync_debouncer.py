"""SyncDebouncer 去抖逻辑测试。"""

import time

from database.sync_debouncer import SyncDebouncer


def test_debouncer_delays_execution():
    """debouncer 在 delay 秒后才执行回调。"""
    d = SyncDebouncer(delay=0.2)
    result = []
    d.trigger(lambda: result.append("fired"))
    assert result == []
    time.sleep(0.3)
    assert result == ["fired"]


def test_debouncer_cancels_previous():
    """连续 trigger 只执行最后一次。"""
    d = SyncDebouncer(delay=0.15)
    results = []
    d.trigger(lambda: results.append(1))
    time.sleep(0.05)
    d.trigger(lambda: results.append(2))
    time.sleep(0.25)
    assert results == [2]


def test_debouncer_flush_executes_immediately():
    """flush 绕过去抖立即执行。"""
    d = SyncDebouncer(delay=10.0)
    result = []
    d.trigger(lambda: result.append("delayed"))
    d.flush(lambda: result.append("flushed"))
    assert result == ["flushed"]
