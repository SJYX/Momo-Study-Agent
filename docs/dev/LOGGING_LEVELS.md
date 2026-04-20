# 日志分级系统 (Logging Levels System)

## 概述

项目现已实现完整的日志分级系统，支持全局级别配置和按模块级别覆盖。日志控制的单一事实来源是 [core/logger.py](../../core/logger.py)，`config.py` 不再保存独立的日志级别常量。

## 日志级别说明

| 级别 | 数值 | 说明 | 用途 |
|------|------|------|------|
| CRITICAL | 50 | 严重错误 | 系统故障、致命错误 |
| ERROR | 40 | 错误 | 功能失败、异常发生 |
| WARNING | 30 | 警告 | 潜在问题、不推荐操作 |
| INFO | 20 | 信息 | 操作进度、状态变化（**默认**） |
| DEBUG | 10 | 调试 | 详细调试信息、数据流 |
| NOTSET | 0 | 未设置 | 跟随父日志器配置 |

## 使用方式

### 方式 1️⃣：全局日志级别（环境变量）

设置 `LOG_LEVEL` 环境变量控制全局日志级别：

```bash
# 仅显示 WARNING 及以上级别
export LOG_LEVEL=WARNING

# 显示所有非调试信息（默认）
export LOG_LEVEL=INFO

# 显示所有信息包括调试（最详细）
export LOG_LEVEL=DEBUG
```

**示例：**
```bash
# Linux/macOS
LOG_LEVEL=DEBUG python main.py

# Windows PowerShell
$env:LOG_LEVEL="DEBUG"; python main.py

# Windows cmd
set LOG_LEVEL=DEBUG && python main.py
```

### 方式 2️⃣：按模块级别覆盖

使用 `LOG_MODULE_LEVELS` 环境变量为特定模块设置日志级别（优先级高于全局设置）：

```bash
# 格式: "module1:LEVEL1,module2:LEVEL2,..."
export LOG_MODULE_LEVELS="database.connection:WARNING,sync_manager:DEBUG,maimemo_api:ERROR"
```

**示例：**
```bash
# 仅调试 sync_manager 模块，其他模块用全局 INFO 级别
export LOG_LEVEL=INFO
export LOG_MODULE_LEVELS="sync_manager:DEBUG"
python main.py
```

## 代码中的日志调用

### 基础调用（默认 DEBUG 级别）

```python
from core.db_manager import _debug_log

# 最简单的调用方式（自动 DEBUG 级别）
_debug_log("数据库初始化完成")
_debug_log("处理了 100 条记录", start_time=time.time())
```

### 指定日志级别

```python
# 设置为 INFO 级别
_debug_log("用户登录成功", level="INFO")

# 设置为 WARNING 级别
_debug_log("检测到重复处理的词汇", level="WARNING")

# 设置为 ERROR 级别
_debug_log(f"凭证获取失败: {error_msg}", level="ERROR")

# 设置为 CRITICAL 级别
_debug_log("数据库连接完全失败", level="CRITICAL")
```

### 指定模块名称

```python
# 默认模块为 "db_manager"
_debug_log("同步完成", module="db_manager")

# 为其他模块调用
_debug_log("AI 调用成功", module="mimo")
_debug_log("墨墨 API 返回异常", module="maimemo_api")
```

### 完整示例

```python
import time

# 调试信息：显示关键流程
_debug_log("开始同步数据库...", level="DEBUG", module="sync")

try:
    start = time.time()
    result = sync_databases()
    # 信息：记录操作结果
    _debug_log(f"同步成功: {result} 条记录", start_time=start, level="INFO")
except Exception as e:
    # 错误：记录异常
    _debug_log(f"同步失败: {str(e)}", level="ERROR")
```

## 常见场景

### 场景 1：生产环境（仅看警告和错误）

```bash
export LOG_LEVEL=WARNING
python main.py
```

### 场景 2：调试特定功能

```bash
# 只调试数据库模块，其他模块显示 INFO
export LOG_LEVEL=INFO
export LOG_MODULE_LEVELS="db_manager:DEBUG"
python main.py
```

