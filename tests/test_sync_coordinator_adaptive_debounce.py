"""测试 ProfileSyncCoordinator 自适应去抖动功能"""
import pytest
import time
from unittest.mock import Mock
from database.sync_coordinator import ProfileSyncCoordinator


def test_adaptive_delay_high_frequency():
    """验证高频写入返回最小延迟（1 秒）"""
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=Mock(),
        debounce_seconds=5.0
    )

    # 模拟高频写入：10 次写入在 2 秒内
    now = time.time()
    coordinator._write_timestamps = [
        now - 2.0, now - 1.8, now - 1.6, now - 1.4, now - 1.2,
        now - 1.0, now - 0.8, now - 0.6, now - 0.4, now - 0.2
    ]

    delay = coordinator._calculate_adaptive_delay()

    assert delay == 1.0  # 最小延迟


def test_adaptive_delay_low_frequency():
    """验证低频写入返回最大延迟（3 秒）"""
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=Mock(),
        debounce_seconds=5.0
    )

    # 模拟低频写入：6 次写入，间隔均 >= 5 秒
    now = time.time()
    coordinator._write_timestamps = [
        now - 30.0, now - 24.0, now - 18.0, now - 12.0, now - 6.0, now - 1.0
    ]

    delay = coordinator._calculate_adaptive_delay()

    assert delay == 3.0  # 最大延迟


def test_adaptive_delay_insufficient_data():
    """验证数据不足时返回最大延迟"""
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=Mock(),
        debounce_seconds=5.0
    )

    # 只有 3 次写入（< 5）
    now = time.time()
    coordinator._write_timestamps = [now - 2.0, now - 1.0, now - 0.5]

    delay = coordinator._calculate_adaptive_delay()

    assert delay == 3.0  # 数据不足，返回最大延迟
