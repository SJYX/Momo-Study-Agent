# 阶段性项目归档（Phases Archive）

本目录是 **已完成** 的一次性项目记录。这些文档**不是**活动指令，阅读时请当成"2026 年某阶段的快照"，不要据此给出"你现在应该做 X"的建议。

## 如何使用本目录

- 想了解"现在怎么用/怎么改代码" → 看 [`../../dev/AI_CONTEXT.md`](../../dev/AI_CONTEXT.md)（规则）+ [`../../architecture/ARCHITECTURE.md`](../../architecture/ARCHITECTURE.md)（结构）
- 想了解"某功能为什么是现在这样" → 看下表找对应的历史文档
- **永远不要**把这里的 TODO / 下一步 / 待办清单当作当前任务

## 文档清单

| 归档文档 | 时期 | 它解决了什么 | 今天在哪儿找同等能力 |
| --- | --- | --- | --- |
| [PHASE_2_WRITE_SIMPLIFICATION.md](PHASE_2_WRITE_SIMPLIFICATION.md) | 2026-04 | Embedded Replicas 迁移 Phase 2：消除双写逻辑 | `database/momo_words.py` 各写函数（单写走 ER 自动同步） |
| [PHASE_3_SYNC_OPTIMIZATION.md](PHASE_3_SYNC_OPTIMIZATION.md) | 2026-04 | 用 `conn.sync()` 替代 600 行手工同步代码 | `database/momo_words.py::sync_databases` / `sync_hub_databases` |
| [PHASE_4_TESTING_VALIDATION.md](PHASE_4_TESTING_VALIDATION.md) | 2026-04-17 | Phase 0-3 迁移的全量回归测试验证 | `tests/`（保持绿的回归口径：`pytest -m "not slow"`） |
| [EMBEDDED_REPLICAS_PHASE_0_2_COMPLETION.md](EMBEDDED_REPLICAS_PHASE_0_2_COMPLETION.md) | 2026-04-17 | libsql-client → libsql 迁移 + 连接层重构完成报告 | `database/connection.py`（`_get_main_write_conn_singleton` 等） |
| [EMBEDDED_REPLICAS_MIGRATION.md](EMBEDDED_REPLICAS_MIGRATION.md) | 2026-04 | 迁移前分析稿（架构诊断 + 方案设计） | 结论已落地；原理讲述见 `../../architecture/ARCHITECTURE.md` 的同步模型段 |
| [OPEN_SOURCE_TRANSITION_PLAN.md](OPEN_SOURCE_TRANSITION_PLAN.md) | 2026-04 | 开源转向：从管理员代建凭证 → 用户自配 | `.env.example`、`core/config_wizard.py`（当前已是用户自配模式） |
| [WAL_CONFLICT_FIX.md](WAL_CONFLICT_FIX.md) | 2026-04 | SQLite WAL frame insert conflict 修复 | 精华已落地到 `../../../database/README.md`（PRAGMA + 重试守则） |
| [CONCURRENCY_REFACTOR.md](CONCURRENCY_REFACTOR.md) | 2026-04 | 高并发重构：ThreadLocal 读 + 写队列 + 单守护线程 | 精华已落地到 `../../architecture/ARCHITECTURE.md`（并发模型段） |
| [DOCS_CLEANUP_PLAN.md](DOCS_CLEANUP_PLAN.md) | 2026-04-21 | 本次文档清理工作的方案文档 | 已执行，结果即当前 `docs/` 结构 |

## 维护规则

- 本目录文件 **只新增，不修改**（改内容 = 篡改历史记录）。
- 如果某个历史文档的技术结论和今天代码矛盾了，**不要回来改这里**；应该更新 `AI_CONTEXT.md` 或 `ARCHITECTURE.md`，然后在本索引表的"今天在哪儿找"列里指向新位置。
- 新增归档时同时在 `docs/CHANGELOG.md` 留一条"XXX 已完成，归档到 history/phases/"。
