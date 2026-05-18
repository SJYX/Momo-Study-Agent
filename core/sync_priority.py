"""
core/sync_priority.py: 同步任务优先级定义。

P1 = 今日任务（study_workflow / study_flow 触发）
P2 = 用户主动（UI 点击立即同步 / 重试）
P3 = warmup 自动补偿（profile 首次进入扫描）
P4 = 预留（延迟重试 / 定时补偿）

数值越小优先级越高，与 queue.PriorityQueue 默认排序一致。
"""
from __future__ import annotations

from enum import IntEnum


class Priority(IntEnum):
    P1 = 1
    P2 = 2
    P3 = 3
    P4 = 4
