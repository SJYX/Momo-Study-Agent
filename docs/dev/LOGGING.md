# 日志快速参考

## 目的

这个页面只给开发者提供最短路径的日志接入和排障入口。实现细节以 [core/logger.py](../../core/logger.py) 为准，级别与覆盖规则见下方“日志级别与覆盖”段落。

## 你该怎么用

- 正常业务日志使用 `get_logger()`。
- 需要结构化输出时，保持 `module` 字段稳定。
- 不要在核心业务里用 `print()` 替代日志。
- 频繁日志（如循环内重复输出）使用节流方法：`logger.debug_throttled()` / `info_throttled()` / `warning_throttled()` / `error_throttled(key, interval_seconds)`。

## 日志级别与覆盖

- 全局级别通过 `LOG_LEVEL` 控制，支持 `CRITICAL` / `ERROR` / `WARNING` / `INFO` / `DEBUG`。
- 模块级别通过 `LOG_MODULE_LEVELS` 覆盖，格式为 `module1:LEVEL1,module2:LEVEL2`。
- 当前代码库常用模块名包括 `database.connection`、`database.momo_words`、`database.schema`、`database.hub_users`、`database.utils`。
- `core/db_manager.py` 已删除，旧的 `db_manager` module key 不再使用。

示例：

```bash
LOG_LEVEL=INFO
LOG_MODULE_LEVELS="database.connection:DEBUG,mimo:WARNING"
```

```python
_debug_log("同步完成", module="database.connection")
```

## 核心能力

- 结构化输出：`StructuredFormatter`
- 异步记录：`AsyncLogger`
- 性能耗时：`log_performance()`
- 节流方法：`{debug,info,warning,error}_throttled(key, message, interval_seconds=60)` —— 同一 `key` 的日志在间隔内仅输出一次。
- 初始化入口：`setup_logger()`

## 常见排查

如果日志没有按预期出现，优先检查：
- `LOG_LEVEL`
- `LOG_MODULE_LEVELS`
- 当前模块是否真的走了 `core/logger.py`
- 若日志被"吞掉"，检查是否使用了 throttle 方法且还在冷却期内

## 关联文档

- [../architecture/LOG_SYSTEM.md](../architecture/LOG_SYSTEM.md)
