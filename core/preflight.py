import os
from typing import Dict, List


def _read_env_file(path: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not os.path.exists(path):
        return result

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _is_truthy(raw: str) -> bool:
    return str(raw or "").strip().lower() in ("1", "true", "yes", "y", "on")


def run_preflight(root_dir: str, username: str) -> Dict:
    profiles_dir = os.path.join(root_dir, "data", "profiles")
    global_env_path = os.path.join(root_dir, ".env")
    profile_path = os.path.join(profiles_dir, f"{username}.env")

    global_env = _read_env_file(global_env_path)
    profile_env = _read_env_file(profile_path)

    force_cloud_mode = _is_truthy(global_env.get("FORCE_CLOUD_MODE", "False"))

    checks: List[Dict] = []

    def add_check(name: str, ok: bool, blocking: bool, detail: str, fix_hint: str) -> None:
        checks.append(
            {
                "name": name,
                "ok": ok,
                "status": "ok" if ok else "missing",
                "blocking": bool(blocking and not ok),
                "category": "config" if not ok else "ready",
                "detail": detail,
                "fix_hint": fix_hint,
            }
        )

    profile_exists = os.path.exists(profile_path)
    add_check(
        "profile",
        profile_exists,
        True,
        f"用户配置文件: {'存在' if profile_exists else '不存在'} ({profile_path})",
        f"先运行主程序创建用户: python main.py (目标用户: {username})",
    )

    momo_token = profile_env.get("MOMO_TOKEN", "")
    add_check(
        "momo_token",
        bool(momo_token),
        True,
        "MOMO_TOKEN 已配置" if momo_token else "MOMO_TOKEN 缺失",
        f"在 {profile_path} 中配置 MOMO_TOKEN，或重新运行向导。",
    )

    provider = profile_env.get("AI_PROVIDER", "").lower().strip()
    provider_ok = provider in ("mimo", "gemini")
    add_check(
        "ai_provider",
        provider_ok,
        True,
        f"AI_PROVIDER={provider}" if provider else "AI_PROVIDER 缺失",
        "设置 AI_PROVIDER 为 mimo 或 gemini。",
    )

    mimo_key = profile_env.get("MIMO_API_KEY", "")
    gemini_key = profile_env.get("GEMINI_API_KEY", "")

    ai_key_ok = (provider == "mimo" and bool(mimo_key)) or (provider == "gemini" and bool(gemini_key))
    add_check(
        "ai_key",
        ai_key_ok,
        True,
        "AI Key 已配置" if ai_key_ok else "当前 provider 对应的 API Key 缺失",
        "为当前 AI_PROVIDER 配置对应 API Key。",
    )

    turso_user_ok = bool(profile_env.get("TURSO_DB_URL") and profile_env.get("TURSO_AUTH_TOKEN"))
    add_check(
        "turso_user_db",
        turso_user_ok,
        force_cloud_mode,
        "用户 Turso 数据库配置完整" if turso_user_ok else "用户 Turso 数据库配置不完整",
        "若使用云端，请补全 TURSO_DB_URL 与 TURSO_AUTH_TOKEN；本地模式可暂不配置。",
    )

    hub_ok = bool(global_env.get("TURSO_HUB_DB_URL") and global_env.get("TURSO_HUB_AUTH_TOKEN"))
    add_check(
        "hub_config",
        hub_ok,
        force_cloud_mode,
        "Hub 配置完整" if hub_ok else "Hub 配置缺失",
        "在全局 .env 中补全 TURSO_HUB_DB_URL 与 TURSO_HUB_AUTH_TOKEN。",
    )

    cloud_conflict = force_cloud_mode and (not hub_ok or not turso_user_ok)
    add_check(
        "force_cloud_conflict",
        not cloud_conflict,
        force_cloud_mode,
        "FORCE_CLOUD_MODE 与当前配置一致"
        if not cloud_conflict
        else "FORCE_CLOUD_MODE=True 但 Hub/用户云库配置缺失",
        "补全云端配置，或将全局 .env 的 FORCE_CLOUD_MODE 改为 False。",
    )

    blocking_items = [item for item in checks if item.get("blocking")]

    return {
        "username": username,
        "root_dir": root_dir,
        "profile_path": profile_path,
        "force_cloud_mode": force_cloud_mode,
        "ok": len(blocking_items) == 0,
        "checks": checks,
        "blocking_items": blocking_items,
    }
