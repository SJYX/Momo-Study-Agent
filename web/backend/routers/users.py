"""
web/backend/routers/users.py: 用户管理端点。

GET  /api/users              — 本机 profile 列表
PUT  /api/users/active       — 切换当前活跃用户
POST /api/users/wizard       — 创建新用户（单页表单一次提交）
POST /api/users/validate     — 验证配置项
DELETE /api/users/{username}  — 删除本地 profile
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Path

from web.backend.deps import get_active_user
from web.backend.router_helpers import catch_api_errors
from web.backend.schemas import (
    AIConfigRequest,
    AIConfigResponse,
    AIModelInfo,
    AIModelsResponse,
    AITestRequest,
    AITestResponse,
    ApiResponse,
    ProfileCreateRequest,
    ProfileCreateResponse,
    ProfileConfigUpdateRequest,
    UsersListResponse,
    ValidateRequest,
    ValidateResponse,
    WizardCreateRequest,
    WizardCreateResponse,
    error_response,
    ok_response,
)

router = APIRouter(prefix="/api/users", tags=["users"])


# ---------------------------------------------------------------------------
# helpers — profile .env 读写
# ---------------------------------------------------------------------------
def _resolve_profile_path(username: str):
    """解析用户 profile .env 路径。"""
    from config import PROFILES_DIR

    normalized = username.lower()
    path = os.path.join(PROFILES_DIR, f"{normalized}.env")
    if os.path.exists(path):
        return path
    for entry in os.listdir(PROFILES_DIR) if os.path.isdir(PROFILES_DIR) else []:
        if entry.lower() == f"{normalized}.env":
            return os.path.join(PROFILES_DIR, entry)
    return None


def _update_profile_env(profile_path: str, updates: dict):
    """更新 profile .env 文件中的键值对。"""
    lines = []
    if os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    keys_written = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                keys_written.add(key)
                continue
        # 兼容历史文件末尾缺少换行的情况，避免后续追加键值时发生粘行。
        if line.endswith("\n"):
            new_lines.append(line)
        else:
            new_lines.append(line + "\n")

    for key, value in updates.items():
        if key not in keys_written:
            new_lines.append(f"{key}={value}\n")

    with open(profile_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


@router.get("", response_model=ApiResponse[UsersListResponse])
async def list_users(user: str = Depends(get_active_user)):
    """列出本机所有 profile 用户。"""
    from config import PROFILES_DIR
    from core.profile_manager import ProfileManager

    print(f"[Web][users] list_users called by profile={user}")
    pm = ProfileManager(PROFILES_DIR)
    profiles = pm.list_profiles()

    # 为每个用户检查配置状态
    result = []
    for username in profiles:
        profile_path = os.path.join(PROFILES_DIR, f"{username}.env")
        has_momo = False
        has_ai = False
        ai_provider = ""

        if os.path.exists(profile_path):
            env_data = {}
            with open(profile_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_data[k.strip()] = v.strip().strip('"').strip("'")

            has_momo = bool(env_data.get("MOMO_TOKEN"))
            ai_provider = env_data.get("AI_PROVIDER", "")
            # Unified field wins (AIConfigCard writes only AI_API_KEY); legacy
            # provider-keyed fields cover wizard-created profiles.
            has_ai = bool(env_data.get("AI_API_KEY"))
            if not has_ai:
                if ai_provider == "mimo":
                    has_ai = bool(env_data.get("MIMO_API_KEY"))
                elif ai_provider == "gemini":
                    has_ai = bool(env_data.get("GEMINI_API_KEY"))

        result.append({
            "username": username,
            "ai_provider": ai_provider,
            "has_momo_token": has_momo,
            "has_ai_key": has_ai,
            "is_active": username == user,
        })

    return ok_response({"users": result, "active_profile": user}, user_id=user)


@router.put("/active", response_model=ApiResponse[dict])
async def switch_active_user(
    username: str,
    user: str = Depends(get_active_user),
):
    """预热目标 profile 的上下文（PUT /api/users/active?username=xxx）。

    前端已通过 X-Momo-Profile header 实现请求级 profile 解析，
    此端点仅做校验 + 预创建 context，避免首次请求延迟。
    """
    import config as _cfg

    # 校验目标用户存在
    profile_path = os.path.join(_cfg.PROFILES_DIR, f"{username.lower()}.env")
    if not os.path.exists(profile_path):
        return error_response("NOT_FOUND", f"用户 '{username}' 不存在", user_id=user)

    import web.backend.deps as _deps

    warmup_state = "not_started"
    try:
        if _deps._context_manager:
            ctx = _deps._context_manager.get(username.lower())
            # get() 已同步执行 DB 初始化（init_db + init_db_session_resources）。
            # ensure_profile_ready 是 no-op（warmup 已在 get 中启动）。
            _deps._context_manager.ensure_profile_ready(ctx)
            warmup_state = _deps._context_manager.get_warmup_state(username.lower())
    except Exception as e:
        return error_response("CONTEXT_ERROR", f"初始化用户上下文失败: {e}", user_id=user)

    warmup_state = "not_started"
    if _deps._context_manager:
        warmup_state = _deps._context_manager.get_warmup_state(username.lower())

    return ok_response({
        "active_profile": username.lower(),
        "warmup_state": warmup_state,
        "message": f"已切换到用户 '{username}'",
    }, user_id=username.lower())


@router.post("", response_model=ApiResponse[ProfileCreateResponse])
async def create_profile_minimal(body: ProfileCreateRequest, user: str = Depends(get_active_user)):
    """创建最小 profile（仅 profile_name 必填）。"""
    from config import PROFILES_DIR
    from core.config_wizard import ConfigWizard

    profile_name = (body.profile_name or "").strip().lower()
    if not profile_name:
        return error_response("INVALID_INPUT", "profile_name 不能为空", user_id=user)

    profile_path = os.path.join(PROFILES_DIR, f"{profile_name}.env")
    if os.path.exists(profile_path):
        return error_response("USER_EXISTS", f"用户 '{profile_name}' 已存在", user_id=user)

    os.makedirs(PROFILES_DIR, exist_ok=True)
    with open(profile_path, "w", encoding="utf-8") as f:
        f.write(f'USER_EMAIL="{profile_name}@momo-local"\n')

    try:
        wizard = ConfigWizard(PROFILES_DIR)
        wizard._init_local_db(profile_name)
    except Exception as e:
        return error_response("DB_INIT_ERROR", f"用户已创建但本地数据库初始化失败: {e}", user_id=user)

    return ok_response(
        {
            "profile_name": profile_name,
            "profile_path": profile_path,
            "message": f"用户 '{profile_name}' 创建成功",
        },
        user_id=user,
    )


@router.post("/validate", response_model=ApiResponse[ValidateResponse])
async def validate_config(body: ValidateRequest, user: str = Depends(get_active_user)):
    """验证配置项（墨墨 Token / AI Key 等），返回校验结果。

    body: {"field": "momo_token"|"mimo_api_key"|"gemini_api_key", "value": "..."}
    """
    field = body.field
    value = body.value

    if not field or not value:
        return error_response("INVALID_INPUT", "field 和 value 不能为空", user_id=user)

    try:
        if field == "momo_token":
            from core.maimemo_api import MaiMemoAPI
            test_api = MaiMemoAPI(value)
            res = test_api.get_today_items(limit=1)
            ok = res is not None and res.get("data") is not None
            if hasattr(test_api, "close"):
                test_api.close()
            return ok_response({"field": field, "valid": ok, "message": "连接成功" if ok else "Token 无效"}, user_id=user)

        elif field == "mimo_api_key":
            from core.litellm_client import LiteLLMClient
            from core.litellm_presets import get_default_base_url
            client = LiteLLMClient(model="openai/mimo-v2-flash", api_key=value, base_url=get_default_base_url("mimo"))
            text, _ = client.generate_with_instruction("test", instruction="回复 OK")
            ok = bool(text)
            client.close()
            return ok_response({"field": field, "valid": ok, "message": "Key 有效" if ok else "Key 无效"}, user_id=user)

        elif field == "gemini_api_key":
            from core.litellm_client import LiteLLMClient
            client = LiteLLMClient(model="gemini/gemini-2.0-flash", api_key=value)
            text, _ = client.generate_with_instruction("test", instruction="回复 OK")
            ok = bool(text)
            client.close()
            return ok_response({"field": field, "valid": ok, "message": "Key 有效" if ok else "Key 无效"}, user_id=user)

        else:
            return error_response("UNKNOWN_FIELD", f"不支持的字段: {field}", user_id=user)

    except Exception as e:
        return ok_response({"field": field, "valid": False, "message": str(e)[:200]}, user_id=user)


@router.post("/wizard", response_model=ApiResponse[WizardCreateResponse])
async def wizard_create(body: WizardCreateRequest, user: str = Depends(get_active_user)):
    """单页表单一次提交创建新用户 profile。

    body: {
        "username": "xxx",
        "momo_token": "...",
        "ai_provider": "mimo"|"gemini"|"",
        "ai_api_key": "...",
        "user_email": "..."   // optional
    }
    """
    from config import PROFILES_DIR
    from core.config_wizard import ConfigWizard

    username = (body.username or "").strip().lower()
    momo_token = body.momo_token
    ai_provider = body.ai_provider
    ai_api_key = body.ai_api_key
    user_email = body.user_email or f"{username}@momo-local"

    if not username:
        return error_response("INVALID_INPUT", "用户名不能为空", user_id=user)

    # 检查用户名是否已存在
    profile_path = os.path.join(PROFILES_DIR, f"{username}.env")
    if os.path.exists(profile_path):
        return error_response("USER_EXISTS", f"用户 '{username}' 已存在", user_id=user)

    # 构造 env 内容（统一变量为主，保留 legacy 字段以便老脚本继续工作）
    env_lines = [
        f'MOMO_TOKEN="{momo_token}"',
        f'AI_PROVIDER="{ai_provider}"',
    ]
    if ai_api_key:
        env_lines.append(f'AI_API_KEY="{ai_api_key}"')
    if ai_provider == "mimo":
        env_lines.append(f'MIMO_API_KEY="{ai_api_key}"')
    elif ai_provider == "gemini":
        env_lines.append(f'GEMINI_API_KEY="{ai_api_key}"')

    # 尝试云端数据库配置
    wizard = ConfigWizard(PROFILES_DIR)
    mgmt_token = os.getenv("TURSO_MGMT_TOKEN")
    org_slug = os.getenv("TURSO_ORG_SLUG")
    group = os.getenv("TURSO_GROUP") or "123"

    cloud_configured = False
    if mgmt_token and org_slug:
        try:
            db_name = f"history-{username}"
            database = wizard._create_turso_database(org_slug, db_name, mgmt_token, group)
            hostname = database.get("Hostname") or database.get("hostname") or ""
            db_url = wizard._normalize_turso_db_url(hostname)
            db_auth_token = wizard._generate_db_auth_token(org_slug, mgmt_token, db_name) or mgmt_token
            env_lines.extend([
                f'TURSO_DB_NAME="{db_name}"',
                f'TURSO_DB_HOSTNAME="{hostname}"',
                f'TURSO_DB_URL="{db_url}"',
                f'TURSO_AUTH_TOKEN="{db_auth_token}"',
            ])
            cloud_configured = True
        except Exception:
            pass  # 云端配置失败，回退本地模式

    env_lines.append(f'USER_EMAIL="{user_email}"')

    # 写入 profile 文件
    os.makedirs(PROFILES_DIR, exist_ok=True)
    with open(profile_path, "w", encoding="utf-8") as f:
        f.write("\n".join(env_lines) + "\n")

    # 初始化本地数据库
    try:
        wizard._init_local_db(username)
    except Exception as e:
        return error_response("DB_INIT_ERROR", f"用户已创建但本地数据库初始化失败: {e}", user_id=user)

    # 验证结果
    validation_results = {}
    if momo_token:
        vr = wizard.validate_momo(momo_token)
        validation_results["momo_token"] = vr
    if ai_provider and ai_api_key:
        if ai_provider == "mimo":
            vr = wizard.validate_mimo(ai_api_key)
        else:
            vr = wizard.validate_gemini(ai_api_key)
        validation_results[f"{ai_provider}_api_key"] = vr

    return ok_response({
        "username": username,
        "profile_path": profile_path,
        "cloud_configured": cloud_configured,
        "validation": validation_results,
        "message": f"用户 '{username}' 创建成功",
    }, user_id=user)


@router.put("/{username}/config", response_model=ApiResponse[dict])
async def update_profile_config(
    body: ProfileConfigUpdateRequest,
    username: str = Path(...),
    user: str = Depends(get_active_user),
):
    """更新已有 profile 的配置项（不重新创建 profile）。

    只更新请求中提供的非 null 字段。
    """
    from config import PROFILES_DIR

    username = username.strip().lower()
    profile_path = os.path.join(PROFILES_DIR, f"{username}.env")

    if not os.path.exists(profile_path):
        return error_response("NOT_FOUND", f"用户 '{username}' 不存在", user_id=user)

    # 读取现有配置
    env_data: dict[str, str] = {}
    with open(profile_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env_data[k.strip()] = v.strip().strip('"').strip("'")

    # 合并更新
    if body.momo_token is not None:
        env_data["MOMO_TOKEN"] = body.momo_token
    if body.ai_provider is not None:
        env_data["AI_PROVIDER"] = body.ai_provider
    if body.ai_api_key is not None:
        provider = body.ai_provider or env_data.get("AI_PROVIDER", "")
        # Unified field is authoritative — Web user_context reads only this.
        env_data["AI_API_KEY"] = body.ai_api_key
        # Mirror to the legacy slot so CLI/preflight paths that still consult
        # the provider-keyed env keep agreeing with the unified one.
        if provider == "mimo":
            env_data["MIMO_API_KEY"] = body.ai_api_key
            env_data.pop("GEMINI_API_KEY", None)
        elif provider == "gemini":
            env_data["GEMINI_API_KEY"] = body.ai_api_key
            env_data.pop("MIMO_API_KEY", None)
        else:
            # Drop both legacy slots so they don't shadow AI_API_KEY for the
            # new provider.
            env_data.pop("MIMO_API_KEY", None)
            env_data.pop("GEMINI_API_KEY", None)
    if body.user_email is not None:
        env_data["USER_EMAIL"] = body.user_email

    # 写回
    env_lines = [f'{k}="{v}"' for k, v in env_data.items()]
    with open(profile_path, "w", encoding="utf-8") as f:
        f.write("\n".join(env_lines) + "\n")

    # 清理该 profile 的 context 缓存（下次请求时会重新加载新配置）
    import web.backend.deps as _deps
    if _deps._context_manager:
        _deps._context_manager.cleanup(username)

    return ok_response({
        "username": username,
        "message": f"用户 '{username}' 配置已更新",
    }, user_id=user)


@router.delete("/{username}")
@catch_api_errors("DELETE_ERROR")
async def delete_user(
    username: str = Path(...),
    user: str = Depends(get_active_user),
):
    """删除本地 profile（不能删除当前活跃用户）。"""
    from config import PROFILES_DIR
    from core.profile_manager import ProfileManager

    if username == user:
        return error_response("CANNOT_DELETE_ACTIVE", "不能删除当前活跃用户", user_id=user)

    pm = ProfileManager(PROFILES_DIR)
    try:
        pm.delete_local_profile(username)
    except FileNotFoundError:
        return error_response("NOT_FOUND", f"用户 '{username}' 不存在", user_id=user)
    return ok_response({"deleted": username}, user_id=user)


# ---------------------------------------------------------------------------
# /api/users/{username}/ai-models  — 供应商 & 预设模型列表
# ---------------------------------------------------------------------------
@router.get("/{username}/ai-models", response_model=ApiResponse[AIModelsResponse])
async def get_ai_models(
    username: str = Path(...),
    user: str = Depends(get_active_user),
):
    """获取所有供应商及其预设模型列表。"""
    from core.litellm_presets import PROVIDERS

    providers = [AIModelInfo(**p) for p in PROVIDERS]
    return ok_response(AIModelsResponse(providers=providers).model_dump(), user_id=user)


# ---------------------------------------------------------------------------
# /api/users/{username}/ai-config  — 保存 AI 配置到 profile .env
# ---------------------------------------------------------------------------
@router.post("/{username}/ai-config", response_model=ApiResponse[AIConfigResponse])
async def save_ai_config(
    body: AIConfigRequest,
    username: str = Path(...),
    user: str = Depends(get_active_user),
):
    """保存 AI 配置到 profile .env。"""
    profile_path = _resolve_profile_path(username)
    if not profile_path:
        return error_response("NOT_FOUND", f"Profile '{username}' not found", user_id=user)

    env_updates = {
        "AI_PROVIDER": body.provider,
        "AI_API_KEY": body.api_key,
        "AI_MODEL": body.model,
    }
    if body.base_url:
        env_updates["AI_BASE_URL"] = body.base_url
    else:
        env_updates["AI_BASE_URL"] = ""

    _update_profile_env(profile_path, env_updates)

    from config import ACTIVE_USER

    if ACTIVE_USER == username.lower():
        from config import switch_user

        switch_user(username)

    # 失效缓存的 UserContext：缓存里的 ai_client 还持有旧 api_key，
    # 不 cleanup 会让下一次 study/today 任务用过期凭据。
    try:
        import web.backend.deps as _deps
        if _deps._context_manager is not None:
            _deps._context_manager.cleanup(username.lower())
    except Exception:
        pass

    return ok_response(
        AIConfigResponse(
            provider=body.provider,
            model=body.model,
            has_api_key=True,
            base_url=body.base_url,
        ).model_dump(),
        user_id=user,
    )


# ---------------------------------------------------------------------------
# /api/users/{username}/ai-test  — 测试 AI 连接
# ---------------------------------------------------------------------------
@router.post("/{username}/ai-test", response_model=ApiResponse[AITestResponse])
async def test_ai_connection(
    body: AITestRequest,
    username: str = Path(...),
    user: str = Depends(get_active_user),
):
    """测试 AI 连接。"""
    import time

    from core.litellm_client import LiteLLMClient

    model = body.model
    if "/" not in model:
        from core.litellm_presets import get_provider_prefix

        prefix = get_provider_prefix(body.provider)
        model = f"{prefix}{model}"

    client = LiteLLMClient(model=model, api_key=body.api_key, base_url=body.base_url)
    try:
        started = time.time()
        text, metadata = client.generate_with_instruction(
            "Say 'hello' in one word.",
            instruction="Reply with exactly one word, nothing else.",
        )
        latency_ms = (time.time() - started) * 1000

        if text:
            return ok_response(
                AITestResponse(ok=True, message="连接成功", latency_ms=latency_ms).model_dump(),
                user_id=user,
            )
        else:
            error_msg = metadata.get("error", "未知错误")
            return ok_response(
                AITestResponse(ok=False, message=f"连接失败: {error_msg}").model_dump(),
                user_id=user,
            )
    except Exception as e:
        return ok_response(
            AITestResponse(ok=False, message=f"连接失败: {str(e)}").model_dump(),
            user_id=user,
        )
