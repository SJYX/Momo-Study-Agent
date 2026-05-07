"""
web/backend/router_helpers.py: FastAPI router 装饰器与公共工具。

提供 @catch_api_errors 装饰器，统一处理 router 中重复的「外层 try/except → error_response」模板。

边界：
- 只接管「未捕获异常」→ 转为 error_response(default_code, str(e))。
- 不吞 HTTPException（FastAPI 自有处理路径）。
- 不影响业务层主动 return 的 error_response（早返回继续走，因为它们不抛异常）。
- 自动从 kwargs 提取 user_id：优先 `user` 字符串参数，回退到 `ctx.profile_name`。
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from fastapi import HTTPException

from web.backend.schemas import error_response


def _resolve_user_id(kwargs: dict[str, Any]) -> str:
    """从 endpoint 的 kwargs 中提取 user_id，给 error_response 使用。

    顺序：
    1. kwargs['user']（来自 Depends(get_active_user)）
    2. kwargs['ctx'].profile_name（来自 Depends(get_user_context)）
    3. 空字符串（不应发生）
    """
    user_val = kwargs.get("user")
    if isinstance(user_val, str) and user_val:
        return user_val

    ctx = kwargs.get("ctx")
    if ctx is not None:
        name = getattr(ctx, "profile_name", None)
        if isinstance(name, str) and name:
            return name

    return ""


def catch_api_errors(default_code: str) -> Callable:
    """装饰 router 端点：未捕获异常自动转 error_response。

    用法::

        @router.get("/today")
        @catch_api_errors("MAIMO_API_ERROR")
        async def get_today(user: str = Depends(get_active_user), ...):
            res = await run_in_threadpool(...)  # 不再需要外层 try/except
            return ok_response(...)

    放行：
    - HTTPException（如 _submit_with_profile_lock 抛 409）→ FastAPI 处理
    - 业务函数主动 return 的 error_response → 早返回不触发装饰器

    保留原函数签名（functools.wraps），FastAPI 的依赖注入正常解析。
    """
    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except HTTPException:
                    raise
                except Exception as e:
                    user_id = _resolve_user_id(kwargs)
                    return error_response(default_code, str(e), user_id=user_id)
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                user_id = _resolve_user_id(kwargs)
                return error_response(default_code, str(e), user_id=user_id)
        return sync_wrapper
    return decorator


__all__ = ["catch_api_errors"]
