# CONTRIBUTING.md — 开发规约

> 所有向本项目贡献代码或使用 AI 进行 Vibe Coding 时，必须遵守以下规约。

---

## 日志规范

**严禁使用 `print()`**，所有输出必须通过 logger：

```python
from core.logger import get_logger

# 正常操作
get_logger().info("成功获取 10 条词汇", module="my_module")

# 带上下文的错误
get_logger().error("API 请求失败", error=str(e), module="my_module")

# 仅落文件不打控制台的调试信息（默认 DEBUG 级别不打控制台）
get_logger().debug("详细耗时: 120ms")
```

**例外**：`profile_manager.py` 和 `config_wizard.py` 中面向用户的交互提示（菜单选项、输入引导）**允许** `print()`，因为这是 CLI 的 UI 层。

---

## 数据库规范

### 查询结果映射

```python
# ❌ 错误：不要把云连接写法和本地 SQLite 写法混为一谈
conn.row_factory = sqlite3.Row
result = dict(row)

# ✅ 正确：使用兼容函数
from core.db_manager import _row_to_dict
cur.execute("SELECT ...")
row = cur.fetchone()
result = _row_to_dict(cur, row) if row else None
```

### 新增字段

只在 `db_manager._create_tables()` 中添加，并在函数末尾追加兼容升级：

```python
try:
    cur.execute("ALTER TABLE my_table ADD COLUMN new_field TEXT")
except Exception:
    pass  # 字段已存在时静默跳过
```

### 获取连接

```python
from core.db_manager import _get_conn, DB_PATH
conn = _get_conn(DB_PATH)  # 自动路由：有网→Turso，无网→本地 SQLite
```

### Turso 云数据库配置

- 当前代码支持从 `TURSO_DB_URL` 读取完整连接地址。
- 也支持仅配置 `TURSO_DB_HOSTNAME`，会自动补全为 `https://{hostname}`。
- 必须同时提供 `TURSO_AUTH_TOKEN`，用于 `libsql.connect(url, auth_token=...)`。
- 新用户向导会尝试调用 Turso API `POST /v1/organizations/{organizationSlug}/databases` 创建数据库，并将结果写入该用户的 `.env` 配置。

### 中央 Hub 初始化

如果是新环境（本地开发或新部署），必须先初始化中央 Hub 数据库以创建表结构和首个管理员帐号：

```bash
# 设置环境变量以跳过 profile 交互，并指定 UTF-8 编码修复 Windows 乱码
export MOMO_USER=Asher
export PYTHONIOENCODING=utf-8
python scripts/init_hub.py
```
这将在 `data/momo-users-hub.db`（或云端）创建管理表及默认管理员 Asher（密码见 `.env`）。

### 时区处理

所有数据库时间字段遵循以下规则：

```python
from core.db_manager import get_timestamp_with_tz

# ✓ 正确：带时区的 ISO 8601 格式
created_at = get_timestamp_with_tz()  # 输出：2026-04-11T14:30:45+08:00

# ❌ 错误：使用 time.time() 或 datetime.now()
cur.execute("... VALUES (..., ?, ...)", (..., time.time(), ...))
```

存储格式必须包含时区信息，便于多时区场景下的数据比对与审计。

### 凭证与安全

开源版本采用“用户自配凭证”模式，要求如下：

- 不要在仓库中提交真实 `MOMO_TOKEN`、`MIMO_API_KEY`、`GEMINI_API_KEY`、`TURSO_AUTH_TOKEN`
- 凭证仅放在本地 `.env` 或 `data/profiles/<user>.env`
- 提交前确认 `.gitignore` 生效，避免 `data/` 与 `.env` 被误提交

---

## AI 客户端扩展规范

新增 AI 提供商时，必须实现以下两个接口（参考 `gemini_client.py`）：

```python
class NewAIClient:
    def generate_mnemonics(self, words: List[Dict], prompt: str) -> Tuple[List[Dict], Dict]:
        """批量生成助记，返回 (results, metadata)"""
        ...

    def generate_with_instruction(self, content: str, instruction: str) -> Tuple[str, Dict]:
        """按指令生成文本，返回 (text, metadata)"""
        ...
```

然后在 `main.py` 的客户端初始化路由表中注册。

---

## Prompt 文件规范

- 所有 Prompt 文件统一存放于 `docs/prompts/`
- 路径通过 `config.py` 中的常量引用，不得硬编码
- 修改 Prompt 后启动时系统会自动计算 MD5 指纹并归档到 `data/prompts/`，无需手动操作

---

## compat 导入规范（迁移过渡期）

- `compat/` 是历史导入兼容层，不是新功能入口。
- 业务代码统一从 `core/` 导入。
- 测试与实验脚本在迁移过渡期可从 `compat/` 导入，避免历史路径直接失效。

示例：

```python
# 业务代码
from core.gemini_client import GeminiClient

# 测试/实验脚本（迁移过渡期）
from compat.gemini_client import GeminiClient
```

---

## 用户隔离规范

- 数据库路径：`data/history_{ACTIVE_USER}.db`
- 日志文件：`logs/{ACTIVE_USER}.log`
- 用户配置：`data/profiles/{ACTIVE_USER}.env`
- 禁止在任何模块中硬编码用户名

---

## 薄弱词筛选规范

### 筛选系统使用

使用 `WeakWordFilter` 类进行薄弱词筛选，而非单一阈值：

```python
from core.weak_word_filter import WeakWordFilter

filter = WeakWordFilter(logger)

# 获取动态阈值
user_stats = filter._get_user_stats()
threshold = filter.get_dynamic_threshold(user_stats)

# 按分数获取薄弱词
weak_words = filter.get_weak_words_by_score(min_score=50.0, limit=100)

# 按类别获取薄弱词
categorized = filter.get_weak_words_by_category(threshold)
```

### 评分维度

薄弱词评分基于以下维度（总分 100 分）：

1. **熟悉度** (0-40分)：熟悉度越低，分数越高
2. **复习次数** (0-20分)：复习次数越少，分数越高
3. **时间因素** (0-10分)：上次学习越久，分数越高
4. **迭代级别** (0-10分)：迭代级别越高，分数越高

### 阈值调整

- **动态阈值**：根据用户学习频率和平均熟悉度自动调整
- **高频用户**：阈值 +0.5（筛选更严格）
- **低频用户**：阈值 -0.5（筛选更宽松）

---

## 新功能开发流程

1. 在 `docs/dev/DECISIONS.md` 记录设计动机和否定方案
2. 实现功能
3. 运行 `python -m py_compile <文件>` 验证语法
4. 更新 `docs/dev/AI_CONTEXT.md` 中的"当前状态"节
5. 若功能涉及日志或排障，补充 `docs/dev/LOGGING.md` 与 `docs/dev/QUICK_START.md`
6. 若改动影响行为/配置/接口/流程，必须同步更新对应专项文档（如 `AUTO_SYNC.md`）
7. 变更说明中列出“受影响文档清单”，确保评审可追踪
