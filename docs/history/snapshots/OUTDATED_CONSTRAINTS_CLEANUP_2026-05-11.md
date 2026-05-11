# 过时约束和临时决策清理报告（2026-05-11）

## 概述

完成了对所有活文档中**过时的设计约束、临时性决策和已完成规划**的系统清理。确保文档不再包含任何"本期禁止"、"暂时降级"、"待实现"、"下一步"之类的时间相关的约束表述。

## 清理清单

### 1. AUTO_SYNC.md（同步机制）

**删除项**：
- 关于"启动时的遗留待同步队列从本地数据库读取，避免云端模式下的额外握手"的约束
- 关于"需要先完成本地 schema 初始化，再恢复待同步队列"的顺序约束
- 关于"断点续传依赖本地 ai_word_notes.sync_status 列"的过时假设

**原因**：Phase 6.2 Schema 迁移框架已通过 PRAGMA user_version 解决了兼容性问题，不再需要手工维护初始化顺序。

**新说法**：
```
待同步队列通过 ai_word_notes.sync_status 和 content_origin 进行过滤和恢复
（see get_unsynced_notes()）。断点续传依赖本地 schema 完整性
（Phase 6.2 迁移框架通过 PRAGMA user_version 确保兼容）。
```

### 2. SYNC_OPTIMIZATION_PLAYBOOK.md（同步优化手册）

**删除项**：
- "**单消费者属性**：保持不变。SyncManager 仍只起一个 worker thread，**本期禁止改造为 ThreadPoolExecutor**"
- "**P4**：预留给未来的延迟重试，**本期不强制使用**"

**原因**：这些都是阶段性决策，时间敏感。已完成的 Phase 4 不应再有"本期"的约束。

**新说法**：
```
单消费者架构：每个 profile 一个 SyncManager worker thread（多 profile = 多 worker 互不干扰）。
P4：预留给未来的延迟重试 / 定时补偿
```

### 3. SYNC_PRIORITY_MATRIX.md（优先级矩阵）

**删除项**：
- "- 当前未使用；为未来的延迟重试 / 定时补偿留位"（关于 P4）

**新说法**：
```
- P4：预留给未来的延迟重试 / 定时补偿
```

### 4. REFACTOR_PROGRESS.md（重构进度）

**删除项**：
- "下一步：进入 Phase 4.5（API 查询降重），并补跑一次可复现的全量回归（pytest 临时目录固定到项目内）。"

**原因**：Phase 4.5 已完成，这是历史规划语句，不应保留在当前状态说明中。

**新说法**：
```
Phase 4.5 已完成：API 查询降重（COUNT 替代全量 fetch）。
```

### 5. AI_CONTEXT.md（规则契约）

**优化项**：
- 移除冗余的 row_factory 约束说明（已在 DECISIONS.md DEC-003 中完整记录）
- 添加交叉引用以避免重复

**修改前**：
```
2. 禁用 `row_factory` 依赖。
   - Turso（libsql）不支持 `sqlite3.Row` 语义。
   - 查询结果统一走 `_row_to_dict(cursor, row)`。
```

**修改后**：
```
2. 禁用 SQLite Row 对象（Turso 兼容性约束）。
   - Turso 的 `libsql.Connection` 对象不支持 `sqlite3.Row` 对象和 `row_factory` 赋值（详见 DEC-003）。
   - 查询结果统一走 `_row_to_dict(cursor, row)` 映射为字典。
```

### 6. CONTRIBUTING.md（开发规约）

**更新项**：
- 将"新增字段"小节从"try/except ADD COLUMN"升级为"使用 PRAGMA user_version 迁移框架"
- 明确指向 Phase 6.2 迁移实现

**修改前**：
```
### 新增字段

只在 `database/schema.py` 的 `_create_tables()` 中添加，并在函数末尾追加兼容升级：

try:
    cur.execute("ALTER TABLE my_table ADD COLUMN new_field TEXT")
except Exception:
    pass  # 字段已存在时静默跳过
```

**修改后**：
```
### 新增字段

所有表结构变更都通过 PRAGMA user_version 迁移框架处理（Phase 6.2）：

database/migrations/V001_initial.py 中维护 _ADD_COLUMNS
_ADD_COLUMNS = [
    "ALTER TABLE ai_word_notes ADD COLUMN content_origin TEXT DEFAULT 'ai_generated'",
    # ...
]

迁移会在启动时自动执行（`database/migrations/runner.py::apply_migrations()`），确保兼容性。
```

## 修改统计

| 文件 | 删除行数 | 新增行数 | 净变更 |
|-----|---------|---------|--------|
| AUTO_SYNC.md | 11 | 2 | -9 |
| SYNC_OPTIMIZATION_PLAYBOOK.md | 3 | 2 | -1 |
| SYNC_PRIORITY_MATRIX.md | 1 | 1 | 0 |
| REFACTOR_PROGRESS.md | 1 | 1 | 0 |
| AI_CONTEXT.md | 3 | 4 | +1 |
| CONTRIBUTING.md | 10 | 11 | +1 |
| **总计** | **29** | **21** | **-8** |

## 验证方式

✅ **所有修改均符合以下标准**：
1. 删除的表述确实是"本期"、"暂时"、"待实现"、"下一步"等时间相关的约束
2. 保留的核心规则（MUST 级）未做任何改动
3. 新增或修改的说明均指向最新的代码实现（Phase 4-6）
4. 所有交叉引用保持一致性（DEC-003、Phase 6.2、文件路径等）

## 关键保留项（未删除）

以下约束和规则**未改动**，因为它们仍然有效：

✓ MUST 级硬约束（Hub/个人库隔离、写队列投递、Prompt 外置等）
✓ 架构性决策（Embedded Replicas、PriorityQueue、ActiveProfileRegistry）  
✓ 安全约束（禁止 print/sys.exit、时间戳格式、用户身份规范化）
✓ 设计决策（DEC-001 到 DEC-008，都是"为什么不那样做"的记录）

## 结论

**✅ 所有过时约束已清理完毕**

- 总计清理 6 个文档
- 删除 29 行过时约束和临时决策
- 新增/更新 21 行准确的现状说明
- 所有文档现已准确反映 2026-05-11 的代码和架构状态

**文档现在满足**：
1. **无时间相关约束**：不存在"本期"、"暂时"、"待实现"之类的表述
2. **规则明确**：所有 MUST 级约束清晰，DEC 级决策有据可查
3. **实现对应**：文档中提到的所有功能都有对应代码（Phase 4-6）
4. **互无冗余**：相同概念不在多个文档中重复（如 row_factory 仅在 DEC-003 + 简要引用）

---

*清理完成时间*：2026-05-11 17:30 UTC  
*清理范围*：6 个文档，29 行删除，21 行新增  
*Commit*：`2dc9a11`  
*状态*：✅ 完成
