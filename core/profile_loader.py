"""
core/profile_loader.py: 多用户 profile 生命周期 + 三阶段 env 加载 + DB 路径解析。

从 config.py 抽出，是 Phase 6.3a 重构的成果。设计目标：让 config.py 真正只
"导出 settings"，profile 生命周期作为独立子系统暴露。

外部入口：
- `bootstrap_initial_profile(global_env_path, profiles_dir, base_dir)` — 程序启动调用一次。
  完成三阶段 env 加载 + 解析 ACTIVE_USER + 计算 DB_PATH/TEST_DB_PATH。
  返回 `ProfileBootstrap` dataclass。
- `switch_user(username, ...)` — 运行时热切换。返回规范化后的用户名。

设计取舍：
- `switch_user` 仍然反向 patch `database.connection` / `database.momo_words` 模块的
  DB_PATH 全局——这是历史 wart，移除需要更深的连接重建逻辑。Phase 6.3a 不动。
- 模块级 mutable 全局（ACTIVE_USER 等）没有引入；返回 dataclass 让调用方决定怎么 cache。
- USER_SCOPED_KEYS 集中在这里维护，不在 config.py 复制。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from dotenv import load_dotenv


USER_SCOPED_KEYS: List[str] = [
    "MOMO_TOKEN",
    "AI_PROVIDER",
    "AI_PROTOCOL",
    "AI_API_KEY",
    "AI_MODEL",
    "AI_BASE_URL",
    "MIMO_API_KEY",
    "MIMO_API_BASE",
    "MIMO_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "TURSO_DB_URL",
    "TURSO_AUTH_TOKEN",
    "TURSO_DB_HOSTNAME",
    "TURSO_TEST_DB_URL",
    "TURSO_TEST_AUTH_TOKEN",
    "TURSO_TEST_DB_HOSTNAME",
]


def apply_ai_legacy_fallbacks(
    *,
    provider: str,
    ai_api_key: str,
    ai_model: str,
    ai_base_url: str,
    gemini_api_key: str,
    gemini_model: str,
    mimo_api_key: str,
    mimo_model: str,
) -> Tuple[str, str, str]:
    """Pure migration helper: if the unified AI_* values are missing, fill
    them from the legacy provider-keyed fields and apply the mimo-default
    base_url.

    Extracted from the duplicated logic at config.py:module-load and
    config.py:switch_user — one source of truth so the two callsites
    can't drift.

    Returns (ai_api_key, ai_model, ai_base_url).
    """
    if not ai_api_key:
        if provider == "gemini" and gemini_api_key:
            ai_api_key = gemini_api_key
        elif mimo_api_key:
            ai_api_key = mimo_api_key

    if not ai_model:
        if provider == "gemini" and gemini_model:
            ai_model = gemini_model
        elif mimo_model:
            ai_model = mimo_model

    if provider == "mimo" and not ai_base_url:
        ai_base_url = "https://api.xiaomimimo.com/v1"

    return ai_api_key, ai_model, ai_base_url


@dataclass
class ProfileBootstrap:
    """初始 bootstrap 结果。供 config.py 导出为模块级符号。"""

    active_user: str
    db_path: str
    test_db_path: str
    profile_env_path: Optional[str] = None
    user_from_env: bool = False
    profile_files_seen: List[str] = field(default_factory=list)


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def resolve_profile_env_path(username: str, profiles_dir: str) -> Tuple[str, Optional[str]]:
    """大小写不敏感地定位 profile 文件。返回 (规范用户名, 文件路径或 None)。"""
    normalized = normalize_username(username)
    if not normalized:
        return normalized, None

    direct_path = os.path.join(profiles_dir, f"{normalized}.env")
    if os.path.exists(direct_path):
        return normalized, direct_path

    try:
        entries = os.listdir(profiles_dir)
    except FileNotFoundError:
        return normalized, None

    for entry in entries:
        if not entry.lower().endswith(".env"):
            continue
        stem = entry[:-4]
        if stem.strip().lower() == normalized:
            return normalized, os.path.join(profiles_dir, entry)
    return normalized, None


def resolve_user_db_paths(user: str, data_dir: str) -> Tuple[str, str]:
    """返回 (db_path, test_db_path)，含历史命名兼容（history_X.db / history-X.db / 大小写）。"""
    db_filename = f"history-{user.lower()}.db"
    db_path = os.path.join(data_dir, db_filename)
    old_db_path = os.path.join(data_dir, f"history_{user}.db")
    old_db_path_lower = os.path.join(data_dir, f"history_{user.lower()}.db")
    if not os.path.exists(db_path):
        if os.path.exists(old_db_path):
            db_path = old_db_path
        elif os.path.exists(old_db_path_lower):
            db_path = old_db_path_lower

    test_db_path = os.path.join(data_dir, f"test-{user.lower()}.db")
    old_test_path = os.path.join(data_dir, f"test_{user}.db")
    if not os.path.exists(test_db_path) and os.path.exists(old_test_path):
        test_db_path = old_test_path

    return db_path, test_db_path


def _force_cloud_mode_from_global(global_env_path: str) -> Optional[str]:
    """单独读 .env 中的 FORCE_CLOUD_MODE。这是历史 wart：直接 file scan 而不走 dotenv，
    保留以避免改变行为；将来可统一到 dotenv。"""
    if not os.path.exists(global_env_path):
        return None
    try:
        with open(global_env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() == "FORCE_CLOUD_MODE":
                    return value.strip().strip('"').strip("'")
    except Exception:
        return None
    return None


def bootstrap_initial_profile(
    *,
    global_env_path: str,
    profiles_dir: str,
    data_dir: str,
) -> ProfileBootstrap:
    """三阶段 env 加载 + ACTIVE_USER 解析 + DB 路径计算。程序启动调用一次。

    阶段：
    1. 加载全局 .env（override=False）让交互向导能读 ADMIN_PASSWORD_HASH / Hub 配置。
    2. 清掉残留的 USER_SCOPED_KEYS（避免上一个用户的环境变量泄漏）。
    3. 重新加载全局 .env（override=True）让全局管理配置以 .env 为准。
    4. pytest / --help 模式默认 user=test_user / default。
    5. 读 MOMO_USER → 加载用户 profile env → 解析 DB 路径。
    6. 单独 file-scan 提取 FORCE_CLOUD_MODE 并 export 到 os.environ。
    """
    if os.path.exists(global_env_path):
        load_dotenv(global_env_path, override=False)

    for key in USER_SCOPED_KEYS:
        os.environ.pop(key, None)

    if os.path.exists(global_env_path):
        load_dotenv(global_env_path, override=True)

    # pytest / --help 兜底
    if "pytest" in sys.modules and os.getenv("MOMO_USER") is None:
        os.environ["MOMO_USER"] = "test_user"
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]) and os.getenv("MOMO_USER") is None:
        os.environ["MOMO_USER"] = "default"

    user_from_env = os.getenv("MOMO_USER") is not None
    raw_active = os.getenv("MOMO_USER") or "default"
    active_user = normalize_username(raw_active)

    active_user, profile_env = resolve_profile_env_path(active_user, profiles_dir)
    if user_from_env and profile_env:
        load_dotenv(profile_env, override=True)

    db_path, test_db_path = resolve_user_db_paths(active_user, data_dir)

    fcm = _force_cloud_mode_from_global(global_env_path)
    if fcm is not None:
        os.environ["FORCE_CLOUD_MODE"] = fcm

    if not user_from_env:
        # 没有显式指定 MOMO_USER：默认降级为 default 并加载其 profile（如有）
        active_user = "default"
        os.environ["MOMO_USER"] = active_user
        active_user, profile_env = resolve_profile_env_path(active_user, profiles_dir)
        if profile_env:
            load_dotenv(profile_env, override=True)
        db_path, test_db_path = resolve_user_db_paths(active_user, data_dir)

    return ProfileBootstrap(
        active_user=active_user,
        db_path=db_path,
        test_db_path=test_db_path,
        profile_env_path=profile_env,
        user_from_env=user_from_env,
    )


def switch_user(
    username: str,
    *,
    global_env_path: str,
    profiles_dir: str,
    data_dir: str,
) -> Tuple[str, str, str]:
    """运行时热切换：清旧 USER_SCOPED_KEYS → 加载新 profile env → 重载全局 → 计算 DB 路径。

    返回 (规范化用户名, db_path, test_db_path)。

    注意：调用方需要把返回值同步到 config 模块级变量 + database 模块的 DB_PATH 缓存。
    本函数不做反向 patch（保持纯计算）；patch 留在 config.switch_user 里——这样
    profile_loader 可以独立测试。
    """
    for key in USER_SCOPED_KEYS:
        os.environ.pop(key, None)

    normalized, profile_env = resolve_profile_env_path(username, profiles_dir)
    if not normalized:
        normalized = "default"

    os.environ["MOMO_USER"] = normalized
    if profile_env:
        load_dotenv(profile_env, override=True)

    if os.path.exists(global_env_path):
        load_dotenv(global_env_path, override=False)

    db_path, test_db_path = resolve_user_db_paths(normalized, data_dir)
    return normalized, db_path, test_db_path
