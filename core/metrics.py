"""
core/metrics.py: 进程内轻量指标层，给 B3 闲时引擎与 B5 可观测性 endpoint 用。

设计要点（PLAYBOOK B5）：
- 仅进程内存，重启后丢失。对运行期决策足够；无需 SQLite 持久化
- 按 (profile, metric_name) 二维隔离，多用户 Web 场景下天然不串
- RollingWindow 双约束：max_size 防爆内存 + ttl_s 时间窗口
- record 时顺手 evict 过期项，不起后台线程
- percentile 用线性插值；空窗口返回 None
- 线程安全：每个 RollingWindow 独立锁；MetricsCollector 仅锁住 dict 查找/插入

不做：
- LogStatistics 那种无界累积；本模块是它的替代品而非升级
- 后台周期 dump；通过 /api/ops/metrics endpoint 按需读
- 通过 logging Handler 自动采集；调用方显式 record
"""
from __future__ import annotations

import bisect
import threading
import time
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# RollingWindow
# ---------------------------------------------------------------------------
class RollingWindow:
    """有限容量 + TTL 双约束的时间序列。

    内部以 (timestamp, value) 列表存储；记录时同时按容量与时间裁剪。
    线程安全。
    """

    __slots__ = ("_ttl_s", "_max_size", "_data", "_lock")

    def __init__(self, ttl_s: float = 300.0, max_size: int = 1000) -> None:
        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._ttl_s = float(ttl_s)
        self._max_size = int(max_size)
        self._data: List[Tuple[float, float]] = []
        self._lock = threading.Lock()

    def record(self, value: float, *, now: Optional[float] = None) -> None:
        """记录一个采样。now 仅测试用；生产代码省略即可。"""
        ts = float(now) if now is not None else time.time()
        v = float(value)
        with self._lock:
            self._evict_expired(ts)
            self._data.append((ts, v))
            overflow = len(self._data) - self._max_size
            if overflow > 0:
                del self._data[0:overflow]

    def percentile(self, p: float, *, now: Optional[float] = None) -> Optional[float]:
        """返回 p 分位值；空窗口返回 None。p 取 0-100。"""
        if not 0 <= p <= 100:
            raise ValueError("p must be in [0, 100]")
        ts = float(now) if now is not None else time.time()
        with self._lock:
            self._evict_expired(ts)
            if not self._data:
                return None
            values = sorted(v for _, v in self._data)
        if len(values) == 1:
            return values[0]
        # 线性插值百分位
        rank = (p / 100.0) * (len(values) - 1)
        lo = int(rank)
        hi = min(lo + 1, len(values) - 1)
        frac = rank - lo
        return values[lo] + (values[hi] - values[lo]) * frac

    def count(self, *, now: Optional[float] = None) -> int:
        ts = float(now) if now is not None else time.time()
        with self._lock:
            self._evict_expired(ts)
            return len(self._data)

    def reset(self) -> None:
        with self._lock:
            self._data.clear()

    def _evict_expired(self, now: float) -> None:
        """删除时间窗口外的样本。调用方必须持有 _lock。"""
        if not self._data:
            return
        cutoff = now - self._ttl_s
        # data 按 ts 单调递增（record 用 time.time() 严格递增），用 bisect 找截断点
        keys = [t for t, _ in self._data]
        idx = bisect.bisect_left(keys, cutoff)
        if idx > 0:
            del self._data[0:idx]


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------
class MetricsCollector:
    """进程级单例，按 (profile, metric_name) 维护 RollingWindow。"""

    def __init__(self, ttl_s: float = 300.0, max_size: int = 1000) -> None:
        self._ttl_s = ttl_s
        self._max_size = max_size
        self._windows: Dict[Tuple[str, str], RollingWindow] = {}
        self._dict_lock = threading.Lock()

    def _get_or_create(self, profile: str, metric: str) -> RollingWindow:
        key = (profile, metric)
        with self._dict_lock:
            w = self._windows.get(key)
            if w is None:
                w = RollingWindow(ttl_s=self._ttl_s, max_size=self._max_size)
                self._windows[key] = w
            return w

    def record(self, profile: str, metric: str, value: float) -> None:
        """记录一次采样。profile 为 None/"" 时归到 sentinel "_global"。"""
        p = profile or "_global"
        try:
            self._get_or_create(p, metric).record(value)
        except Exception:
            # 指标采集不应破坏业务路径
            pass

    def percentile(self, profile: str, metric: str, p: float) -> Optional[float]:
        key = (profile or "_global", metric)
        with self._dict_lock:
            w = self._windows.get(key)
        return w.percentile(p) if w is not None else None

    def count(self, profile: str, metric: str) -> int:
        key = (profile or "_global", metric)
        with self._dict_lock:
            w = self._windows.get(key)
        return w.count() if w is not None else 0

    def snapshot(self, profile: Optional[str] = None) -> Dict[str, Dict[str, Dict[str, float | int | None]]]:
        """返回按 profile 分组的快照。
        profile=None 返回所有 profile；指定 profile 仅该 profile。
        每条指标输出 p50/p95/p99/count。
        """
        with self._dict_lock:
            items = list(self._windows.items())
        out: Dict[str, Dict[str, Dict[str, float | int | None]]] = {}
        for (prof, metric), w in items:
            if profile is not None and prof != profile:
                continue
            out.setdefault(prof, {})[metric] = {
                "p50": w.percentile(50),
                "p95": w.percentile(95),
                "p99": w.percentile(99),
                "count": w.count(),
            }
        return out

    def reset(self, profile: Optional[str] = None) -> None:
        """清空指定 profile 的窗口；None 清空全部。"""
        with self._dict_lock:
            if profile is None:
                self._windows.clear()
                return
            keys_to_drop = [k for k in self._windows if k[0] == profile]
            for k in keys_to_drop:
                del self._windows[k]


# ---------------------------------------------------------------------------
# 进程级访问器
# ---------------------------------------------------------------------------
_collector: Optional[MetricsCollector] = None
_collector_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """获取或创建进程级 MetricsCollector 单例。"""
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = MetricsCollector()
    return _collector


def reset_collector_for_test() -> None:
    """测试钩子：销毁单例让下个用例拿到干净实例。"""
    global _collector
    with _collector_lock:
        _collector = None
