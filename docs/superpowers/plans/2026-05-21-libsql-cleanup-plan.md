# libsql 后端技术债全面清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清理全系统 libsql/pyturso 相关死代码、重复代码、误命名，保留 libsql fallback 兼容路径

**Architecture:** 按文件组分批清理，每组完成后编译检查 + 回归测试。保留所有 libsql fallback 路径和 Protocol 分支结构。

**Tech Stack:** Python 3.12+, pytest, SQLite (libsql/pyturso backends)

**Spec:** `docs/superpowers/specs/2026-05-21-libsql-cleanup-design.md`

---

## 文件变更总览

| 操作 | 文件 |
|------|------|
| **删除** | `database/legacy.py` |
| **删除** | `compat/__init__.py`, `compat/gemini_client.py`, `compat/maimemo_api.py` |
| **修改** | `database/connection.py`（~7 项清理） |
| **修改** | `database/utils.py`（删除未使用函数 + 清理无意义条件） |
| **修改** | `database/session.py`（删死 import） |
| **修改** | `database/community_lookup.py`（删死 import + 重命名参数） |
| **修改** | `database/sync_service.py`（重命名函数 + 字符串） |
| **修改** | `core/log_config.py`（删除后半段重复定义） |
| **修改** | `core/mimo_client.py`（删死函数） |
| **修改** | `core/iteration_manager.py`（提取重复 import） |
| **修改** | `tests/core/test_gemini_client.py`（更新 import 路径） |
| **修改** | `tests/core/test_maimemo_api.py`（更新 import 路径） |
| **修改** | `tests/core/test_apple.py`（更新 import 路径） |
| **修改** | `docs/architecture/ARCHITECTURE.md`（移除 legacy.py 条目） |

---

## Task 1: 删除 database/legacy.py

**文件:**
- Delete: `database/legacy.py`

**验证:** grep 确认无代码 import legacy（CHANGELOG.md 和 ARCHITECTURE.md 有引用但只是文档）。

- [ ] **Step 1: Verify no code imports legacy**

```bash
# 搜索所有 Python 文件，确认无 import
```

Run: `grep -rn "from database.legacy\|import database.legacy\|from \.legacy\|import legacy" --include="*.py" | grep -v legacy.py | grep -v "CHANGELOG\|ARCHITECTURE\|AI_CONTEXT\|CONTRIBUTING\|README\|superpowers"`

Expected: 无结果（只有文档引用，无代码引用）

- [ ] **Step 2: Delete the file**

```bash
git rm database/legacy.py
```

- [ ] **Step 3: Run py_compile on dependent files**

```bash
python -m py_compile database/connection.py
python -m py_compile database/momo_words.py
python -m py_compile database/hub_users.py
```

Expected: 全部 PASS

- [ ] **Step 4: Run regression tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: PASS（legacy.py 无代码依赖）

- [ ] **Step 5: Commit**

```bash
git add database/legacy.py
git commit -m "chore: remove dead database/legacy.py — no code imports it"
```

---

## Task 2: 删除 compat/ 包 + 更新测试 import

**文件:**
- Delete: `compat/__init__.py`, `compat/gemini_client.py`, `compat/maimemo_api.py`
- Modify: `tests/core/test_gemini_client.py:3`
- Modify: `tests/core/test_maimemo_api.py:2`
- Modify: `tests/core/test_apple.py:10`

- [ ] **Step 1: Update test_gemini_client.py import**

Change line 3:
```python
# BEFORE:
from compat.gemini_client import GeminiClient, _extract_json_array
# AFTER:
from core.gemini_client import GeminiClient, _extract_json_array
```

- [ ] **Step 2: Update test_maimemo_api.py import**

Change line 2:
```python
# BEFORE:
from compat.maimemo_api import MaiMemoAPI
# AFTER:
from core.maimemo_api import MaiMemoAPI
```

- [ ] **Step 3: Update test_apple.py import**

Change line 10:
```python
# BEFORE:
from compat.gemini_client import GeminiClient
# AFTER:
from core.gemini_client import GeminiClient
```

- [ ] **Step 4: Run affected tests**

```bash
python -m pytest tests/core/test_gemini_client.py tests/core/test_maimemo_api.py tests/core/test_apple.py -v --tb=short
```

Expected: PASS

- [ ] **Step 5: Delete compat/ directory**

```bash
git rm -r compat/
```

- [ ] **Step 6: Commit**

```bash
git add tests/core/test_gemini_client.py tests/core/test_maimemo_api.py tests/core/test_apple.py compat/
git commit -m "chore: remove compat/ shim package — update tests to import from core/ directly"
```

---

