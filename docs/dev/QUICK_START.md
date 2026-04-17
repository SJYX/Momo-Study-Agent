# 开发快速启动

## 目标

给新开发者一个最短的本地起步路径。

## 推荐顺序

1. 先看 [AI_CONTEXT.md](AI_CONTEXT.md) 了解当前约束。
2. 再看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解编码规约。
3. 需要排查日志时看 [LOGGING.md](LOGGING.md) 和 [LOGGING_LEVELS.md](LOGGING_LEVELS.md)。
4. 需要理解同步时看 [AUTO_SYNC.md](AUTO_SYNC.md).

## 起步检查

- 确认 `.env` 或 profile 配置已就绪。
- 运行 preflight 工具确认缺失项。
- 先跑单元测试，再改流程文档或交互。

## 最短可执行路径

```bash
pip install -r requirements.txt
python tools/preflight_check.py --user <username>
python -m pytest tests/ -v --tb=short -m "not slow"
python main.py
```

说明：

- 默认测试命令不依赖覆盖率插件，可直接在精简环境执行。
- 若要验证同步链路行为，优先阅读 [AUTO_SYNC.md](AUTO_SYNC.md) 再做流程改动。

## 适用范围

这个页面只做导航，不替代具体实现文档。
