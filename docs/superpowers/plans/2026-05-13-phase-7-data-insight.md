# Phase 7 数据洞察与基建完善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完善 AI 批次元数据统计，扩充数据库 Schema 以全量保存学习进度/明细、远端 ID，并补充缺失的索引和枚举类型。

**Architecture:**
本次升级（Phase 7）采取严格的关系化扩充策略。所有新增列和新表通过 `database/migrations/V002_phase7_data_insight.py` 迁移脚本推进，并在 `database/schema.py` 的 v0 骨架中体现。同时修改 `gemini_client`、`mimo_client` 补齐延迟和 Token 统计，修改 `study_workflow` 将 `next_study_date` 等增量字段透传至数据库。由于涉及多表关联和统计增强，各表索引亦将同步完善。

**Tech Stack:** Python 3.12, SQLite, PRAGMA user_version, Pydantic (DTOs).

---

### Task 1: 完善 AI 批次元数据 (Latency & Tokens)

**Files:**
- Modify: `core/gemini_client.py`
- Modify: `core/mimo_client.py`
- Modify: `database/dto.py`
- Modify: `database/notes_repo.py`
- Modify: `core/study_workflow.py`

- [ ] **Step 1: 修改 DTO 和 Repo 签名**
在 `database/dto.py` 中的 `AIBatchData` TypedDict 已有 `total_latency_ms`, `prompt_tokens`, `completion_tokens`，无需修改。
检查 `database/notes_repo.py` 的 `save_ai_batch` 实现，确保写入了这些字段。

- [ ] **Step 2: 修改 GeminiClient**
在 `core/gemini_client.py` 中的 `generate_with_instruction` 方法内记录耗时，并在 `generate_mnemonics` 的返回值 metadata 中带出。

```python
# core/gemini_client.py 约 39 行
        instr = instruction or self._load_instruction()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                start_time = time.time()
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=instr
                    )
                )
                end_time = time.time()
                text = response.text.strip()
                usage = response.usage_metadata
                
                metadata = {
                    "request_id": None,
                    "finish_reason": str(response.candidates[0].finish_reason) if response.candidates else "UNKNOWN",
                    "prompt_tokens": usage.prompt_token_count if usage else 0,
                    "completion_tokens": usage.candidates_token_count if usage else 0,
                    "total_tokens": usage.total_token_count if usage else 0,
                    "total_latency_ms": int((end_time - start_time) * 1000)
                }
                return text, metadata
```

- [ ] **Step 3: 修改 MimoClient**
在 `core/mimo_client.py` 中同样记录耗时（原代码已有 `started_at = time.time()`，需补齐 `total_latency_ms`）。

```python
# core/mimo_client.py 约 78 行
                result = response.json()
                end_time = time.time()
                text = result["choices"][0]["message"]["content"].strip()
                usage = result.get("usage", {})
                
                metadata = {
                    "request_id": result.get("id"),
                    "finish_reason": result["choices"][0].get("finish_reason"),
                    "prompt_tokens": usage.get('prompt_tokens', 0),
                    "completion_tokens": usage.get('completion_tokens', 0),
                    "total_tokens": usage.get('total_tokens', 0),
                    "total_latency_ms": int((end_time - started_at) * 1000)
                }
                return text, metadata
```

- [ ] **Step 4: 修改 StudyWorkflow 调用**
在 `core/study_workflow.py` 的 `_run_ai_batch` 和后续保存逻辑中透传 tokens。

```python
# core/study_workflow.py 约 291 行
                    batch_id = str(uuid.uuid4())
                    ok = save_ai_batch(
                        {
                            "batch_id": batch_id,
                            "request_id": metadata.get("request_id"),
                            "ai_provider": AI_PROVIDER,
                            "model_name": self.ai_client.model_name,
                            "prompt_version": getattr(self.ai_client, "prompt_version", ""),
                            "batch_size": len(batch),
                            "total_latency_ms": metadata.get("total_latency_ms", 0),
                            "prompt_tokens": metadata.get("prompt_tokens", 0),
                            "completion_tokens": metadata.get("completion_tokens", 0),
                            "total_tokens": metadata.get("total_tokens", 0),
                            "finish_reason": metadata.get("finish_reason"),
                        }
                    )
```

