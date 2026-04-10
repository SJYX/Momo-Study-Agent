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
# ❌ 错误：Turso 连接不支持
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

## 用户隔离规范

- 数据库路径：`data/history_{ACTIVE_USER}.db`
- 日志文件：`logs/{ACTIVE_USER}.log`
- 用户配置：`data/profiles/{ACTIVE_USER}.env`
- 禁止在任何模块中硬编码用户名

---

## 新功能开发流程

1. 在 `docs/dev/DECISIONS.md` 记录设计动机和否定方案
2. 实现功能
3. 运行 `python -m py_compile <文件>` 验证语法
4. 更新 `docs/dev/AI_CONTEXT.md` 中的"当前状态"节