## Task 3: 清理 core/log_config.py 重复定义

**文件:**
- Modify: `core/log_config.py`（删除 lines 160-259 的重复块）

- [ ] **Step 1: Read the file to identify the duplicate block**

```bash
# The second half (lines 160+) duplicates lines 60-158:
# ENV_CONFIGS, get_config, load_yaml_config, save_yaml_config, merge_configs, get_full_config
```

Run: `wc -l core/log_config.py`

- [ ] **Step 2: Remove the duplicate block (lines 160 to end)**

Delete everything from line 160 onwards. Keep lines 1-159.

- [ ] **Step 3: Compile check**

```bash
python -m py_compile core/log_config.py
```

Expected: PASS

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/log_config.py
git commit -m "chore: remove duplicate definitions in log_config.py — second half overwrote first"
```

---

## Task 4: 清理 core/ 死函数和重复 import

**文件:**
- Modify: `core/mimo_client.py`（删除 `_extract_json_array` 死函数）
- Modify: `core/iteration_manager.py`（提取重复 json_repair import）

- [ ] **Step 1: Delete _extract_json_array from mimo_client.py**

在 `core/mimo_client.py` 中找到 `_extract_json_array` 函数（约 lines 203-217），确认文件内无调用后删除。

```bash
# 验证文件内无调用
grep -n "_extract_json_array" core/mimo_client.py
```

Expected: 只有函数定义行，无调用行

删除该函数。

- [ ] **Step 2: Compile check**

```bash
python -m py_compile core/mimo_client.py
```

Expected: PASS

- [ ] **Step 3: Extract duplicate json_repair import in iteration_manager.py**

在 `core/iteration_manager.py` 中：
- 约 lines 198-203: `_handle_level_1_selection` 中有 `try: import importlib; json_repair = importlib.import_module("json_repair")`
- 约 lines 263-268: `_handle_level_2_refinement` 中有相同的 import 块

将两个函数内的 import 块删除，改为模块顶部统一 import：

```python
# 在文件顶部 import 区域添加（如果还没有的话）：
try:
    import json_repair
except ImportError:
    json_repair = None
```

然后在两个函数中直接使用 `json_repair`（模块级变量）。

- [ ] **Step 4: Compile check**

```bash
python -m py_compile core/iteration_manager.py
```

Expected: PASS

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/mimo_client.py core/iteration_manager.py
git commit -m "chore: remove dead _extract_json_array from mimo_client + dedupe json_repair import in iteration_manager"
```

---

## Task 5: 清理 database/connection.py — 删除 fallback 错误分类

**文件:**
- Modify: `database/connection.py` lines 50-108

**风险修正：** 当前 import 只导入 3 个函数（`_backup_broken_database_file`, `_is_sqlite_data_corruption_error`, `_is_sqlite_malformed_error`），fallback block 额外定义了 `_is_pyturso_db_missing_error` 和 `_is_pyturso_db_corruption_error` 但它们仅在 `_is_sqlite_malformed_error` 内部调用，不需要模块级 import。因此只需保持 3 个函数的 import，不需加到 5 个。

- [ ] **Step 1: 确认 utils 导入可用**

```bash
python -c "from database.utils import _backup_broken_database_file, _is_sqlite_data_corruption_error, _is_sqlite_malformed_error; print('OK')"
```

Expected: OK

- [ ] **Step 2: 将 utils 导入改为常规 import，删除 fallback block**

```python
# BEFORE (lines 50-108):
try:
    from core.logger import get_logger
except ImportError:
    ...

# Optional utility imports (to be fully moved into database/utils.py later).
try:
    from .utils import (
        _backup_broken_database_file,
        _is_sqlite_data_corruption_error,
        _is_sqlite_malformed_error,
    )
except Exception:
    def _is_pyturso_db_missing_error(msg): ...  # 37 lines fallback

# AFTER:
try:
    from core.logger import get_logger
except ImportError:
    ...

from .utils import (
    _backup_broken_database_file,
    _is_sqlite_data_corruption_error,
    _is_sqlite_malformed_error,
)
```

注意：不需要导入 `_is_pyturso_db_missing_error` 和 `_is_pyturso_db_corruption_error`——它们仅在 `_is_sqlite_malformed_error` 内部调用，后者已导入。

- [ ] **Step 3: Compile check**

```bash
python -m py_compile database/connection.py
```