- [ ] **Step 5: 提交**
```bash
git add core/gemini_client.py core/mimo_client.py core/study_workflow.py
git commit -m "fix: record latency and separate tokens for AI batches"
```

### Task 2: 数据库 Schema 与 V002 迁移脚本

**Files:**
- Create: `database/migrations/V002_phase7_data_insight.py`
- Modify: `database/schema.py`

- [ ] **Step 1: 编写 V002 迁移脚本**
包含新增列、新表和缺失的索引（满足 4.3, 4.4, 4.5, 4.6, 4.7, 4.8）。要求幂等。

```python
# database/migrations/V002_phase7_data_insight.py
from typing import Any

def apply(cur: Any) -> None:
    # 4.3 & 4.8 Add next_study_date, category, error_count to word_progress_history
    try:
        cur.execute("ALTER TABLE word_progress_history ADD COLUMN next_study_date TIMESTAMP")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE word_progress_history ADD COLUMN category TEXT")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE word_progress_history ADD COLUMN error_count INTEGER DEFAULT 0")
    except Exception:
        pass
        
    # 4.4 Maimemo remote refs table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS maimemo_remote_refs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voc_id TEXT NOT NULL,
            ref_type TEXT NOT NULL,
            remote_id TEXT NOT NULL,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_remote_refs_voc ON maimemo_remote_refs(voc_id, ref_type)")
    except Exception:
        pass

    # 4.5 Study records table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS study_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voc_id TEXT NOT NULL,
            study_date DATE NOT NULL,
            review_time TIMESTAMP,
            review_status TEXT,
            familiarity_change REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_study_records_voc_date ON study_records(voc_id, study_date)")
    except Exception:
        pass

    # 4.6 Sync status index
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_sync ON ai_word_notes (sync_status, content_origin)")
    except Exception:
        pass

    # 4.7 Progress latest index
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_progress_latest ON word_progress_history (voc_id, created_at DESC)")
    except Exception:
        pass
```

- [ ] **Step 2: 更新 Schema 初始化骨架**
在 `database/schema.py` 中的 `_create_tables` 和 `_init_hub_schema` 中加入对应的新表和索引。

```python
# database/schema.py (修改点示意，加入新表和列)
# 在 word_progress_history 的 CREATE TABLE 语句增加:
# "next_study_date TIMESTAMP, category TEXT, error_count INTEGER DEFAULT 0, "
#
# 在 _create_tables 末尾增加：
    cur.execute(
        "CREATE TABLE IF NOT EXISTS maimemo_remote_refs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT NOT NULL, ref_type TEXT NOT NULL, "
        "remote_id TEXT NOT NULL, synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_remote_refs_voc ON maimemo_remote_refs(voc_id, ref_type)")
    except Exception:
        pass

    cur.execute(
        "CREATE TABLE IF NOT EXISTS study_records ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT NOT NULL, study_date DATE NOT NULL, "
        "review_time TIMESTAMP, review_status TEXT, familiarity_change REAL, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_study_records_voc_date ON study_records(voc_id, study_date)")
    except Exception:
        pass

    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_sync ON ai_word_notes (sync_status, content_origin)")
    except Exception:
        pass
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_progress_latest ON word_progress_history (voc_id, created_at DESC)")
    except Exception:
        pass
```

- [ ] **Step 3: 修改 Hub 数据库 (Task 4.10)**
在 `database/schema.py` 中的 `_init_hub_schema` 内，我们无需修改 admin_logs 的建表，因为它已经是 TEXT。我们确保调用处存 JSON 即可（在之后的重构中体现，本阶段 Schema 已经足够）。

