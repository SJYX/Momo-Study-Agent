"""
core/feature_flags.py: 进程级 feature flag 读取，主要用于 PLAYBOOK A4 Kill Switch。

设计：
- 默认值 True（保留既有行为），出现性能回退时 ops 可一键 False
- Phase 6.3b 起：已知 flag 由 ``core.settings.Settings`` 校验持有；本模块只是
  对外的"测试友好"读取门面（保留 ``set_enabled`` / ``reset_overrides`` 钩子）
- 未知 flag 仍兜底走 ``os.getenv``——给临时调试用，不强制登记到 Settings
- 所有正式 flag 名称在本文件 ``_KNOWN_FLAGS`` 集中登记，与 Settings 模型对齐
"""
from __future__ import annotations

import os
import threading
from typing import Dict, Set

_KNOWN_FLAGS: Set[str] = {
    "AUTO_WARMUP_SYNC_ENABLED",
    "SYNC_STATUS_HEAVY_QUERY_ENABLED",
    "BACKGROUND_RETRY_ENABLED",
}

_TRUTHY = {"1", "true", "yes", "y", "on"}
_FALSY = {"0", "false", "no", "n", "off"}

_lock = threading.Lock()
_test_overrides: Dict[str, bool] = {}


def _parse_bool(raw: str, default: bool) -> bool:
    s = (raw or "").strip().lower()
    if s in _TRUTHY:
        return True
    if s in _FALSY:
        return False
    return default


def is_enabled(name: str, default: bool = True) -> bool:
    """检查 feature flag 是否启用。

    优先级：测试 override > Settings 模型（已知 flag）> os.getenv > default。
    """
    with _lock:
        if name in _test_overrides:
            return _test_overrides[name]

    if name in _KNOWN_FLAGS:
        try:
            from core.settings import get_settings
            settings = get_settings()
            return bool(getattr(settings, name, default))
        except Exception:
            # settings 出问题不应阻塞 ops 路径；降级到 raw env
            pass

    raw = os.getenv(name)
    return _parse_bool(raw, default) if raw is not None else default


def set_enabled(name: str, value: bool) -> None:
    """测试钩子：覆盖 flag 状态。生产代码不要调用。"""
    with _lock:
        _test_overrides[name] = bool(value)


def reset_overrides() -> None:
    """清除所有测试 override。下次 ``is_enabled`` 重新读 Settings / env。

    同时清掉 ``core.settings`` 缓存，让 env 改动后下次读到新值。
    """
    with _lock:
        _test_overrides.clear()
    try:
        from core.settings import rebuild_settings
        rebuild_settings()
    except Exception:
        pass


def known_flags() -> Set[str]:
    """返回登记过的 flag 名称（用于 ops 检查 / pydantic 模型对齐）。"""
    return frozenset(_KNOWN_FLAGS)

