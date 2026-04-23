"""
web/backend/routers/users.py: 用户管理端点。

GET  /api/users              — 本机 profile 列表
POST /api/users/wizard       — 创建新用户（单页表单一次提交）
POST /api/users/validate     — 验证配置项
DELETE /api/users/{username}  — 删除本地 profile
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Path

from web.backend.deps import get_active_user
from web.backend.schemas import ok_response, error_response

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
async def list_users(user: str = Depends(get_active_user)):
    """列出本机所有 profile 用户。"""
    from config import PROFILES_DIR
    from core.profile_manager import ProfileManager

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

    return ok_response({"users": result, "active_user": user}, user_id=user)


@router.post("/validate")
async def validate_config(body: dict, user: str = Depends(get_active_user)):
    """验证配置项（墨墨 Token / AI Key 等），返回校验结果。

    body: {"field": "momo_token"|"mimo_api_key"|"gemini_api_key", "value": "..."}
    """
    field = body.get("field", "")
    value = body.get("value", "")

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
            from core.mimo_client import MimoClient
            client = MimoClient(api_key=value)
            text, _ = client.generate_with_instruction("test", instruction="回复 OK")
            ok = bool(text)
            client.close()
            return ok_response({"field": field, "valid": ok, "message": "Key 有效" if ok else "Key 无效"}, user_id=user)

        elif field == "gemini_api_key":
            from core.gemini_client import GeminiClient
            client = GeminiClient(api_key=value)
            text, _ = client.generate_with_instruction("test", instruction="回复 OK")
            ok = bool(text)
            client.close()
            return ok_response({"field": field, "valid": ok, "message": "Key 有效" if ok else "Key 无效"}, user_id=user)

        else:
            return error_response("UNKNOWN_FIELD", f"不支持的字段: {field}", user_id=user)

    except Exception as e:
        return ok_response({"field": field, "valid": False, "message": str(e)[:200]}, user_id=user)


@router.post("/wizard")
async def wizard_create(body: dict, user: str = Depends(get_active_user)):
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

    username = (body.get("username") or "").strip().lower()
    momo_token = body.get("momo_token", "")
    ai_provider = body.get("ai_provider", "")
    ai_api_key = body.get("ai_api_key", "")
    user_email = body.get("user_email", "") or f"{username}@momo-local"

    if not username:
        return error_response("INVALID_INPUT", "用户名不能为空", user_id=user)

    # 检查用户名是否已存在
    profile_path = os.path.join(PROFILES_DIR, f"{username}.env")
    if os.path.exists(profile_path):
        return error_response("USER_EXISTS", f"用户 '{username}' 已存在", user_id=user)

    # 构造 env 内容
    env_lines = [
        f'MOMO_TOKEN="{momo_token}"',
        f'AI_PROVIDER="{ai_provider}"',
    ]
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


@router.delete("/{username}")
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
        return ok_response({"deleted": username}, user_id=user)
    except FileNotFoundError:
        return error_response("NOT_FOUND", f"用户 '{username}' 不存在", user_id=user)
    except Exception as e:
        return error_response("DELETE_ERROR", str(e), user_id=user)
