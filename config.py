import os
import sys
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────────────
# 路径定义 (Paths)
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")
PROMPT_FILE = os.path.join(BASE_DIR, "gem_prompt.md")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PROFILES_DIR, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# 多用户 Profile 初始化 (Multi-user Initialization)
# ──────────────────────────────────────────────────────────────────────────────
# 只有在直接运行主程序或脚本时触发交互，如果是自动化测试，建议通过环境变量指定用户
ACTIVE_USER = os.getenv("MOMO_USER")

# 内部导入避免循环依赖
from core.profile_manager import ProfileManager
from core.config_wizard import ConfigWizard

pm = ProfileManager(PROFILES_DIR)
wizard = ConfigWizard(PROFILES_DIR)

if not ACTIVE_USER:
    # 交互式选择或创建用户 (内部已集成向导)
    ACTIVE_USER = pm.pick_profile()

# 加载选中用户的配置文件
profile_env = os.path.join(PROFILES_DIR, f"{ACTIVE_USER}.env")
if os.path.exists(profile_env):
    load_dotenv(profile_env, override=True)
else:
    # 回退：如果没有 Profile 则尝试加载根目录旧有的 .env (兼容性)
    load_dotenv(os.path.join(BASE_DIR, ".env"))

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
DB_PATH = os.path.join(DATA_DIR, f"history_{ACTIVE_USER}.db")
TEST_DB_PATH = os.path.join(DATA_DIR, f"test_{ACTIVE_USER}.db")

# 运行控制
DRY_RUN = False 
