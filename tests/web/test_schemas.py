"""
tests/web/test_schemas.py -- Pydantic model + ok_response/error_response tests.
"""
from __future__ import annotations
import pytest
from web.backend.schemas import (
    ApiError, ApiResponse, FutureItemsResponse, HealthInfo, PreflightCheck,
    PreflightResponse, SessionInfo, StatsSummary, SyncConflict, SyncFlushResponse,
    SyncRetryResponse, SyncStatusItem, SyncStatusResponse, TaskCancelResponse,
    TaskStatusResponse, TodayItem, TodayItemsResponse, UserProfile, UsersListResponse,
    ValidateRequest, ValidateResponse, WizardCreateRequest, WizardCreateResponse,
    WordIterationsResponse, WordNoteDetail, WordNoteSummary, WordsListResponse,
    error_response, ok_response,
)


class TestOkResponse:
    def test_basic(self):
        r = ok_response({"k": "v"})
        assert r["ok"] is True
        assert r["data"] == {"k": "v"}
        assert r["error"] is None
    def test_with_user_id(self):
        r = ok_response("h", user_id="a")
        assert r["user_id"] == "a"
    def test_none_data(self):
        r = ok_response()
        assert r["data"] is None


class TestErrorResponse:
    def test_basic(self):
        r = error_response("NOT_FOUND", "msg")
        assert r["ok"] is False
        assert r["error"]["code"] == "NOT_FOUND"
    def test_with_user_id(self):
        r = error_response("E", "m", user_id="b")
        assert r["user_id"] == "b"


class TestSchemas:
    def test_health_info(self):
        assert HealthInfo().model_dump()["status"] == "ok"
    def test_session_info(self):
        s = SessionInfo(active_user="t", ai_provider="g", batch_size=10, dry_run=False, db_path="/d")
        assert s.model_dump()["active_user"] == "t"
    def test_today_items(self):
        r = TodayItemsResponse(count=2, items=[TodayItem(voc_id="v1", voc_spelling="w")])
        assert r.model_dump()["count"] == 2
    def test_future_items(self):
        r = FutureItemsResponse(days=14, count=0)
        assert r.model_dump()["days"] == 14
    def test_task_status(self):
        r = TaskStatusResponse(task_id="t1", status="done")
        assert r.model_dump()["task_id"] == "t1"
    def test_task_cancel(self):
        assert TaskCancelResponse().model_dump()["canceled"] is True
    def test_words_list(self):
        r = WordsListResponse(total=100, items=[WordNoteSummary(voc_id="v1")])
        assert r.model_dump()["total"] == 100
    def test_word_detail(self):
        r = WordNoteDetail(voc_id="v1", spelling="t", basic_meanings="m")
        assert r.model_dump()["spelling"] == "t"
    def test_word_iterations(self):
        r = WordIterationsResponse(voc_id="v1", iterations=[])
        assert r.model_dump()["iterations"] == []
    def test_stats_summary(self):
        r = StatsSummary(total_words=50)
        assert r.model_dump()["total_words"] == 50
    def test_sync_status(self):
        r = SyncStatusResponse(queue_depth=3, conflicts=[SyncConflict(voc_id="v1", sync_status=2)])
        assert r.model_dump()["queue_depth"] == 3
    def test_sync_flush(self):
        assert SyncFlushResponse().model_dump()["flushed"] is True
    def test_sync_retry(self):
        r = SyncRetryResponse(retried=5)
        assert r.model_dump()["retried"] == 5
    def test_users_list(self):
        r = UsersListResponse(users=[UserProfile(username="a")], active_user="a")
        assert len(r.model_dump()["users"]) == 1
    def test_validate_req(self):
        r = ValidateRequest(field="f", value="v")
        assert r.model_dump()["field"] == "f"
    def test_validate_resp(self):
        r = ValidateResponse(field="f", valid=True, message="ok")
        assert r.model_dump()["valid"] is True
    def test_wizard_req(self):
        r = WizardCreateRequest(username="t", momo_token="tok", ai_provider="g", ai_api_key="k")
        assert r.model_dump()["username"] == "t"
    def test_wizard_resp(self):
        r = WizardCreateResponse(username="t", profile_path="/p", message="ok")
        assert r.model_dump()["username"] == "t"
    def test_preflight_check(self):
        c = PreflightCheck(name="c", ok=True, status="ok", blocking=False, category="c", detail="d", fix_hint="")
        assert c.model_dump()["name"] == "c"
    def test_preflight_response(self):
        r = PreflightResponse(username="t", root_dir="/r", profile_path="/p", force_cloud_mode=False, ok=True)
        assert r.model_dump()["ok"] is True
    def test_api_error(self):
        assert ApiError(code="E", message="m").model_dump()["code"] == "E"
    def test_api_response(self):
        r = ApiResponse(ok=True, data="h")
        assert r.model_dump()["ok"] is True
    def test_sync_status_item(self):
        assert SyncStatusItem(voc_id="v1", sync_status=0).model_dump()["voc_id"] == "v1"
    def test_task_run_response(self):
        from web.backend.schemas import TaskRunResponse
        r = TaskRunResponse(task_id="t1", word_count=10)
        assert r.model_dump()["word_count"] == 10
