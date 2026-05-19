# Progress — Dual-Database Refactoring

## Session Log

### 2026-05-19 — Planning Phase

- **Actions:** Explored codebase (study_workflow.py, notes_repo.py, feature_flags.py, settings.py, config.py, schema.py, migrations/, tests/)
- **Findings:** Recorded in `findings.md`
- **User Decisions:**
  - Migration numbering: V005+ (semantic naming)
  - Integration: per-word lookup within batches, CacheNetworkError triggers batch circuit breaker
  - is_customized: new `update_memory_aid` function in notes_repo.py
- **Output:** Created `task_plan.md` (12 tasks), `findings.md`

## Tasks Status

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Register Feature Flag & Settings | pending | |
| 2 | Add Cache Config Exports | pending | |
| 3 | Create GlobalCacheClient | pending | |
| 4 | Create V005_is_customized Migration | pending | |
| 5 | Add update_memory_aid | pending | |
| 6 | Create WordLookup Orchestrator | pending | |
| 7 | Create V006_seed_global_cache | pending | |
| 8 | Integrate into study_workflow | pending | |
| 9 | Update SQL Constants for is_customized | pending | |
| 10 | Update conftest.py | pending | |
| 11 | Integration Tests | pending | |
| 12 | Full Test Suite Verification | pending | |

## Code Review Feedback

### 2026-05-19 — Task 8 Step 2 _run_ai_batch 严重逻辑 Bug（已修复）

**问题：** 原设计中 L1 命中的词没有 append 到结果列表，导致被 `words_needing_ai` 误判为未处理词，触发批量 AI 二次调用 → Token 浪费。

**根本原因：**
- 原代码只有 L2/L3 路径有 `cached_results.append(result.note)`
- L1 命中的词只打了 debug 日志，没有收集
- 末尾的 `words_needing_ai` 批量 AI 补刀逻辑又把 L1 命中的词重新送去调 AI

**修复方案：**
1. 所有 L1/L2/L3 命中统一 append 到 `ai_results`
2. 移除末尾的 `words_needing_ai` 批量 AI 补刀逻辑（每个词在循环内已被 WordLookup 完整处理）

**Review 来源：** 用户直接 review plan 文件并提供修正代码

### 2026-05-19 — Task 6 _find_local 数据串位隐患（已修复）

**问题：** `_find_local` 使用 `SELECT n.*` + 硬编码 `columns` 列表按索引映射。`SELECT *` 的返回顺序依赖物理表定义，一旦迁移添加列的顺序与硬编码列表不一致，就会发生静默数据串位（比如把时间戳塞进整型字段）。

**根因：** 这是现有代码库的模式（`community_lookup.py`、`notes_repo.py` 都用了 `SELECT *`），但新代码不应该继承这个历史遗留。

**修复方案：**
1. 改用显式列名的 SELECT 语句（`SELECT voc_id, spelling, ...`）
2. SQL 中的列名顺序和 `columns` 数组保持严格一一对应
3. 注释说明：未来迁移加列时需同步更新此处

**Review 来源：** 用户交叉对比 Task 6 columns 列表与 Task 9 NOTE_UPSERT_SQL 字段映射后发现

## Errors Encountered

(none yet — code not yet implemented)