### 场景 3：完整调试（所有信息）

```bash
export LOG_LEVEL=DEBUG
python main.py
```

### 场景 4：多模块调试

```bash
export LOG_LEVEL=WARNING
export LOG_MODULE_LEVELS="db_manager:DEBUG,mimo:DEBUG,maimemo_api:INFO"
python main.py
```

## 配置文件方式

也可以在 `.env` 文件中设置：

```bash
# .env
LOG_LEVEL=INFO
LOG_MODULE_LEVELS=db_manager:DEBUG,mimo:WARNING
```

## 性能影响

- **级别越低（DEBUG），性能影响越大** - 需要更多日志处理
- **级别越高（WARNING/CRITICAL），性能影响最小** - 仅输出关键信息
- 建议生产环境使用 `WARNING` 或 `ERROR` 级别

## 日志输出示例

### DEBUG 级别
```
[DB_MANAGER] 快速路径检测完成: 数据一致，跳过对比 | Time: 5ms
[DB_MANAGER] 同步 ai_word_notes 表... | Time: 120ms
[DB_MANAGER] 数据库同步完成 | 总耗时: 250ms
```

### INFO 级别
```
[DB_MANAGER] 同步成功: 上传 15, 下载 3
[MIMO] AI 调用完成: tokens=500
```

### WARNING 级别
```
[DB_MANAGER] 警告: 检测到重复处理的词汇 ID
[MAIMEMO_API] 警告: API 频率限制，3 秒后重试
```

### ERROR 级别
```
[DB_MANAGER] 错误: 数据库连接失败: connection timeout
[MIMO] 错误: API 返回 429, 重试次数已达上限
```

## 注意事项

1. **模块名匹配** - `LOG_MODULE_LEVELS` 中的模块名应与代码中 `module` 参数一致
2. **优先级顺序** - 模块级别 > 全局级别 > 默认 INFO
3. **环境变量大小写** - 推荐使用大写，但也支持小写（自动转换）
4. **单一入口** - 日志级别由 `core/logger.py` 统一解释和过滤，不再从 `config.py` 读取冗余副本
5. **性能调优** - 生产环境建议 WARNING 以上，开发环境可用 DEBUG
6. **日志持久化** - 控制台和文件可配置不同级别（`console_level` / `file_level`）

## 实现对应

- `StructuredFormatter`：文件输出的结构化 JSON 格式。
- `AsyncLogger`：`use_async=True` 时启用的异步队列。
- `setup_logger()`：统一初始化入口，承接环境配置。
- `log_performance()`：当前实现以显式传入 logger 或 logger 工厂为主。

## 相关文档

- [LOGGING.md](LOGGING.md)
- [../architecture/LOG_SYSTEM.md](../architecture/LOG_SYSTEM.md)

## 扩展开发

### 为新模块添加日志

```python
# 在你的模块中导入
from core.db_manager import _debug_log

# 在适当位置调用
_debug_log("模块初始化完成", level="INFO", module="my_module")
```

### 创建模块级别的日志函数（可选）

```python
# my_module.py
from core.db_manager import _debug_log as _log

def log_info(msg, start_time=None):
    _log(msg, start_time=start_time, level="INFO", module="my_module")

def log_debug(msg, start_time=None):
    _log(msg, start_time=start_time, level="DEBUG", module="my_module")
```

## 故障排除

**问题：设置了 LOG_LEVEL 但日志没有减少**
- 检查是否有模块级别覆盖（`LOG_MODULE_LEVELS`）
- 确认环境变量拼写正确：`LOG_LEVEL` 而非 `LOGLEVEL`
- 确认日志初始化走的是 `core.logger.setup_logger()`，而不是旧的配置副本

**问题：某个模块的日志仍然显示**
- 检查模块名是否正确（注意大小写）
- 使用 `LOG_MODULE_LEVELS="module_name:WARNING"` 进行覆盖

**问题：日志性能下降**
- 降低全局 `LOG_LEVEL` 到 WARNING 或 ERROR
- 只为需要调试的模块设置 DEBUG 级别
