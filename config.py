import os
import sys
import io
import platform
from dotenv import load_dotenv

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

# Prompt 迭代优化工具路径 (Prompt Iteration Dev Tool)
PROMPT_DEV_DIR = os.path.join(BASE_DIR, "docs", "prompts", "dev")
PROMPT_DEV_FILE = os.path.join(PROMPT_DEV_DIR, "gem_prompt_iteration.md")
AUDITOR_PROMPT_FILE = os.path.join(BASE_DIR, "docs", "prompts", "evaluation", "system_auditor_prompt.md")
OPTIMIZER_PROMPT_FILE = os.path.join(PROMPT_DEV_DIR, "prompt_optimizer.md")
BENCHMARK_DIR = os.path.join(DATA_DIR, "benchmark")
PROMPT_ITERATION_DB = os.path.join(DATA_DIR, "prompt_iterations.db")
PROMPT_HISTORY_DIR = os.path.join(BASE_DIR, "docs", "prompts", "history")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PROFILES_DIR, exist_ok=True)
os.makedirs(PROMPT_DEV_DIR, exist_ok=True)
os.makedirs(BENCHMARK_DIR, exist_ok=True)
os.makedirs(PROMPT_HISTORY_DIR, exist_ok=True)

# 先加载全局 .env 以便交互向导可以读取共享配置（如 ADMIN_PASSWORD_HASH / Hub 配置）
# 参考模板: .env.example
global_env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(global_env_path):
    load_dotenv(global_env_path, override=False)  # override=False: 不覆盖已有的

# 用户隔离的敏感配置：必须来自 data/profiles/<user>.env，而不是全局 .env
USER_SCOPED_KEYS = [
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
]
for key in USER_SCOPED_KEYS:
    os.environ.pop(key, None)

# 全局管理配置必须以 .env 为准，避免当前 shell 残留旧值导致 slug/token 混用
if os.path.exists(global_env_path):
    load_dotenv(global_env_path, override=True)

# ──────────────────────────────────────────────────────────────────────────────
# 多用户 Profile 初始化 (Multi-user Initialization)
# ──────────────────────────────────────────────────────────────────────────────
# 只有在直接运行主程序或脚本时触发交互，如果是自动化测试，建议通过环境变量指定用户
if "pytest" in sys.modules and os.getenv("MOMO_USER") is None:
    os.environ["MOMO_USER"] = "test_user"

# 帮助模式下避免触发交互式用户选择，确保 `python main.py --help` 可直接输出帮助。
if any(arg in ("-h", "--help") for arg in sys.argv[1:]) and os.getenv("MOMO_USER") is None:
    os.environ["MOMO_USER"] = "default"

ACTIVE_USER = os.getenv("MOMO_USER") or "default"
_USER_FROM_ENV = os.getenv("MOMO_USER") is not None


def _normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def _resolve_profile_env_path(username: str):
    """按大小写不敏感方式定位 profile 文件，返回 (规范用户名, 文件路径或 None)。"""
    normalized = _normalize_username(username)
    if not normalized:
        return normalized, None

    direct_path = os.path.join(PROFILES_DIR, f"{normalized}.env")
    if os.path.exists(direct_path):
        return normalized, direct_path

    for entry in os.listdir(PROFILES_DIR):
        if not entry.lower().endswith(".env"):
            continue
        stem = entry[:-4]
        if stem.strip().lower() == normalized:
            return normalized, os.path.join(PROFILES_DIR, entry)
    return normalized, None


ACTIVE_USER = _normalize_username(ACTIVE_USER)

def _resolve_user_db_paths(user: str):
    db_filename = f"history-{user.lower()}.db"
    db_path = os.path.join(DATA_DIR, db_filename)
    old_db_path = os.path.join(DATA_DIR, f"history_{user}.db")
    old_db_path_lower = os.path.join(DATA_DIR, f"history_{user.lower()}.db")
    if not os.path.exists(db_path):
        if os.path.exists(old_db_path):
            db_path = old_db_path
        elif os.path.exists(old_db_path_lower):
            db_path = old_db_path_lower

    test_db_path = os.path.join(DATA_DIR, f"test-{user.lower()}.db")
    old_test_path = os.path.join(DATA_DIR, f"test_{user}.db")
    if not os.path.exists(test_db_path) and os.path.exists(old_test_path):
        test_db_path = old_test_path

    return db_path, test_db_path

# 内部导入避免循环依赖
from core.profile_manager import ProfileManager

pm = ProfileManager(PROFILES_DIR)

# 如果通过环境变量指定用户，先加载该用户 profile
ACTIVE_USER, profile_env = _resolve_profile_env_path(ACTIVE_USER)
if _USER_FROM_ENV and profile_env:
    load_dotenv(profile_env, override=True)

# 先为当前用户（或 default）准备路径，供其他模块在初始化期间引用
DB_PATH, TEST_DB_PATH = _resolve_user_db_paths(ACTIVE_USER)

# ──────────────────────────────────────────────────────────────────────────────
# 强制云端模式（全局不可覆盖）
# ──────────────────────────────────────────────────────────────────────────────
# 无论用户配置如何，强制云端模式始终从全局 .env 读取
# 这确保了所有用户都必须使用云端数据库
if os.path.exists(global_env_path):
    # 重新加载全局配置中的 FORCE_CLOUD_MODE
    global_config = {}
    with open(global_env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                parts = line.split('=', 1)
                if len(parts) == 2:
                    k, v = parts
                    global_config[k.strip()] = v.strip().strip('"').strip("'")

    if 'FORCE_CLOUD_MODE' in global_config:
        os.environ['FORCE_CLOUD_MODE'] = global_config['FORCE_CLOUD_MODE']

if not _USER_FROM_ENV:
    # 交互式选择或创建用户（放在 DB_PATH 定义之后，避免新建用户时触发循环导入）
    ACTIVE_USER = _normalize_username(pm.pick_profile())
    os.environ["MOMO_USER"] = ACTIVE_USER

    # 重新加载选中用户的配置文件（用户配置优先级更高）
    ACTIVE_USER, profile_env = _resolve_profile_env_path(ACTIVE_USER)
    if profile_env:
        load_dotenv(profile_env, override=True)  # override=False: 用户配置覆盖全局

    # 根据最终选中的用户重新计算数据库路径
    DB_PATH, TEST_DB_PATH = _resolve_user_db_paths(ACTIVE_USER)

# ──────────────────────────────────────────────────────────────────────────────
# 导出核心配置 (Exported Config)
# ──────────────────────────────────────────────────────────────────────────────

# API Keys
MOMO_TOKEN = os.getenv("MOMO_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MIMO_API_KEY = os.getenv("MIMO_API_KEY")
MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://api.xiaomimimo.com/v1")

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
TURSO_GROUP = os.getenv('TURSO_GROUP', 'default')
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
# True: 必须使用云端数据库，本地仅作为备份/缓存
# False: 允许纯本地运行（不推荐）
def get_force_cloud_mode():
    """动态获取强制云端模式。允许在程序运行期间通过环境变量临时修改。"""
    return os.getenv('FORCE_CLOUD_MODE', 'False').lower() in ('true', '1', 'yes', 'y')

FORCE_CLOUD_MODE = get_force_cloud_mode()

