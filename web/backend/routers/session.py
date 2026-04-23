"""
web/backend/routers/session.py: GET /api/session — 当前锁定用户信息 + 配置摘要。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from web.backend.deps import get_active_user
from web.backend.schemas import SessionInfo, ok_response

router = APIRouter(prefix="/api", tags=["session"])


@router.get("/session")
async def get_session(user: str = Depends(get_active_user)):
    """返回当前锁定用户、AI 配置摘要。"""
    from config import AI_PROVIDER, BATCH_SIZE, DRY_RUN, DB_PATH
    info = SessionInfo(
        active_user=user,
        ai_provider=AI_PROVIDER,
        batch_size=BATCH_SIZE,
        dry_run=DRY_RUN,
        db_path=DB_PATH,
    )
    return ok_response(info.model_dump(), user_id=user)