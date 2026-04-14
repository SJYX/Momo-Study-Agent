# 系统架构

> 这里描述的是代码模块边界和调用关系，不重复实现细节。

## 模块边界

- [main.py](../../main.py) 负责主菜单、任务分发和运行时编排。
- [config.py](../../config.py) 负责路径、用户 profile 和全局配置加载。
- [core/config_wizard.py](../../core/config_wizard.py) 负责新用户初始化、凭证保存和预检提示。
- [core/db_manager.py](../../core/db_manager.py) 负责本地 SQLite、Turso、Hub 与同步。
- [core/maimemo_api.py](../../core/maimemo_api.py) 负责墨墨 API 调用封装。
- [core/gemini_client.py](../../core/gemini_client.py) 与 [core/mimo_client.py](../../core/mimo_client.py) 负责 AI 助记生成。
- [core/iteration_manager.py](../../core/iteration_manager.py) 负责薄弱词识别、选优和重炼。
- [core/logger.py](../../core/logger.py) 负责日志输出与性能统计。

## 主流程调用链

```mermaid
flowchart TD
  A[启动 main.py] --> B[加载 config.py]
  B --> C[初始化 StudyFlowManager]
  C --> D[同步检查 sync_databases(dry_run=True)]
  D --> E[主菜单]
  E --> F[今日任务 / 未来计划]
  E --> G[智能迭代]
  E --> H[同步并退出]
  F --> I[批量拉取墨墨任务]
  I --> J[AI 生成助记]
  J --> K[写入 ai_word_notes / processed_words]
  K --> L[后台同步]
  G --> M[WeakWordFilter 筛选]
  M --> N[IterationManager 选优/重炼]
  N --> O[同步云词本和迭代记录]
```

## 关键运行规则

- AI 提供商由 `AI_PROVIDER` 决定，当前支持 `mimo` 和 `gemini`。
- 数据同步是“本地 SQLite + Turso”双轨，不是纯云端。
- 中央 Hub 是用户元数据与审计层，独立于用户学习数据仓库。
- 主流程允许后台同步，退出前会再做一次安全同步。

## 相关文档

- [DATA_FLOW.md](DATA_FLOW.md)
- [DATABASE_DESIGN.md](DATABASE_DESIGN.md)
- [../dev/AI_CONTEXT.md](../dev/AI_CONTEXT.md)