"""
core/active_profile_registry.py: 进程级活跃 profile 注册表。

由 web/backend/deps.py::_resolve_profile() 在每个 API 请求时调用 set_active()。
SyncManager worker 在出队前用 is_active() 自检——非 active profile 的低优任务（P3+）
应让位给 active profile 的同步吞吐。

CLI 模式下未调用 set_active() 时，get_active() 返回 None；is_active() 对所有 profile
都返回 True（向后兼容：无前端在跑 = 所有 worker 都按本来的优先级处理）。
"""
from __future__ import annotations

import threading
from typing import Optional

_lock = threading.Lock()
_active_profile: Optional[str] = None


def set_active(profile_name: str) -> None:
    """记录最近一次发起 API 请求的 profile（即用户当前操作的 profile）。"""
    global _active_profile
    if not profile_name:
        return
    normalized = profile_name.strip().lower()
    if not normalized:
        return
    with _lock:
        _active_profile = normalized


def get_active() -> Optional[str]:
    with _lock:
        return _active_profile


def is_active(profile_name: str) -> bool:
    """非 web 场景（无 set_active 调用）下默认所有 profile 都视为 active。"""
    if not profile_name:
        return True
    with _lock:
        if _active_profile is None:
            return True
        return _active_profile == profile_name.strip().lower()


def reset() -> None:
    """测试辅助：清空注册表状态。"""
    global _active_profile
    with _lock:
        _active_profile = None
