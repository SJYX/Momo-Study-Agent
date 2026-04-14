# 日志快速参考

## 目的

这个页面给开发者提供最短路径的日志接入和排障入口。实现细节以 [core/logger.py](../../core/logger.py) 为准。

## 你该怎么用

- 正常业务日志使用 `get_logger()`。
- 需要结构化输出时，保持 `module` 字段稳定。
- 不要在核心业务里用 `print()` 替代日志。

## 核心能力

- 结构化输出：`StructuredFormatter`
- 异步记录：`AsyncLogger`
- 性能耗时：`log_performance()`
- 初始化入口：`setup_logger()`

## 常见排查

如果日志没有按预期出现，优先检查：
- `LOG_LEVEL`
- `LOG_MODULE_LEVELS`
- 当前模块是否真的走了 `core/logger.py`

## 关联文档

- [LOGGING_LEVELS.md](LOGGING_LEVELS.md)
- [../architecture/LOG_SYSTEM.md](../architecture/LOG_SYSTEM.md)
