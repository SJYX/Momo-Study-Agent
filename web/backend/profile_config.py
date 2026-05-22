"""
web/backend/profile_config.py — 不可变的 profile 级配置快照。

P4-T4 之前 UserContextManager._create_context 通过 `config.switch_user()` 修改
模块级全局变量（MOMO_TOKEN/AI_PROVIDER/DB_PATH/...），完成构造后再 finally 恢复。
那段代码同时承担"按用户加载 .env"和"作为 core 客户端的入参源"两件事，串行化的副作用
还要靠 _lock 序列化。本模块把"加载 .env" 的部分抽离成纯函数 + 不可变 dataclass，
让 _create_context 无需触碰任何全局态。

加载顺序与历史 cfg.switch_user 一致：
  1. 全局 .env (override=False)        — 仅作为兜底
  2. <profile>.env (override=True)     — profile 级覆盖

不修改 os.environ；所有读出的值挂在返回的 ProfileConfig dataclass 上。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import dotenv_values

from core.profile_loader import (
    USER_SCOPED_KEYS,
    normalize_username as _normalize_username,
    resolve_profile_env_path as _resolve_profile_env_path,
    resolve_user_db_paths as _resolve_user_db_paths,
)


@dataclass(frozen=True)
class ProfileConfig:
    """单个 profile 的运行期配置快照。frozen=True 防止下游误改。"""
    profile_name: str
    env_path: str
    # 凭据
    momo_token: str = ""
    ai_provider: str = "mimo"
    gemini_api_key: str = ""
    gemini_model: str = ""
    mimo_api_key: str = ""
    mimo_api_base: str = ""
    mimo_model: str = ""
    # 数据库路径
    db_path: str = ""
    test_db_path: str = ""
    # Turso（个人库；Hub 和 mgmt token 走全局 .env，不在此快照里）
    turso_db_url: str = ""
    turso_auth_token: str = ""
    turso_db_hostname: str = ""
    turso_test_db_url: str = ""
    turso_test_auth_token: str = ""
    turso_test_db_hostname: str = ""


def load_profile_config(profile_name: str) -> ProfileConfig:
    """读 <profile>.env 与全局 .env，返回不可变的 ProfileConfig。

    不修改 os.environ。core 层仍保留 import-time 绑定（AI_PROVIDER / BATCH_SIZE 等
    通过 from config import 拿到，无法热切换）；本模块只覆盖 web 层
    UserContextManager 实际需要的 user-scoped 字段。
    """
    import config as cfg  # 延迟导入避免循环

    base_dir = cfg.BASE_DIR
    data_dir = cfg.DATA_DIR
    profiles_dir = cfg.PROFILES_DIR

    normalized, env_path = _resolve_profile_env_path(profile_name, profiles_dir)
    if not normalized:
        normalized = "default"

    # 先收集全局 .env 作为兜底
    merged: dict[str, str] = {}
    global_env = os.path.join(base_dir, ".env")
    if os.path.exists(global_env):
        merged.update({k: v for k, v in dotenv_values(global_env).items() if v is not None})

    # profile 级覆盖
    if env_path and os.path.exists(env_path):
        for k, v in dotenv_values(env_path).items():
            if v is not None:
                merged[k] = v

    db_path, test_db_path = _resolve_user_db_paths(normalized, data_dir)

    return ProfileConfig(
        profile_name=normalized,
        env_path=env_path or os.path.join(profiles_dir, f"{normalized}.env"),
        momo_token=merged.get("MOMO_TOKEN", "") or "",
        ai_provider=(merged.get("AI_PROVIDER") or "mimo").strip().lower(),
        gemini_api_key=merged.get("GEMINI_API_KEY", "") or "",
        gemini_model=merged.get("GEMINI_MODEL", "") or "",
        mimo_api_key=merged.get("MIMO_API_KEY", "") or "",
        mimo_api_base=merged.get("MIMO_API_BASE", "") or "",
        mimo_model=merged.get("MIMO_MODEL", "") or "",
        db_path=db_path,
        test_db_path=test_db_path,
        turso_db_url=merged.get("TURSO_DB_URL", "") or "",
        turso_auth_token=merged.get("TURSO_AUTH_TOKEN", "") or "",
        turso_db_hostname=merged.get("TURSO_DB_HOSTNAME", "") or "",
        turso_test_db_url=merged.get("TURSO_TEST_DB_URL", "") or "",
        turso_test_auth_token=merged.get("TURSO_TEST_AUTH_TOKEN", "") or "",
        turso_test_db_hostname=merged.get("TURSO_TEST_DB_HOSTNAME", "") or "",
    )
