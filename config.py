import os
import sys
import io
import platform
from dotenv import load_dotenv

# Force UTF-8 encoding for console output on Windows
if platform.system() == "Windows":
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

# 先加载全局 .env 以便交互向导可以读取共享配置（如 ADMIN_PASSWORD_HASH / Hub 配置）
# 参考模板: .env.example
global_env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(global_env_path):
    load_dotenv(global_env_path, override=False)  # override=False: 不覆盖已有的

# ──────────────────────────────────────────────────────────────────────────────
# 多用户 Profile 初始化 (Multi-user Initialization)
# ──────────────────────────────────────────────────────────────────────────────
# 只有在直接运行主程序或脚本时触发交互，如果是自动化测试，建议通过环境变量指定用户
ACTIVE_USER = os.getenv("MOMO_USER") or None

# 内部导入避免循环依赖
from core.profile_manager import ProfileManager
from core.config_wizard import ConfigWizard

pm = ProfileManager(PROFILES_DIR)
wizard = ConfigWizard(PROFILES_DIR)

if not ACTIVE_USER:
    # 交互式选择或创建用户 (内部已集成向导)
    ACTIVE_USER = pm.pick_profile()

# 加载选中用户的配置文件（用户配置优先级更高）
profile_env = os.path.join(PROFILES_DIR, f"{ACTIVE_USER}.env")
if os.path.exists(profile_env):
    load_dotenv(profile_env, override=True)  # override=True: 用户配置覆盖全局

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

# 数据库路径 (按用户隔离)
_db_filename = f"history-{ACTIVE_USER.lower()}.db"
DB_PATH = os.path.join(DATA_DIR, _db_filename)
# 向后兼容：检查是否存在旧格式的文件 (history_User.db 或 history_user.db)
_old_db_path = os.path.join(DATA_DIR, f"history_{ACTIVE_USER}.db")
_old_db_path_lower = os.path.join(DATA_DIR, f"history_{ACTIVE_USER.lower()}.db")
if not os.path.exists(DB_PATH):
    if os.path.exists(_old_db_path):
        DB_PATH = _old_db_path
    elif os.path.exists(_old_db_path_lower):
        DB_PATH = _old_db_path_lower

TEST_DB_PATH = os.path.join(DATA_DIR, f"test-{ACTIVE_USER.lower()}.db")
_old_test_path = os.path.join(DATA_DIR, f"test_{ACTIVE_USER}.db")
if not os.path.exists(TEST_DB_PATH) and os.path.exists(_old_test_path):
    TEST_DB_PATH = _old_test_path

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
FORCE_CLOUD_MODE = os.getenv('FORCE_CLOUD_MODE', 'True').lower() in ('true', '1', 'yes', 'y') 