- [ ] **Step 4: 测试迁移脚本**
运行: `python -m tools.preflight_check --user test_user` (确保无错并能执行迁移)

- [ ] **Step 5: 提交**
```bash
git add database/migrations/V002_phase7_data_insight.py database/schema.py
git commit -m "feat(db): schema expansion for data insights (Phase 7)"
```

### Task 3: 提取并存储 Maimemo 学习进度增量字段

**Files:**
- Modify: `database/dto.py`
- Modify: `database/progress_repo.py`
- Modify: `core/study_workflow.py`

- [ ] **Step 1: 修改 ProgressSnapshot DTO**
```python
# database/dto.py 约 82 行
class ProgressSnapshot(TypedDict, total=False):
    """log_progress_snapshots() 的列表元素形状。"""
    voc_id: Union[str, int]
    short_term_familiarity: float
    long_term_familiarity: float
    voc_familiarity: float
    review_count: int
    next_study_date: Optional[str]
    category: Optional[str]
    error_count: Optional[int]
```

- [ ] **Step 2: 修改 Repo 写入**
在 `database/progress_repo.py` 中找到 `log_progress_snapshots` 并将新列加入 `INSERT` 语句。

- [ ] **Step 3: 修改业务解析**
在 `core/study_workflow.py` (如 `_process_results` 或获取 `get_today_items` 后的处理) 提取 `next_study_date`, `category`, `error_count` 并传给 snapshot 记录逻辑。如果是通过 `WordService`，则需要一并修改 `WordService.enrich_with_states` 的回填机制，使其传递这些新属性。

- [ ] **Step 4: 提交**
```bash
git add database/dto.py database/progress_repo.py core/study_workflow.py
git commit -m "feat(progress): record next_study_date, category and error_count"
```

### Task 4: 添加 WordState 和 SyncStatus 枚举

**Files:**
- Modify: `database/word_state.py`

- [ ] **Step 1: 添加 SyncStatus Enum**
在 `database/word_state.py` 增加正式的 `SyncStatus` 枚举。

```python
# database/word_state.py
from enum import IntEnum

class SyncStatus(IntEnum):
    """AI 笔记同步状态 6 态机。"""
    UNSYNCED = 0
    SYNCED = 1
    CONFLICT = 2
    QUEUED = 3
    SYNCING = 4
    FAILED = 5
```

- [ ] **Step 2: 替换魔术数字**
修改 `database/word_state.py` 中的 `derive_state` 和 `state_to_where_clause`，将魔术数字替换为 `SyncStatus` 常量。

- [ ] **Step 3: 提交**
```bash
git add database/word_state.py
git commit -m "refactor(db): add formal SyncStatus enum to word_state.py"
```

### Task 5: User Stats 更新时机梳理 (Task 4.9)

**Files:**
- Modify: `core/sync_manager.py` (或 `sync_service.py`)

- [ ] **Step 1: 定位 Hub 写入逻辑**
由于 `user_stats` 是全局 Hub 数据库的统计信息，应在本地同步完成后通过 `sync_hub_databases()` 或者特定的 stats updater 进行写入。在 `core/sync_service.py` 找到同步的统计点，使用 `connection._get_hub_conn()` 写入增量数据：`total_sync_count + 1` 等。
*(此 Task 依据具体代码库现状在子代理实施阶段细化，只需确保同步时更新 user_stats 的 total_sync_count 和 last_activity_at)*

- [ ] **Step 2: 提交**
```bash
git commit -am "feat(sync): increment user_stats on sync completion"
```

---

## Review & Handoff
本计划涵盖了问题 4.1 到 4.10，涉及 1 个 Schema 迁移，新增了 2 张表和 3 个字段，并补齐了客户端丢失的 Tokens 和 Latency 统计。存储清理由于用户选择暂不处理而跳过。

计划已就绪并保存。建议使用 **Subagent-Driven** 模式按 Task 逐个实施，以保证每个步骤的数据库事务和写入边界安全。