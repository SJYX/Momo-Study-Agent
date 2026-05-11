# 日志快速参考

## 目的

这个页面给开发者提供最短路径的日志接入和排障入口。实现细节以 [core/logger.py](../../core/logger.py) 为准。

## 你该怎么用

- 正常业务日志使用 `get_logger()`。
- 需要结构化输出时，保持 `module` 字段稳定。
- 不要在核心业务里用 `print()` 替代日志。
- 频繁日志（如循环内重复输出）使用节流方法：`logger.debug_throttled()` / `info_throttled()` / `warning_throttled()` / `error_throttled(key, interval_seconds)`（Phase 5）。

## 核心能力

- 结构化输出：`StructuredFormatter`
- 异步记录：`AsyncLogger`
- 性能耗时：`log_performance()`
- 节流方法：`{debug,info,warning,error}_throttled(key, message, interval_seconds=60)` —— 同一 `key` 的日志在间隔内仅输出一次（Phase 5）
- 初始化入口：`setup_logger()`

## 常见排查

如果日志没有按预期出现，优先检查：
- `LOG_LEVEL`
- `LOG_MODULE_LEVELS`
- 当前模块是否真的走了 `core/logger.py`
- 若日志被"吞掉"，检查是否使用了 throttle 方法且还在冷却期内

## 关联文档

- [LOGGING_LEVELS.md](LOGGING_LEVELS.md)
- [../architecture/LOG_SYSTEM.md](../architecture/LOG_SYSTEM.md)
