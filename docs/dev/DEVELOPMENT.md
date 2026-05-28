# 开发指引（导航入口）

本文件**只是索引**——绝不复制其他文档内容，避免事实源漂移。
按你想做的事查表，跳转到对应权威文档。

## 第一次接触本项目

| 你想做什么 | 去哪看 |
| --- | --- |
| 规则红线（MUST / 反模式 / 数据流） | [`AI_CONTEXT.md`](AI_CONTEXT.md) — **唯一事实来源** |
| 项目地图 / 当前状态摘要 | [`../../CLAUDE.md`](../../CLAUDE.md)（AI 会话首页）/ [`../../AGENTS.md`](../../AGENTS.md)（Codex Agent 入口） |
| 启动命令 / 环境准备 | 本页下方“快速起步” |
| 系统架构与数据流 | [`../architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md) |
| 表结构 + sync_status / WordState 状态机 | [`../architecture/DATABASE_DESIGN.md`](../architecture/DATABASE_DESIGN.md) |
| 启动分支决策（用户/云端/管理员） | [`../architecture/decision_flow.md`](../architecture/decision_flow.md) |

## 主题文档

| 主题 | 文档 |
| --- | --- |
| 同步机制（前后台策略、队列、退出收尾） | [`AUTO_SYNC.md`](AUTO_SYNC.md) |
| 同步优化历史决策与场景矩阵 | [`SYNC_OPTIMIZATION_PLAYBOOK.md`](SYNC_OPTIMIZATION_PLAYBOOK.md) / [`SYNC_PRIORITY_MATRIX.md`](SYNC_PRIORITY_MATRIX.md) |
| 日志系统接入与级别 | [`LOGGING.md`](LOGGING.md) |
| 历史决策记录（为什么不那样做） | [`DECISIONS.md`](DECISIONS.md) |
| 贡献规范 / 新增 AI 提供商 / 凭证处理 | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| 运行期 WAL / 游标 / 重试铁律 | [`../../database/README.md`](../../database/README.md) |

## 快速起步

如果你只是想尽快跑起来，按这个最短路径即可：

```bash
pip install -r requirements.txt
python tools/preflight_check.py --user <username>
python -m pytest tests/ -v --tb=short -m "not slow"
python main.py
```

说明：

- 先确认 `.env` 或 profile 配置已就绪。
- 若要验证同步链路行为，先读 `AUTO_SYNC.md` 再改流程。
- 这部分只保留最短可执行路径，不再单独维护 `QUICK_START.md`。

## 子领域工作区

| 子领域 | 入口 |
| --- | --- |
| Web UI 设计 / 任务推进 | [`web_ui/README.md`](web_ui/README.md) — Web UI 工作区导航（chapters 任务文档） |
| 数据库内部协议 | [`../../database/README.md`](../../database/README.md) |

## 进行中的重构

| 文档 | 角色 |
| --- | --- |
| [`REFACTOR_PROGRESS.md`](REFACTOR_PROGRESS.md) | 阶段 checklist + 决策落定 |

## 历史归档

需要查阅已完成 / 已废弃的内容：

- 阶段历史：[`../history/phases/`](../history/phases/)（CONCURRENCY/EMBEDDED_REPLICAS/WAL_CONFLICT 等已完成阶段）
- Web UI 旧版散落文档：[`../history/web_ui_legacy/`](../history/web_ui_legacy/)（2026-05-02 之前的根级 WEB_UI_*.md，已被 `web_ui/` 工作区取代）
- 项目快照：[`../history/snapshots/`](../history/snapshots/)（PROJECT_STATUS.md 等带日期的状态快照）

## 调试入口

| 想看什么 | 位置 |
| --- | --- |
| 运行日志 | `logs/<user>.log` |
| 个人学习数据库 | `data/history-<user>.db`（+ `.db-wal` / `.db-shm`） |
| 用户凭据 | `data/profiles/<user>.env` |
| 进程锁 | `data/.process.lock` |
| 测试数据库 | `data/test-<user>.db` |

## 何时改本文件

- **新增主题文档**：在对应表格新增一行。**不要把内容直接写进来**。
- **文档归档**：在「历史归档」表新增条目。
- **链接失效**：直接修。
- **要改流程规则 / 红线**：去 `AI_CONTEXT.md`，**不**改这里。
