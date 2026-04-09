import os
from dotenv import load_dotenv

# 加载 .env 依赖
load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# 核心配置 (Core Config)
# ──────────────────────────────────────────────────────────────────────────────

# API Keys
MOMO_TOKEN = os.getenv("MOMO_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MIMO_API_KEY = os.getenv("MIMO_API_KEY")
MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://api.mioffice.cn/v1")

# 模型设置 (AI Settings)
# 优先级：环境变量 > 默认模型
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2-flash")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1"))

# 当前使用的 AI 提供商: "gemini" 或 "mimo"
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini")

# 重试机制 (Retry Logic)
MAX_RETRIES = 3
RETRY_WAIT_S = [10, 25, 60]

# ──────────────────────────────────────────────────────────────────────────────
# 路径配置 (Paths)
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PROMPT_FILE = os.path.join(BASE_DIR, "gem_prompt.md")

# 数据库路径
DB_PATH = os.path.join(DATA_DIR, "history.db")
TEST_DB_PATH = os.path.join(DATA_DIR, "test.db")

# ──────────────────────────────────────────────────────────────────────────────
# 运行控制 (Runtime)
# ──────────────────────────────────────────────────────────────────────────────
DRY_RUN = False  # 测试模式开关，默认开启

def ensure_dirs():
    """确保必要的目录存在。"""
    os.makedirs(DATA_DIR, exist_ok=True)

# 初始化
ensure_dirs()
