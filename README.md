# Momo Study Agent

这是一个基于墨墨背单词 OpenAPI 的多用户 CLI 工具。它负责拉取词汇、调用 AI 生成助记、写回墨墨，并把本地学习数据同步到 Turso 云端。

当前版本在本地数据库层默认启用 SQLite WAL 并发模式，并为 AI 笔记引入 `sync_status` 持久化队列状态（`0=待同步`, `1=已同步`），用于提升高并发写入稳定性和同步可恢复性。

## 快速开始

```bash
pip install -r requirements.txt
python tools/preflight_check.py --user <username>
python main.py
```

首次运行时，向导默认采用“先保存后校验”，敏感输入会隐藏回显；如果暂时没有完整凭证，也可以先跳过，后续再用 preflight 补齐。

## Prompt 工程迭代

如果是为了迭代和优化 `gem_prompt.md`，请执行专门的工具：

```bash
# 初始化开发环境
python scripts/prompt_dev_tool.py init

# 启动自动优化循环 (评估 -> 打分 -> 局部重写 -> 再打分)
python scripts/prompt_dev_tool.py optimize
```
详细说明见 [scripts/prompt_dev_tool.py](scripts/prompt_dev_tool.py)。

## 你会用到的入口

- [docs/DOCUMENT_INDEX.md](docs/DOCUMENT_INDEX.md) 是文档总索引。
- [docs/dev/AI_CONTEXT.md](docs/dev/AI_CONTEXT.md) 是 AI 执行规范唯一来源。
- [docs/dev/LOGGING.md](docs/dev/LOGGING.md) 是日志接入和排障入口。
- [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md) 是架构总入口。
- [docs/dev/NEW_USER_ZERO_CREDENTIAL_PLAN.md](docs/dev/NEW_USER_ZERO_CREDENTIAL_PLAN.md) 只保留历史方案入口。

## 目录说明

```text
MOMO_Script/
├── main.py
├── config.py
├── compat/
├── core/
├── data/
├── docs/
├── logs/
├── scripts/
├── tools/
└── tests/
```

- `core/` 放运行时代码。
- `compat/` 放旧导入兼容层（迁移过渡期），新业务代码从 `core/` 导入，测试/实验脚本可暂用 `compat/` 保持历史路径兼容。
- `data/`、`logs/` 只保留必要的目录占位文件，真正的 profile、日志和缓存属于运行时产物。

## 说明

如果你在根目录里看到 `.coverage`、`htmlcov/`、`.pytest_cache/`、`test.db` 这类文件，它们是本地运行产物，不是项目源代码。