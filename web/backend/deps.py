"""
web/backend/deps.py: FastAPI 依赖注入 — 请求级 profile 上下文。

P0-P1 改造：从单用户全局单例改为按 X-Momo-Profile header 解析的 profile 级上下文。
保留原有 get_* 函数签名，router 层无需改动。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Header, Request

# ---------------------------------------------------------------------------
# 模块级单例（由 app.py lifespan 负责初始化 & 清理）
# ---------------------------------------------------------------------------
_context_manager = None  # UserContextManager 实例
_fallback_user: Optional[str] = None  # 启动时的默认用户（兼容无 header 场景）


def init_deps(context_manager, fallback_user: str = ""):
    """在 lifespan startup 中调用，注册 UserContextManager。"""
    global _context_manager, _fallback_user
    _context_manager = context_manager
    _fallback_user = fallback_user


def cleanup_deps():
    """在 lifespan shutdown 中调用，释放所有 profile 资源。"""
    global _context_manager
    if _context_manager:
        _context_manager.cleanup_all()
        _context_manager = None


# ---------------------------------------------------------------------------
# 内部辅助：解析当前请求的 profile
# ---------------------------------------------------------------------------
def _resolve_profile(
    x_momo_profile: Optional[str] = Header(default=None),
) -> str:
    """从 X-Momo-Profile header 解析 profile name，fallback 到启动用户。"""
    if x_momo_profile:
        return x_momo_profile.strip().lower()
    return _fallback_user or "default"


def _get_context(profile: str):
    """从 UserContextManager 获取指定 profile 的上下文。"""
    if _context_manager is None:
        raise RuntimeError("UserContextManager 未初始化")
    return _context_manager.get(profile)


# ---------------------------------------------------------------------------
# Depends 函数（路由层使用）
# ---------------------------------------------------------------------------
def get_active_user(
    x_momo_profile: Optional[str] = Header(default=None),
) -> str:
    """当前请求的 profile name。读取 X-Momo-Profile header。"""
    return _resolve_profile(x_momo_profile)


def get_user_context(
    x_momo_profile: Optional[str] = Header(default=None),
):
    """当前请求的完整 UserContext。"""
    profile = _resolve_profile(x_momo_profile)
    return _get_context(profile)


def get_logger(
    x_momo_profile: Optional[str] = Header(default=None),
):
    ctx = _get_context(_resolve_profile(x_momo_profile))
    return ctx.logger


def get_momo_api(
    x_momo_profile: Optional[str] = Header(default=None),
):
    ctx = _get_context(_resolve_profile(x_momo_profile))
    return ctx.momo_api


def get_ai_client(
    x_momo_profile: Optional[str] = Header(default=None),
):
    ctx = _get_context(_resolve_profile(x_momo_profile))
    return ctx.ai_client


def get_workflow(
    x_momo_profile: Optional[str] = Header(default=None),
):
    ctx = _get_context(_resolve_profile(x_momo_profile))
    return ctx.workflow


def get_task_registry(
    x_momo_profile: Optional[str] = Header(default=None),
):
    ctx = _get_context(_resolve_profile(x_momo_profile))
    return ctx.task_registry


def get_logger_bridge(
    x_momo_profile: Optional[str] = Header(default=None),
):
    ctx = _get_context(_resolve_profile(x_momo_profile))
    return ctx.logger_bridge


# ---------------------------------------------------------------------------
# 兼容旧接口（已废弃，保留给 users.py 等迁移期间使用）
# ---------------------------------------------------------------------------
def reload_user_services():
    """已废弃：profile 切换现在由 UserContextManager 自动处理。"""
    pass