Expected: PASS

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database/connection.py
git commit -m "chore: remove fallback error classifiers from connection.py — use utils.py directly"
```

---

## Task 6: 清理 database/connection.py — 删除未使用全局变量和重复函数

**文件:**
- Modify: `database/connection.py`
  - 删除 lines 111-113 的 `TURSO_DB_URL = None`、`TURSO_AUTH_TOKEN = None`、`TURSO_DB_HOSTNAME = None`（但保留 lines 114-116 的 `TURSO_TEST_*`）
  - 删除 `_normalize_turso_url`（lines 170-178），改为从 utils 导入

**验证点：**
- `TURSO_DB_URL/AUTH_TOKEN/HOSTNAME` 是 module globals，`set_runtime_cloud_credentials`（line 858）设置它们——这个函数被 `web/backend/user_context.py:353` 调用，**不能删**。但这些全局变量本身从未被 connection.py 的函数读取（它们从 `os.getenv()` 读取），所以是**写入后从未读取**的死变量。
- `_normalize_turso_url` 在 connection.py 中仅 line 212 调用一次，utils.py 有同名函数，schema.py 也从 utils 导入

**⚠️ _row_to_dict 保留在 connection.py 中（不做变更）：**
- connection.py 版本有 `cursor.description` 回退路径（lines 767-771），用于 libsql 后端行没有 `.keys()` 的情况
- `_repo_helpers.row_to_dict` 没有 cursor.description 回退——仅处理 `.keys()` / `.asdict()` / `fallback_columns`
- hub_users.py 通过 `connection._row_to_dict(cur, row)` 调用，依赖 cursor.description 回退
- 这个函数不是"重复"，是 connection 层对 libsql 特殊行格式的封装，**保留不动**

- [ ] **Step 1: Delete TURSO_DB_URL/AUTH_TOKEN/HOSTNAME globals (lines 111-113)**

删除这 3 行。保留 TURSO_TEST_* 变量。

验证：grep `connection.TURSO_DB_URL` 和 `connection.TURSO_AUTH_TOKEN` 确认无外部读取。

- [ ] **Step 2: Replace _normalize_turso_url with import from utils**

```python
# BEFORE (line 170-178):
def _normalize_turso_url(hostname: str) -> str:
    if not hostname:
        return ""
    raw = hostname.strip()
    if raw.startswith("libsql://") or raw.startswith("https://") or raw.startswith("wss://"):
        return raw
    if "." in raw or raw == "localhost":
        return f"libsql://{raw}"
    return f"libsql://{raw}"

# AFTER: delete this function entirely, add to the imports from .utils:
from .utils import _normalize_turso_url
```

在 connection.py 顶部的 utils import 区添加 `_normalize_turso_url`。

- [ ] **Step 3: Compile check**

```bash
python -m py_compile database/connection.py
```

Expected: PASS

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database/connection.py
git commit -m "chore: remove duplicate _normalize_turso_url from connection.py + delete unused TURSO_* globals"
```

---

## Task 7: 清理 database/connection.py — 删除 re-import block

**文件:**
- Modify: `database/connection.py` lines 865-890

- [ ] **Step 1: Audit callers of re-imported names**

验证以下名称是否通过 `connection.X` 被外部使用：

```bash
# 搜索所有 Python 文件中通过 connection. 访问这些名称的用法
grep -rn "connection\._write_queue\|connection\._writer_daemon\|connection\._execute_batch_writes\|connection\._start_writer_daemon\|connection\._stop_writer_daemon\|connection\._start_sync_daemon\|connection\._stop_sync_daemon\|connection\.init_concurrent_system\|connection\.cleanup_concurrent_system\|connection\.set_db_syncing\|connection\.clear_db_syncing\|connection\.get_db_sync_status\|connection\.get_write_queue_stats" --include="*.py" | grep -v "connection.py"
```

预期：只有 `_repo_helpers.py` 中的 `_should_use_local_only_connection`（通过 `connection.` 访问）——这个函数不在 re-import block 里，不受影响。

- [ ] **Step 2: Delete the re-import block**

删除 `database/connection.py` 末尾的 lines 865-890（`from database.execution_engine import (...)` 整个 block）。

- [ ] **Step 3: Compile check**

```bash
python -m py_compile database/connection.py
```

Expected: PASS

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database/connection.py
git commit -m "chore: remove backward-compat re-import block from connection.py — import from execution_engine directly"
```

---

## Task 8: 清理 database/utils.py

**文件:**
- Modify: `database/utils.py`
  - 删除 `_is_replica_metadata_missing_error`（约 line 479-488）— 未被调用，connection.py 有自己的版本
  - 清理 `_normalize_turso_url` 无意义条件（约 lines 82-85）

- [ ] **Step 1: Delete unused _is_replica_metadata_missing_error from utils.py**

验证：grep 确认 utils.py 的版本无调用方（connection.py 用自己的版本）。

```bash
grep -rn "_is_replica_metadata_missing_error" --include="*.py" | grep -v "connection.py"
```

Expected: 只有 `utils.py:479` 的定义行，无调用行。

删除 utils.py 中的 `_is_replica_metadata_missing_error` 函数定义。

- [ ] **Step 2: Clean up _normalize_turso_url meaningless branches**

```python
# BEFORE (utils.py lines 82-85):
if "." in raw or raw == "localhost":
    return f"libsql://{raw}"
