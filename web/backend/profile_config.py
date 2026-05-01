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
from typing import Optional

from dotenv import dotenv_values


# 从 config.py 复用的 user-scoped 字段集合
USER_SCOPED_KEYS = (
    "MOMO_TOKEN",
    "AI_PROVIDER",
    "MIMO_API_KEY",
    "GEMINI_API_KEY",
    "TURSO_DB_URL",
    "TURSO_AUTH_TOKEN",
    "TURSO_DB_HOSTNAME",
    "TURSO_TEST_DB_URL",
    "TURSO_TEST_AUTH_TOKEN",
    "TURSO_TEST_DB_HOSTNAME",
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
    mimo_api_key: str = ""
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


def _normalize_username(name: str) -> str:
    return (name or "").strip().lower()


def _resolve_profile_env_path(profiles_dir: str, name: str) -> tuple[str, Optional[str]]:
    """大小写不敏感地找到 <profile>.env，返回 (规范名, 路径或 None)。"""
    normalized = _normalize_username(name)
    if not normalized:
        return normalized, None

    direct = os.path.join(profiles_dir, f"{normalized}.env")
    if os.path.exists(direct):
        return normalized, direct

    if os.path.isdir(profiles_dir):
        for entry in os.listdir(profiles_dir):
            if not entry.lower().endswith(".env"):
                continue
            stem = entry[:-4]
            if stem.strip().lower() == normalized:
                return normalized, os.path.join(profiles_dir, entry)
    return normalized, None


def _resolve_user_db_paths(data_dir: str, user: str) -> tuple[str, str]:
    """复刻 config._resolve_user_db_paths 的兼容查找逻辑。"""
    db_filename = f"history-{user.lower()}.db"
    db_path = os.path.join(data_dir, db_filename)
    old = os.path.join(data_dir, f"history_{user}.db")
    old_lower = os.path.join(data_dir, f"history_{user.lower()}.db")
    if not os.path.exists(db_path):
        if os.path.exists(old):
            db_path = old
        elif os.path.exists(old_lower):
            db_path = old_lower

    test_db_path = os.path.join(data_dir, f"test-{user.lower()}.db")
    old_test = os.path.join(data_dir, f"test_{user}.db")
    if not os.path.exists(test_db_path) and os.path.exists(old_test):
        test_db_path = old_test
    return db_path, test_db_path


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

    normalized, env_path = _resolve_profile_env_path(profiles_dir, profile_name)
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

    db_path, test_db_path = _resolve_user_db_paths(data_dir, normalized)

    return ProfileConfig(
        profile_name=normalized,
        env_path=env_path or os.path.join(profiles_dir, f"{normalized}.env"),
        momo_token=merged.get("MOMO_TOKEN", "") or "",
        ai_provider=(merged.get("AI_PROVIDER") or "mimo").strip().lower(),
        gemini_api_key=merged.get("GEMINI_API_KEY", "") or "",
        mimo_api_key=merged.get("MIMO_API_KEY", "") or "",
        db_path=db_path,
        test_db_path=test_db_path,
        turso_db_url=merged.get("TURSO_DB_URL", "") or "",
        turso_auth_token=merged.get("TURSO_AUTH_TOKEN", "") or "",
        turso_db_hostname=merged.get("TURSO_DB_HOSTNAME", "") or "",
        turso_test_db_url=merged.get("TURSO_TEST_DB_URL", "") or "",
        turso_test_auth_token=merged.get("TURSO_TEST_AUTH_TOKEN", "") or "",
        turso_test_db_hostname=merged.get("TURSO_TEST_DB_HOSTNAME", "") or "",
    )
