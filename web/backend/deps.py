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