return f"libsql://{raw}"

# AFTER:
return f"libsql://{raw}"
```

- [ ] **Step 3: Compile check**

```bash
python -m py_compile database/utils.py
```

Expected: PASS

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database/utils.py
git commit -m "chore: remove unused _is_replica_metadata_missing_error from utils.py + simplify _normalize_turso_url"
```

---

## Task 9: 清理 session.py 和 community_lookup.py 死 import

**文件:**
- Modify: `database/session.py` lines 16-19
- Modify: `database/community_lookup.py` lines 28-31

- [ ] **Step 1: Remove dead libsql import from session.py**

```python
# BEFORE (session.py lines 16-19):
try:
    import libsql
except Exception:
    libsql = None

# AFTER: delete these 4 lines entirely
```

- [ ] **Step 2: Remove dead libsql import from community_lookup.py**

```python
# BEFORE (community_lookup.py lines 28-31):
try:
    import libsql
except Exception:
    libsql = None

# AFTER: delete these 4 lines entirely
```

- [ ] **Step 3: Compile check**

```bash
python -m py_compile database/session.py database/community_lookup.py
```

Expected: PASS

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database/session.py database/community_lookup.py
git commit -m "chore: remove dead libsql imports from session.py and community_lookup.py"
```

---

## Task 10: 重命名误称函数和参数

**文件:**
- Modify: `database/sync_service.py`
  - 重命名 `_run_libsql_sync_pipeline` → `_run_sync_pipeline`
  - 更新 skip reason `"libsql-unavailable"` → `"backend-unavailable"`
- Modify: `database/community_lookup.py`
  - 重命名参数 `use_libsql_dict` → `use_raw_dict`

- [ ] **Step 1: Rename _run_libsql_sync_pipeline in sync_service.py**

在 `database/sync_service.py` 中：
- 函数定义（约 line 44）：`def _run_libsql_sync_pipeline(...)` → `def _run_sync_pipeline(...)`
- 所有调用点：`_run_libsql_sync_pipeline(...)` → `_run_sync_pipeline(...)`

```bash
grep -n "_run_libsql_sync_pipeline" database/sync_service.py
```

用 replace_all 一次性替换所有出现。

- [ ] **Step 2: Update skip reason string**

```python
# BEFORE:
creds_skip_reason = "libsql-unavailable"
# AFTER:
creds_skip_reason = "backend-unavailable"
```

- [ ] **Step 3: Rename use_libsql_dict parameter in community_lookup.py**

在 `database/community_lookup.py` 中：
- 函数定义中的参数名
- 所有调用点

```bash
grep -n "use_libsql_dict" database/community_lookup.py
```

用 replace_all 替换为 `use_raw_dict`。

- [ ] **Step 4: Compile check**

```bash
python -m py_compile database/sync_service.py database/community_lookup.py
```

Expected: PASS

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add database/sync_service.py database/community_lookup.py
git commit -m "chore: rename _run_libsql_sync_pipeline → _run_sync_pipeline + fix misleading names"
```

---

## Task 11: sync_manager.py 提取重复模式

**文件:**
- Modify: `core/sync_manager.py`

提取两个重复模式为辅助函数：

**模式 A: `db_path` kwarg 合并**（出现 6 次）
```python
# 当前重复模式:
fn(voc_id, ..., db_path=self.db_path) if self.db_path else fn(voc_id, ...)
```

**模式 B: RowStatus logging**（出现 5 次）
```python
# 当前重复模式:
self._logger.info("", extra={"event": "row_status", "data": {"rows": [{"item_id": spell.voc_id, "status": status, "phase": phase}]}})
```

- [ ] **Step 1: Add _call_with_db_path helper**

在 `core/sync_manager.py` 的类外部或类内部（取决于 self.db_path 的访问方式）添加：

```python
def _call_db_fn(fn, voc_id, *args, db_path=None, **kwargs):
    """Call fn with db_path kwarg if available, without if not."""
    if db_path:
        return fn(voc_id, *args, db_path=db_path, **kwargs)
    return fn(voc_id, *args, **kwargs)
```

- [ ] **Step 2: Replace 6 occurrences of the db_path pattern**

