"""
config.py: 全局配置导出 + profile bootstrap 入口。

Phase 6.3a 起：profile 生命周期 / 三阶段 env 加载 / DB 路径解析 已抽到
``core/profile_loader.py``；本文件保留为：

1. UTF-8 控制台 hack（Windows）。
2. 路径常量（BASE_DIR / DATA_DIR / PROFILES_DIR / *_PROMPT_FILE）。
3. 调用 profile_loader.bootstrap_initial_profile 拿到 ACTIVE_USER + DB_PATH。
4. 静态 settings 导出（API keys / Turso URL / 重试常量等）。
5. switch_user thin wrapper（含跨模块 patch）——历史 wart，待 6.3b/6.4 后续清理。

字段名与导出列表 100% 与重构前一致，所有 ``from config import X`` 都不破。
"""
import io
import os
import platform
import sys

from core.profile_loader import (
    USER_SCOPED_KEYS,
    bootstrap_initial_profile,
    normalize_username as _normalize_username,
    resolve_profile_env_path as _resolve_profile_env_path,
    resolve_user_db_paths as _resolve_user_db_paths,
    switch_user as _switch_user_impl,
)

# Force UTF-8 encoding for console output on Windows
if platform.system() == "Windows" and "pytest" not in sys.modules:
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ──────────────────────────────────────────────────────────────────────────────
# 路径定义 (Paths)
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")
PROMPT_FILE = os.path.join(BASE_DIR, "docs", "prompts", "gem_prompt.md")
SCORE_PROMPT_FILE = os.path.join(BASE_DIR, "docs", "prompts", "score_prompt.md")
REFINE_PROMPT_FILE = os.path.join(BASE_DIR, "docs", "prompts", "refine_prompt.md")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PROFILES_DIR, exist_ok=True)

global_env_path = os.path.join(BASE_DIR, ".env")

# ──────────────────────────────────────────────────────────────────────────────
# Profile bootstrap：三阶段 env 加载 + DB 路径解析
# ──────────────────────────────────────────────────────────────────────────────
_bootstrap = bootstrap_initial_profile(
    global_env_path=global_env_path,
    profiles_dir=PROFILES_DIR,
    data_dir=DATA_DIR,
)

ACTIVE_USER = _bootstrap.active_user
DB_PATH = _bootstrap.db_path
TEST_DB_PATH = _bootstrap.test_db_path
_USER_FROM_ENV = _bootstrap.user_from_env

# 内部导入（与 ProfileManager 解耦的轻量初始化）
from core.profile_manager import ProfileManager

pm = ProfileManager(PROFILES_DIR)

# ──────────────────────────────────────────────────────────────────────────────
# 导出核心配置 (Exported Config)
# ──────────────────────────────────────────────────────────────────────────────

# API Keys
MOMO_TOKEN = os.getenv("MOMO_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MIMO_API_KEY = os.getenv("MIMO_API_KEY")
MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://api.xiaomimimo.com/v1")
#MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://token-plan-sgp.xiaomimimo.com/v1")

# 模型设置 (AI Settings)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2-flash")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1"))

# 当前使用的 AI 提供商: "gemini" 或 "mimo"
AI_PROVIDER = os.getenv("AI_PROVIDER", "mimo")

# 重试机制 (Retry Logic)
MAX_RETRIES = 3
RETRY_WAIT_S = [10, 25, 60]

# ──────────────────────────────────────────────────────────────────────────────
# Turso 云数据库配置 (Turso Cloud)
# ──────────────────────────────────────────────────────────────────────────────
TURSO_DB_URL = os.getenv('TURSO_DB_URL')
TURSO_AUTH_TOKEN = os.getenv('TURSO_AUTH_TOKEN')
TURSO_DB_HOSTNAME = os.getenv('TURSO_DB_HOSTNAME')
TURSO_TEST_DB_URL = os.getenv('TURSO_TEST_DB_URL')
TURSO_TEST_AUTH_TOKEN = os.getenv('TURSO_TEST_AUTH_TOKEN')
TURSO_TEST_DB_HOSTNAME = os.getenv('TURSO_TEST_DB_HOSTNAME')

# 中央用户信息库（全局共用，非用户隔离）
TURSO_HUB_DB_URL = os.getenv('TURSO_HUB_DB_URL')
TURSO_HUB_AUTH_TOKEN = os.getenv('TURSO_HUB_AUTH_TOKEN')
# 全局 Turso 管理配置（用于创建用户数据库）
TURSO_MGMT_TOKEN = os.getenv('TURSO_MGMT_TOKEN')
TURSO_ORG_SLUG = os.getenv('TURSO_ORG_SLUG')
TURSO_GROUP = os.getenv('TURSO_GROUP', '123')
# 本地回退路径
HUB_DB_PATH = os.path.join(DATA_DIR, "momo-users-hub.db")

# ──────────────────────────────────────────────────────────────────────────────
# 安全与加密 (Security & Encryption)
# ──────────────────────────────────────────────────────────────────────────────
ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH')
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')

# 运行控制
DRY_RUN = False


# 强制云端运行模式
def get_force_cloud_mode():
    """动态获取强制云端模式。允许在程序运行期间通过环境变量临时修改。"""
    return os.getenv('FORCE_CLOUD_MODE', 'False').lower() in ('true', '1', 'yes', 'y')


FORCE_CLOUD_MODE = get_force_cloud_mode()


# ──────────────────────────────────────────────────────────────────────────────
# 运行时用户切换 (Runtime User Switch)
# ──────────────────────────────────────────────────────────────────────────────
def switch_user(username: str) -> str:
    """热切换当前用户：重新加载 profile env 并更新模块级变量。

    调用后 ``config.AI_PROVIDER`` / ``config.DB_PATH`` / ``config.MOMO_TOKEN`` 等
    立即生效。所有下游 ``database.*`` 模块都直接读 ``config.DB_PATH``——
    Phase 6.4 起本函数不再反向 patch 任何子模块的全局变量。

    返回规范化后的用户名。
    """
    global ACTIVE_USER, MOMO_TOKEN, GEMINI_API_KEY, GEMINI_MODEL, MIMO_API_KEY, MIMO_API_BASE, MIMO_MODEL
    global AI_PROVIDER, DB_PATH, TEST_DB_PATH, TURSO_DB_URL, TURSO_AUTH_TOKEN

    normalized, db_path, test_db_path = _switch_user_impl(
        username,
        global_env_path=global_env_path,
        profiles_dir=PROFILES_DIR,
        data_dir=DATA_DIR,
    )

    ACTIVE_USER = normalized
    MOMO_TOKEN = os.getenv("MOMO_TOKEN")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.0-flash"
    MIMO_API_KEY = os.getenv("MIMO_API_KEY")
    MIMO_API_BASE = os.getenv("MIMO_API_BASE") or "https://api.xiaomimimo.com/v1"
    MIMO_MODEL = os.getenv("MIMO_MODEL") or "mimo-v2-flash"
    AI_PROVIDER = os.getenv("AI_PROVIDER", "mimo")
    TURSO_DB_URL = os.getenv("TURSO_DB_URL")
    TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
    DB_PATH = db_path
    TEST_DB_PATH = test_db_path

    return normalized
