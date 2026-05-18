"""
web/backend/routers/preflight.py: GET /api/preflight — 环境体检。

复用 core/preflight.run_preflight，同步返回检查结果。
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from web.backend.deps import get_active_user
from web.backend.schemas import ApiResponse, PreflightResponse, ok_response

router = APIRouter(prefix="/api", tags=["preflight"])


@router.get("/preflight", response_model=ApiResponse[PreflightResponse])
async def preflight(user: str = Depends(get_active_user)):
    """运行环境体检，返回检查项列表。"""
    from core.preflight import run_preflight
    from config import BASE_DIR

    result = run_preflight(root_dir=BASE_DIR, username=user)
    return ok_response(result, user_id=user)
