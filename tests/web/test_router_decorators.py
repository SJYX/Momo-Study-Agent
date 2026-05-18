"""tests/web/test_router_decorators.py: @catch_api_errors 行为单元测试。

注：项目未配 pytest-asyncio；async 用例改用 asyncio.run() 包裹直接调用，
不依赖 pytest 异步插件。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from web.backend.router_helpers import catch_api_errors
from web.backend.schemas import error_response, ok_response


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 异步路径
# ---------------------------------------------------------------------------

def test_async_passes_through_success_response():
    @catch_api_errors("DEFAULT_ERR")
    async def endpoint():
        return ok_response({"x": 1}, user_id="alice")

    result = _run(endpoint())
    assert result["ok"] is True
    assert result["data"] == {"x": 1}
    assert result["user_id"] == "alice"


def test_async_converts_unexpected_exception_to_error_response():
    @catch_api_errors("MAIMO_API_ERROR")
    async def endpoint(user: str = "alice"):
        raise RuntimeError("boom")

    result = _run(endpoint(user="alice"))
    assert result["ok"] is False
    assert result["error"]["code"] == "MAIMO_API_ERROR"
    assert "boom" in result["error"]["message"]
    assert result["user_id"] == "alice"


def test_async_does_not_swallow_http_exception():
    @catch_api_errors("DEFAULT_ERR")
    async def endpoint():
        raise HTTPException(status_code=409, detail="conflict")

    with pytest.raises(HTTPException) as exc_info:
        _run(endpoint())
    assert exc_info.value.status_code == 409


def test_async_does_not_intercept_explicit_error_response():
    """业务层主动 return 的 error_response 应原样透出，装饰器不动。"""
    @catch_api_errors("WOULD_BE_OVERRIDDEN")
    async def endpoint():
        return error_response("INVALID_INPUT", "bad arg", user_id="bob")

    result = _run(endpoint())
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_INPUT"  # 不是 WOULD_BE_OVERRIDDEN
    assert result["user_id"] == "bob"


def test_async_resolves_user_id_from_user_kwarg():
    @catch_api_errors("X")
    async def endpoint(user: str = ""):
        raise RuntimeError("e")

    result = _run(endpoint(user="charlie"))
    assert result["user_id"] == "charlie"


def test_async_resolves_user_id_from_ctx_profile_name():
    class _Ctx:
        profile_name = "diana"

    @catch_api_errors("X")
    async def endpoint(ctx=None):
        raise RuntimeError("e")

    result = _run(endpoint(ctx=_Ctx()))
    assert result["user_id"] == "diana"


def test_async_user_kwarg_takes_priority_over_ctx():
    class _Ctx:
        profile_name = "from_ctx"

    @catch_api_errors("X")
    async def endpoint(user: str = "", ctx=None):
        raise RuntimeError("e")

    result = _run(endpoint(user="from_user", ctx=_Ctx()))
    assert result["user_id"] == "from_user"


def test_async_falls_back_to_empty_user_id():
    @catch_api_errors("X")
    async def endpoint():
        raise RuntimeError("e")

    result = _run(endpoint())
    assert result["user_id"] == ""


# ---------------------------------------------------------------------------
# 同步路径
# ---------------------------------------------------------------------------

def test_sync_converts_unexpected_exception_to_error_response():
    @catch_api_errors("DB_INIT_ERROR")
    def endpoint(user: str = "alice"):
        raise ValueError("oops")

    result = endpoint(user="alice")
    assert result["ok"] is False
    assert result["error"]["code"] == "DB_INIT_ERROR"
    assert "oops" in result["error"]["message"]


def test_sync_passes_through_success():
    @catch_api_errors("X")
    def endpoint():
        return ok_response("hello")

    assert endpoint() == ok_response("hello")


def test_sync_does_not_swallow_http_exception():
    @catch_api_errors("X")
    def endpoint():
        raise HTTPException(status_code=400, detail="bad")

    with pytest.raises(HTTPException):
        endpoint()


# ---------------------------------------------------------------------------
# functools.wraps 完整性（FastAPI 依赖注入需要看到原签名）
# ---------------------------------------------------------------------------

def test_wraps_preserves_signature_and_name():
    @catch_api_errors("X")
    async def my_endpoint(user: str, ctx=None) -> dict:
        return {}

    assert my_endpoint.__name__ == "my_endpoint"
    sig = list(my_endpoint.__wrapped__.__annotations__)
    assert "user" in sig
