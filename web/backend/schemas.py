"""
web/backend/schemas.py: Pydantic 请求/响应模型，与前端 types.ts 对齐。

所有 API 响应统一格式：
    {"ok": true,  "data": ...}
    {"ok": false, "error": {"code": "...", "message": "..."}}
"""
from __future__ import annotations

from typing import Annotated, Any, Generic, Literal, Optional, TypeVar, Union

from pydantic import BaseModel, Field, RootModel

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
    active_profile: str
    available_profiles: list[str] = Field(default_factory=list)
    server_time: str
    host_binding: str = "127.0.0.1"


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
    started_at: Optional[float] = None
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
    status: Optional[str] = None  # done | None


class TodayItemsResponse(BaseModel):
    count: int = 0
    items: list[TodayItem] = Field(default_factory=list)
    ts: float = 0.0


class FutureItemsResponse(BaseModel):
    days: int = 7
    count: int = 0
    items: list[TodayItem] = Field(default_factory=list)


class IterationCandidateItem(BaseModel):
    voc_id: str
    voc_spelling: str
    voc_meanings: str = ""
    it_level: int = 0
    weak_score: float = 0.0


class IterationCandidatesResponse(BaseModel):
    count: int = 0
    items: list[IterationCandidateItem] = Field(default_factory=list)


class TaskRunResponse(BaseModel):
    task_id: Optional[str] = None
    word_count: Optional[int] = None
    days: Optional[int] = None
    message: Optional[str] = None


class TaskCancelResponse(BaseModel):
    canceled: bool = True


class ProcessRequest(BaseModel):
    voc_ids: Optional[list[str]] = Field(
        default=None, 
        description="Optional list of vocabulary IDs to process. If empty, process all pending."
    )


# ---------------------------------------------------------------------------
# Task event protocol — discriminated union by `type`
#
# 5 event variants:
#   - log         logger 透传（info/warning/error）
#   - status      任务级状态切换（running/done/error/canceled）
#   - heartbeat   SSE 保活
#   - progress    任务级总进度（phase + current/total）
#   - row_status  行级状态批量回填（list[RowState]）
#
# 兼容性元数据：
#   - _seq:  TaskRegistry._emit_event 注入的全局序号，用于前端去重/排序。
#           不在 schema 强约束内，但事件 dict 始终带它。
#   - ts:    服务器时间戳（time.time()）。
#
# 协议演进守则：
#   - 新增 type 必须先扩 union，再让发射方代码生成。
#   - phase 字符串集合见 docs/dev/EVENT_PROTOCOL.md（待补）。
# ---------------------------------------------------------------------------
RowStatus = Literal["pending", "running", "done", "error", "warning"]
TaskStatus = Literal["pending", "running", "done", "error", "canceled"]
LogLevel = Literal["info", "warning", "error"]


class RowState(BaseModel):
    """行级状态回填的最小单元。"""
    item_id: str
    status: RowStatus
    phase: Optional[str] = None
    error: Optional[str] = None
    # V1-T0：失败分组协议字段。后端发射端在 V1 暂不填充，前端 fallback 用 phase 兜底。
    # 正式契约升级排在 C08。
    error_type: Optional[str] = None
    error_code: Optional[str] = None
    # V3 行级百分比（current/total 任一缺失视为不展示百分比）
    current: Optional[int] = None
    total: Optional[int] = None


class LogEvent(BaseModel):
    type: Literal["log"]
    level: LogLevel
    message: str
    module: str = ""
    ts: float


class StatusEvent(BaseModel):
    type: Literal["status"]
    status: TaskStatus
    error: Optional[str] = None
    cancel_requested: Optional[bool] = None
    ts: float


class HeartbeatEvent(BaseModel):
    type: Literal["heartbeat"]
    ts: float


class ProgressEvent(BaseModel):
    """任务级总进度。current/total 按词数计算；phase 标记当前阶段。"""
    type: Literal["progress"]
    phase: str
    current: int = 0
    total: int = 0
    message: Optional[str] = None
    ts: float


