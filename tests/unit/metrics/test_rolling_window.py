"""tests/unit/metrics/test_rolling_window.py: RollingWindow 单元测试。"""
from __future__ import annotations

import threading

import pytest

from core.metrics import RollingWindow


class TestRollingWindow:
    def test_empty_window_percentile_is_none(self):
        w = RollingWindow(ttl_s=60, max_size=100)
        assert w.percentile(50) is None
        assert w.percentile(95) is None
        assert w.count() == 0

    def test_single_sample(self):
        w = RollingWindow(ttl_s=60, max_size=100)
        w.record(42.0)
        assert w.percentile(50) == 42.0
        assert w.percentile(95) == 42.0
        assert w.count() == 1

    def test_percentile_basic(self):
        w = RollingWindow(ttl_s=60, max_size=100)
        for v in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]:
            w.record(v)
        # P50 between 5 and 6 (rank=4.5 -> 5.5)
        assert w.percentile(50) == pytest.approx(5.5)
        # P95 close to 10 (rank=8.55 -> ~9.55)
        assert w.percentile(95) == pytest.approx(9.55)

    def test_ttl_eviction(self):
        w = RollingWindow(ttl_s=10, max_size=100)
        # 注入 100 秒前的旧数据
        w.record(1.0, now=0.0)
        w.record(2.0, now=0.0)
        # 再记一条新的
        w.record(99.0, now=100.0)
        # 在 t=100s 读 → 旧数据已过期，只剩 99
        assert w.percentile(50, now=100.0) == 99.0
        assert w.count(now=100.0) == 1

    def test_max_size_cap(self):
        w = RollingWindow(ttl_s=3600, max_size=5)
        for v in range(10):
            w.record(float(v))
        # 容量 5，应保留最后 5 个 (5..9)
        assert w.count() == 5
        # 前 5 个已被裁掉，P50 应在 5..9 中段
        p50 = w.percentile(50)
        assert p50 is not None and 5.0 <= p50 <= 9.0

    def test_reset(self):
        w = RollingWindow(ttl_s=60, max_size=100)
        for v in [1.0, 2.0, 3.0]:
            w.record(v)
        assert w.count() == 3
        w.reset()
        assert w.count() == 0
        assert w.percentile(50) is None

    def test_invalid_percentile(self):
        w = RollingWindow(ttl_s=60, max_size=100)
        with pytest.raises(ValueError):
            w.percentile(-1)
        with pytest.raises(ValueError):
            w.percentile(101)

    def test_invalid_init_args(self):
        with pytest.raises(ValueError):
            RollingWindow(ttl_s=0)
        with pytest.raises(ValueError):
            RollingWindow(ttl_s=60, max_size=0)

    def test_concurrent_record(self):
        """多线程并发 record 不应崩或漏数据。"""
        w = RollingWindow(ttl_s=60, max_size=10000)

        def writer(n: int) -> None:
            for i in range(n):
                w.record(float(i))

        threads = [threading.Thread(target=writer, args=(100,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert w.count() == 1000
