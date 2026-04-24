"""
web/backend/deps.py: FastAPI 依赖注入 — 单例资源在 lifespan 里创建，请求中用 Depends 注入。

第一期：单用户模式（进程启动时锁定 ACTIVE_USER）。
Phase 6：替换为 JWT / Session 级别的多租户注入。
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, Request

# ---------------------------------------------------------------------------
# 模块级单例（由 app.py lifespan 负责初始化 & 清理）
# ---------------------------------------------------------------------------
_active_user: Optional[str] = None
_logger = None
_momo_api = None
_ai_client = None
_workflow = None
_iteration_manager = None
_task_registry = None
_logger_bridge = None
_sync_manager = None


def init_deps(
    active_user: str,
    logger,
    momo_api,
    ai_client,
    workflow,
    task_registry,
    logger_bridge,
):
    """在 lifespan startup 中调用，注册所有单例。"""
    global _active_user, _logger, _momo_api, _ai_client
    global _workflow, _task_registry, _logger_bridge
    _active_user = active_user
    _logger = logger
    _momo_api = momo_api
    _ai_client = ai_client
    _workflow = workflow
    _task_registry = task_registry
    _logger_bridge = logger_bridge


def cleanup_deps():
    """在 lifespan shutdown 中调用，释放资源。"""
    global _workflow, _momo_api, _ai_client, _logger_bridge
    if _workflow:
        try:
            _workflow.shutdown()
        except Exception:
            pass
    if _momo_api and hasattr(_momo_api, "close"):
        try:
            _momo_api.close()
        except Exception:
            pass
    if _ai_client and hasattr(_ai_client, "close"):
        try:
            _ai_client.close()
        except Exception:
            pass
    if _task_registry:
        try:
            _task_registry.shutdown()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Depends 函数（路由层使用）
# ---------------------------------------------------------------------------
def reload_user_services():
    """用户切换后重建 momo_api / ai_client 等服务单例。"""
    global _momo_api, _ai_client

    import config as _cfg

    # 重建 MaiMemoAPI（token 变了）
    old_momo = _momo_api
    try:
        from core.maimemo_api import MaiMemoAPI
        _momo_api = MaiMemoAPI(_cfg.MOMO_TOKEN)
    except Exception:
        _momo_api = None
    if old_momo and hasattr(old_momo, "close"):
        try:
            old_momo.close()
        except Exception:
            pass

    # 重建 AI client（provider / key 可能变了）
    old_ai = _ai_client
    try:
        if _cfg.AI_PROVIDER == "mimo":
            from core.mimo_client import MimoClient
            _ai_client = MimoClient(_cfg.MIMO_API_KEY)
        else:
            from core.gemini_client import GeminiClient
            _ai_client = GeminiClient(_cfg.GEMINI_API_KEY)
    except Exception:
        _ai_client = None
    if old_ai and hasattr(old_ai, "close"):
        try:
            old_ai.close()
        except Exception:
            pass

    # 更新 workflow 的内部引用
    if _workflow:
        _workflow.momo_api = _momo_api
        _workflow.ai_client = _ai_client


def get_active_user() -> str:
    """当前锁定用户。短期进程级常量；Phase 6 改为 JWT 解析。"""
    return _active_user or "default"


def get_logger():
    return _logger


def get_momo_api():
    return _momo_api


def get_ai_client():
    return _ai_client


def get_workflow():
    return _workflow


def get_task_registry():
    return _task_registry


def get_logger_bridge():
    return _logger_bridge