class RowStatusEvent(BaseModel):
    """行级状态批量事件。可一次携带多行（如 AI 批次开始时所有词的 ai_request）。"""
    type: Literal["row_status"]
    rows: list[RowState]
    ts: float


# Discriminated union — Pydantic 按 `type` 字段路由到具体子类
class TaskEvent(RootModel):
    """SSE 任务事件流的统一信封。前端按 `type` 字段做 type narrowing。"""
    root: Annotated[
        Union[LogEvent, StatusEvent, HeartbeatEvent, ProgressEvent, RowStatusEvent],
        Field(discriminator="type"),
    ]


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


class WordsListResponse(BaseModel):
    total: int = 0
    page: int = 1
    page_size: int = 50
    items: list[WordNoteSummary] = Field(default_factory=list)


class WordIteration(BaseModel):
    voc_id: str
    iteration_type: str
    score: float = 0.0
    justification: str = ""
    tags: str = ""
    refined_content: str = ""
    raw_response: str = ""
    created_at: str = ""


class WordIterationsResponse(BaseModel):
    voc_id: str
    iterations: list[WordIteration] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /api/stats/summary
# ---------------------------------------------------------------------------
class StatsSummary(BaseModel):
    total_words: int = 0
    processed_words: int = 0
    ai_batches: int = 0
    ai_notes_count: int = 0
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


class SyncConflict(BaseModel):
    voc_id: str
    spelling: str = ""
    basic_meanings: str = ""
    sync_status: int = 0
    created_at: str = ""


class SyncStatusResponse(BaseModel):
    queue_depth: int = 0
    conflict_count: int = 0
    conflicts: list[SyncConflict] = Field(default_factory=list)


class SyncFlushResponse(BaseModel):
    flushed: bool = True


class SyncRetryResponse(BaseModel):
    retried: int = 0
    total_conflicts: Optional[int] = None
    message: Optional[str] = None


# ---------------------------------------------------------------------------
# /api/users
# ---------------------------------------------------------------------------
class UserProfile(BaseModel):
    username: str
    ai_provider: str = ""
    has_momo_token: bool = False
    has_ai_key: bool = False
    is_active: bool = False


class UsersListResponse(BaseModel):
    users: list[UserProfile] = Field(default_factory=list)
    active_profile: str


class ProfileCreateRequest(BaseModel):
    profile_name: str


class ProfileCreateResponse(BaseModel):
    profile_name: str
    profile_path: str
    message: str


class ValidateRequest(BaseModel):
    field: str
    value: str


class ValidateResponse(BaseModel):
    field: str
    valid: bool
    message: str


class WizardCreateRequest(BaseModel):
    username: str
    momo_token: str
    ai_provider: str
    ai_api_key: str
    user_email: Optional[str] = None


class ProfileConfigUpdateRequest(BaseModel):
    momo_token: Optional[str] = None
    ai_provider: Optional[str] = None
    ai_api_key: Optional[str] = None
    user_email: Optional[str] = None


class WizardValidationResult(BaseModel):
    ok: bool
    category: Optional[str] = None
    detail: Optional[str] = None


class WizardCreateResponse(BaseModel):
    username: str
    profile_path: str
    cloud_configured: bool = False
    validation: dict[str, WizardValidationResult] = Field(default_factory=dict)
    message: str


# ---------------------------------------------------------------------------
# /api/preflight
# ---------------------------------------------------------------------------
class PreflightItem(BaseModel):
    name: str
    status: str  # "ok" | "fail" | "warn"
    detail: str = ""
    fix_hint: str = ""


class PreflightCheck(BaseModel):
    name: str
    ok: bool
    status: str
    blocking: bool
    category: str
    detail: str
    fix_hint: str


class PreflightResponse(BaseModel):
    username: str
    root_dir: str
    profile_path: str
    force_cloud_mode: bool
    ok: bool
    checks: list[PreflightCheck] = Field(default_factory=list)
    blocking_items: list[PreflightCheck] = Field(default_factory=list)
