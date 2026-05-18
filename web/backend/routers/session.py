"""
web/backend/routers/session.py: GET /api/session — 当前 profile 信息 + 可用 profile 列表。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from web.backend.deps import get_active_user
from web.backend.schemas import ApiResponse, SessionInfo, ok_response

router = APIRouter(prefix="/api", tags=["session"])


@router.get("/session", response_model=ApiResponse[SessionInfo])
async def get_session(user: str = Depends(get_active_user)):
    """返回当前 profile、可用 profile 列表、服务器时间、绑定地址。"""
    from config import PROFILES_DIR
    from core.profile_manager import ProfileManager

    pm = ProfileManager(PROFILES_DIR)
    profiles = pm.list_profiles()

    info = SessionInfo(
        active_profile=user,
        available_profiles=profiles,
        server_time=datetime.now(timezone.utc).isoformat(),
        host_binding="127.0.0.1",
    )
    return ok_response(info.model_dump(), user_id=user)
