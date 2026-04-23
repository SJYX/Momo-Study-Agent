"""
web/backend/schemas.py: Pydantic 请求/响应模型，与前端 types.ts 对齐。

所有 API 响应统一格式：
    {"ok": true,  "data": ...}
    {"ok": false, "error": {"code": "...", "message": "..."}}
"""
from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# 统一响应信封
# ---------------------------------------------------------------------------
class ApiError(BaseModel):
    code: str = "UNKNOWN"
    message: str = ""


class ApiResponse(BaseModel, Generic[T]):
    ok: bool = True
    data: Optional[T] = None
    error: Optional[ApiError] = None
    user_id: str = ""  # 面向未来多用户预埋


def ok_response(data: Any = None, user_id: str = "") -> dict:
    """快速构造成功响应字典。"""
    return {"ok": True, "data": data, "error": None, "user_id": user_id}


def error_response(code: str, message: str, user_id: str = "") -> dict:
    """快速构造错误响应字典。"""
    return {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message},
        "user_id": user_id,
    }


# ---------------------------------------------------------------------------
# /api/session
# ---------------------------------------------------------------------------
class SessionInfo(BaseModel):
    active_user: str
    ai_provider: str
    batch_size: int
    dry_run: bool
    db_path: str


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------
class HealthInfo(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


# ---------------------------------------------------------------------------
# Task 相关
# ---------------------------------------------------------------------------
class TaskSubmitResponse(BaseModel):
    task_id: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str  # pending | running | done | error | canceled
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: float = 0.0
    finished_at: Optional[float] = None


# ---------------------------------------------------------------------------
# /api/study/today
# ---------------------------------------------------------------------------
class TodayItem(BaseModel):
    voc_id: str
    voc_spelling: str
    voc_meanings: str = ""
    review_count: int = 0
    familiarity_short: float = 0.0


# ---------------------------------------------------------------------------
# /api/words
# ---------------------------------------------------------------------------
class WordNoteSummary(BaseModel):
    voc_id: str
    spelling: str = ""
    basic_meanings: str = ""
    memory_aid: str = ""
    it_level: int = 0
    sync_status: int = 0
    created_at: str = ""


class WordNoteDetail(WordNoteSummary):
    ielts_focus: str = ""
    collocations: str = ""
    traps: str = ""
    synonyms: str = ""
    discrimination: str = ""
    example_sentences: str = ""
    word_ratings: str = ""
    tags: str = ""
    raw_full_text: str = ""
    it_history: str = ""


# ---------------------------------------------------------------------------
# /api/stats/summary
# ---------------------------------------------------------------------------
class StatsSummary(BaseModel):
    total_words: int = 0
    processed_words: int = 0
    ai_batches: int = 0
    total_tokens: int = 0
    avg_latency_ms: float = 0.0
    sync_queue_depth: int = 0
    weak_words_count: int = 0


# ---------------------------------------------------------------------------
# /api/sync/status
# ---------------------------------------------------------------------------
class SyncStatusItem(BaseModel):
    voc_id: str
    spelling: str = ""
    sync_status: int = 0
    basic_meanings: str = ""
    created_at: str = ""


# ---------------------------------------------------------------------------
# /api/users
# ---------------------------------------------------------------------------
class UserProfile(BaseModel):
    username: str
    ai_provider: str = ""
    has_momo_token: bool = False
    has_ai_key: bool = False


# ---------------------------------------------------------------------------
# /api/preflight
# ---------------------------------------------------------------------------
class PreflightItem(BaseModel):
    name: str
    status: str  # "ok" | "fail" | "warn"
    detail: str = ""
    fix_hint: str = ""