逐一将 `fn(voc_id, ..., db_path=self.db_path) if self.db_path else fn(voc_id, ...)` 替换为 `_call_db_fn(fn, voc_id, ..., db_path=self.db_path)`。

- [ ] **Step 3: Add _log_row_status helper**

```python
def _log_row_status(self, item_id, status, phase, error=None):
    data = {"rows": [{"item_id": item_id, "status": status, "phase": phase}]}
    if error:
        data["rows"][0]["error"] = str(error)
    self._logger.info("", extra={"event": "row_status", "data": data})
```

- [ ] **Step 4: Replace 5 occurrences of the RowStatus pattern**

逐一将重复的日志代码替换为 `self._log_row_status(...)` 调用。

- [ ] **Step 5: Compile check**

```bash
python -m py_compile core/sync_manager.py
```

Expected: PASS

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/sync_manager.py
git commit -m "chore: extract duplicate db_path and RowStatus patterns in sync_manager.py"
```

---

## Task 12: 更新 ARCHITECTURE.md 文档

**文件:**
- Modify: `docs/architecture/ARCHITECTURE.md` line 46
- Modify: `docs/dev/AI_CONTEXT.md`（确认无 legacy.py / compat/ 引用需要更新）
- Modify: `docs/CHANGELOG.md`（记录本次清理）

- [ ] **Step 1: Remove legacy.py from ARCHITECTURE.md module table**

```markdown
# BEFORE (line 46):
| 持久层（可选门面）| `database/legacy.py` | `from database.legacy import X` 作为老 `core.db_manager` 调用点的过渡 drop-in（re-export 所有子模块） |

# AFTER: 删除这一行
```

- [ ] **Step 2: Check AI_CONTEXT.md for legacy/compat references**

```bash
grep -n "legacy\|compat" docs/dev/AI_CONTEXT.md
```

如有引用则更新或删除相关描述。

- [ ] **Step 3: Update CHANGELOG.md**

在 CHANGELOG 顶部添加本次清理记录：

```markdown
### 2026-05-21 — libsql 技术债全面清理
- 删除 `database/legacy.py`（无代码引用的死文件）
- 删除 `compat/` 包（3 个文件，仅 3 个测试使用，已更新测试直接从 core/ 导入）
- 删除 `core/log_config.py` 重复定义（后半段覆盖前半段）
- 清理 `database/connection.py`：删除 fallback 错误分类、未使用全局变量、重复 _normalize_turso_url、向后兼容 re-import block
- 清理 `database/utils.py`：删除未使用的 _is_replica_metadata_missing_error，简化 _normalize_turso_url 无意义条件
- 清理 dead imports：session.py、community_lookup.py 的死 libsql import
- 重命名误称：`_run_libsql_sync_pipeline` → `_run_sync_pipeline`，`use_libsql_dict` → `use_raw_dict`
- 删除 `core/mimo_client.py` 死函数 _extract_json_array
- 提取 `core/iteration_manager.py` 重复 json_repair import
- 提取 `core/sync_manager.py` 重复 db_path/RowStatus 模式
```

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/ARCHITECTURE.md docs/dev/AI_CONTEXT.md docs/CHANGELOG.md
git commit -m "docs: update ARCHITECTURE.md + CHANGELOG for libsql cleanup"
```

---

## Task 13: 全量回归验证

- [ ] **Step 1: Run full regression suite**

```bash
python -m pytest tests/ -v --tb=short -m "not slow"
```

Expected: 全部 PASS，无新增失败

- [ ] **Step 2: Compile all modified files**

```bash
for f in database/connection.py database/utils.py database/session.py database/community_lookup.py database/sync_service.py database/hub_users.py core/log_config.py core/mimo_client.py core/iteration_manager.py core/sync_manager.py; do
    python -m py_compile "$f" && echo "OK: $f" || echo "FAIL: $f"
done
```

Expected: 全部 OK

- [ ] **Step 3: Verify no broken imports**

```bash
python -c "import database.connection; import database.utils; import database.session; import database.community_lookup; import database.sync_service; import database.hub_users; import core.log_config; import core.mimo_client; import core.iteration_manager; import core.sync_manager; print('ALL OK')"
```

Expected: ALL OK

- [ ] **Step 4: Count line reduction**

```bash
# 统计 git diff 的净减行数
git diff --stat
```

Expected: 预计净减 ~250-300 行

---

## 回滚策略

如果任何 task 导致测试失败：
1. `git stash` 暂存当前更改
2. `git checkout <file>` 恢复单个文件
3. 定位失败原因后重试该 task
4. 如果是清理范围外的 bug，回退并记录为 FUTURE issue
