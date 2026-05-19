# Hybrid Dual-Track Architecture Implementation Plan (Updated)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor MOMO_Script to hybrid dual-track architecture: User_Sync_DB (embedded replica) + Global_Cache_DB (HTTP remote query). 3-level word lookup pipeline (local → cache → AI) with feature-flag gated rollout. Dedicated write thread for async cache writes. Retry limit for LLM failures.

**Architecture:** Per-word lookup within batches: L1 (local ai_word_notes) → L2 (Global_Cache_DB via HTTP `/v2/pipeline`) → L3 (AI API). CacheNetworkError triggers batch-level circuit breaker. AI results written to User_Sync_DB (sync) and Global_Cache_DB via CacheWriteWorker daemon thread (async, best-effort). LLM failures capped at 3 retries per word.

**Tech Stack:** Python 3.12+, SQLite/libsql (Turso), `requests.Session` for HTTP cache, pydantic-settings, existing write-queue pattern, pytest.

**Spec:** `docs/superpowers/specs/2026-05-18-dual-database-refactoring-design.md`

---

## File Structure

| File | Responsibility | Status |
| ---- | ------------- | ------ |
| `core/feature_flags.py` | Register `GLOBAL_CACHE_ENABLED` flag | **DONE** |
| `core/settings.py` | Cache DB settings model | **DONE** |
| `config.py` | Cache env var exports | **DONE** |
| `database/cache_client.py` | GlobalCacheClient + CacheWriteWorker | Needs update (add CacheWriteWorker, /v2/pipeline JSON format) |
| `database/migrations/V005_is_customized.py` | is_customized column | **DONE** (already in repo) |
| `database/notes_repo.py` | update_memory_aid | **DONE** (already in repo) |
| `database/sql_constants.py` | is_customized in NOTE_UPSERT_SQL | **DONE** (already in repo) |
| `core/word_lookup.py` | 3-level lookup orchestrator | Needs update (retry limit, CacheWriteWorker integration) |
| `database/migrations/V006_seed_global_cache.py` | Seed cache from existing data | **DONE** (already in repo) |
| `core/study_workflow.py` | Main workflow integration | Needs update (CacheWriteWorker, retry limit) |
| `database/migrations/V007_migrate_db_format.py` | libSQL → pyturso format migration | Not started (P6 scope) |
| `tests/conftest.py` | Test fixture isolation | Needs update (cache env vars) |

---

## P0-P5: Dual-Track Architecture (feature flag gated)

### Task 1: Register Feature Flag & Settings

**Status: DONE** — `GLOBAL_CACHE_ENABLED` already in `_KNOWN_FLAGS` and `Settings` model.

---

### Task 2: Add Cache Config Exports to config.py

**Status: DONE** — `TURSO_CACHE_DB_URL`, `TURSO_CACHE_AUTH_TOKEN`, `CACHE_TIMEOUT_S` already exported.

---

### Task 3: Update GlobalCacheClient with CacheWriteWorker

**Files:**

- Modify: `database/cache_client.py`

当前 `cache_client.py` 已有 `GlobalCacheClient`，但缺少：

1. `/v2/pipeline` JSON 格式的正确实现（当前响应解析可能不对）
2. `CacheWriteWorker` 专用写入线程
3. 精确的 `queue.Full` 异常捕获

- [ ] **Step 1: Update _pipeline_request with correct /v2/pipeline JSON format**

Edit `database/cache_client.py`, update `_pipeline_request` 方法确保请求和响应格式正确：

```python
def _pipeline_request(self, sql: str, args: Optional[list] = None) -> Optional[Dict[str, Any]]:
    """Execute SQL via Turso /v2/pipeline API.

    Turso pipeline 协议:
      请求: {"requests": [{"type": "execute", "stmts": [{"sql": "...", "args": [...]}]}]}
      响应: {"results": [{"type": "ok", "response": {"result": {...}}}]}
             或 {"results": [{"type": "error", "error": {"message": "..."}}]}
    HTTP 200 ≠ SQL 成功，必须检查 results[].type。
    """
    payload = {
        "requests": [{
            "type": "execute",
            "stmts": [{"sql": sql, "args": args or []}]
        }]
    }
    try:
        resp = self.session.post(self.endpoint, json=payload, timeout=self.timeout)
    except requests.Timeout as e:
        raise CacheNetworkError(f"Cache query timeout ({self.timeout}s): {e}") from e
    except requests.ConnectionError as e:
        raise CacheNetworkError(f"Cache connection failed: {e}") from e
    except requests.RequestException as e:
        raise CacheNetworkError(f"Cache request failed: {e}") from e

    if resp.status_code != 200:
        logger.warning(f"Cache HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"Cache JSON parse error: {e}")
        return None

    # 检查 pipeline 内部错误
    for result in body.get("results", []):
        if result.get("type") == "error":
            error_msg = result.get("error", {}).get("message", "unknown")
            logger.warning(f"Cache SQL error: {error_msg}")
            return None

    return body
```

- [ ] **Step 2: Add CacheWriteWorker class**

Add to `database/cache_client.py` after `GlobalCacheClient`:

```python
class CacheWriteWorker:
    """专用后台线程，消费写入队列，异步回写 Global_Cache_DB。

    - daemon=True: 进程退出时自动清理
    - Queue(maxsize=256): 背压控制，防止离线时队列无限增长
    - put_nowait + queue.Full 精确捕获: 缓存写入是 best-effort
    """

    def __init__(self, client: GlobalCacheClient):
        self.client = client
        self._queue: Queue = Queue(maxsize=256)
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="cache-writer"
        )
        self._thread.start()

    def submit(self, note: Dict[str, Any], prompt_version: str, ai_provider: str):
        """非阻塞投递。队列满时静默丢弃（缓存写入是 best-effort）。"""
        try:
            self._queue.put_nowait((note, prompt_version, ai_provider))
        except queue.Full:
            logger.warning("Cache write queue full, dropping background write.")
        except Exception as e:
            logger.error(f"Unexpected error queuing cache write: {e}")

    def _run(self):
        while True:
            note, pv, provider = self._queue.get()
            try:
                self.client.write(note, pv, provider)
            except Exception:
                pass  # write() 内部已 log
            finally:
                self._queue.task_done()
```

需要在文件顶部添加 import:

```python
import threading
import queue
from queue import Queue
```

- [ ] **Step 3: Update find() to check results[].type**

确保 `find()` 方法正确解析 `/v2/pipeline` 响应格式：

```python
def find(self, spelling: str, prompt_version: str, ai_provider: str) -> Optional[Dict[str, Any]]:
    """Query cache for a word note. Returns note dict or None."""
    key = self.cache_key(spelling, prompt_version, ai_provider)
    sql = "SELECT ai_output_json FROM ai_cache WHERE cache_key = ?"
    body = self._pipeline_request(sql, [key])

    if body is None:
        return None

    try:
        results = body.get("results", [])
        if not results:
            return None
        first = results[0]
        if first.get("type") != "ok":
            return None
        response = first.get("response", {})
        result_rows = response.get("result", [])
        if not result_rows:
            return None
        # result_rows 结构取决于 pipeline 响应格式
        # 可能是 {"rows": [[{"value": "..."}]]} 或其他格式
        # 需要根据实际 Turso 响应调整
        json_str = ""
        rows_data = result_rows.get("rows", []) if isinstance(result_rows, dict) else result_rows
        if rows_data and rows_data[0]:
            cell = rows_data[0][0] if isinstance(rows_data[0], list) else rows_data[0]
            json_str = cell.get("value", "") if isinstance(cell, dict) else str(cell)
        if not json_str:
            return None
        return json.loads(json_str)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        logger.debug(f"Cache parse error for {spelling}: {e}")
        return None
```

- [ ] **Step 4: Run existing cache_client tests**

```bash
pytest tests/unit/database/test_cache_client.py -v --tb=short
```

Expected: All pass (update mock response format if needed).

- [ ] **Step 5: Add CacheWriteWorker tests**

Add to `tests/unit/database/test_cache_client.py`:

```python
def test_cache_write_worker_submit():
    """CacheWriteWorker.submit puts item in queue without blocking."""
    from database.cache_client import CacheWriteWorker
    mock_client = MagicMock()
    worker = CacheWriteWorker(mock_client)
    worker.submit({"spelling": "hello"}, "v1", "mimo")
    # Give thread time to process
    import time
    time.sleep(0.1)
    mock_client.write.assert_called_once()


def test_cache_write_worker_full_queue():
    """CacheWriteWorker.submit drops item when queue is full (no exception)."""
    from database.cache_client import CacheWriteWorker
    mock_client = MagicMock()
    worker = CacheWriteWorker(mock_client)
    # Fill the queue
    for i in range(256):
        worker._queue.put_nowait(({"spelling": f"w{i}"}, "v1", "mimo"))
    # This should not raise
    worker.submit({"spelling": "overflow"}, "v1", "mimo")
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/unit/database/test_cache_client.py -v --tb=short
```

- [ ] **Step 7: Commit**

```bash
git add database/cache_client.py tests/unit/database/test_cache_client.py
git commit -m "feat: add CacheWriteWorker + fix /v2/pipeline JSON format in cache_client"
```

---

### Task 4: V005_is_customized Migration

**Status: DONE** — `database/migrations/V005_is_customized.py` 已在 repo 中，测试通过。

---

### Task 5: update_memory_aid in notes_repo.py

**Status: DONE** — `update_memory_aid` 已在 `database/notes_repo.py` 中，`is_customized=1` 已设置。

---

### Task 6: Update WordLookup with Retry Limit + CacheWriteWorker

**Files:**

- Modify: `core/word_lookup.py`
- Modify: `tests/unit/core/test_word_lookup.py`

当前 `word_lookup.py` 缺少：
1. LLM 失败重试上限（`MAX_LLM_RETRIES = 3`）
2. 使用 `CacheWriteWorker` 替代 `threading.Thread` 做异步缓存写入

- [ ] **Step 1: Add retry limit to WordLookup**

Edit `core/word_lookup.py`, 在 `WordLookup.__init__` 中添加:

```python
MAX_LLM_RETRIES = 3

class WordLookup:
    def __init__(self, ...):
        ...
        self.cache_write_worker = None  # 由外部注入
        self._llm_fail_counts: Dict[str, int] = {}  # spelling → fail count

    def lookup(self, spelling, prompt_version, ai_provider) -> LookupResult:
        """3-level lookup. CacheNetworkError and APIError propagate upward."""
        # ... Level 1, Level 2 unchanged ...

        # Level 3: AI API (with retry limit)
        fail_count = self._llm_fail_counts.get(spelling, 0)
        if fail_count >= MAX_LLM_RETRIES:
            from core.exceptions import APIError
            raise APIError(f"LLM retry limit ({MAX_LLM_RETRIES}) reached for '{spelling}'")

        try:
            ai_note = self._call_ai([spelling], prompt_version, ai_provider)
        except Exception:
            self._llm_fail_counts[spelling] = fail_count + 1
            raise

        if ai_note:
            self._save_local(ai_note, prompt_version, ai_provider)
            self._write_cache_async(ai_note, prompt_version, ai_provider)
            # 成功则重置计数
            self._llm_fail_counts.pop(spelling, None)
            return LookupResult(note=ai_note, source="ai")

        raise RuntimeError(f"WordLookup: all levels exhausted for '{spelling}'")
```

- [ ] **Step 2: Replace threading.Thread with CacheWriteWorker in _write_cache_async**

Edit `_write_cache_async`:

```python
def _write_cache_async(self, note, prompt_version, ai_provider):
    """Fire-and-forget write to Global_Cache_DB via CacheWriteWorker."""
    if not self.cache_client:
        return
    if self.cache_write_worker:
        self.cache_write_worker.submit(note, prompt_version, ai_provider)
    else:
        # Fallback: direct write (should not happen in production)
        try:
            self.cache_client.write(note, prompt_version, ai_provider)
        except Exception as e:
            self.logger.warning(f"Cache write fallback failed: {e}")
```

- [ ] **Step 3: Add retry limit tests**

Add to `tests/unit/core/test_word_lookup.py`:

```python
class TestRetryLimit:
    def test_llm_fail_increments_count(self, lookup):
        lookup.ai_client.generate_mnemonics.side_effect = Exception("API down")
        with patch.object(lookup, "_find_local", return_value=None):
            with patch.object(lookup.cache_client, "find", return_value=None):
                for i in range(3):
                    with pytest.raises(Exception):
                        lookup.lookup("failword", "v1", "mimo")
                assert lookup._llm_fail_counts.get("failword") == 3

    def test_llm_retry_limit_raises_api_error(self, lookup):
        from core.exceptions import APIError
        lookup._llm_fail_counts["failword"] = 3  # Already failed 3 times
        with patch.object(lookup, "_find_local", return_value=None):
            with patch.object(lookup.cache_client, "find", return_value=None):
                with pytest.raises(APIError, match="retry limit"):
                    lookup.lookup("failword", "v1", "mimo")

    def test_llm_success_resets_count(self, lookup):
        lookup._llm_fail_counts["newword"] = 2  # Failed twice before
        with patch.object(lookup, "_find_local", return_value=None):
            with patch.object(lookup.cache_client, "find", return_value=None):
                with patch.object(lookup, "_save_local"):
                    with patch.object(lookup, "_write_cache_async"):
                        result = lookup.lookup("newword", "v1", "mimo")
                        assert result.source == "ai"
                        assert "newword" not in lookup._llm_fail_counts
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/core/test_word_lookup.py -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
git add core/word_lookup.py tests/unit/core/test_word_lookup.py
git commit -m "feat: add LLM retry limit (MAX_LLM_RETRIES=3) + CacheWriteWorker integration to WordLookup"
```

---

### Task 7: V006 Seed Global Cache Migration

**Status: DONE** — `database/migrations/V006_seed_global_cache.py` 已在 repo 中。

---

### Task 8: Integrate WordLookup + CacheWriteWorker into study_workflow.py

**Files:**

- Modify: `core/study_workflow.py`

当前 `study_workflow.py` 需要：

1. 初始化 `CacheWriteWorker` 并注入 `WordLookup`
2. 熔断机制（CacheNetworkError → batch circuit breaker）
3. LLM 失败重试上限处理（`llm_fail_count`）

- [ ] **Step 1: Add CacheWriteWorker initialization**

Edit `core/study_workflow.py`, 在 `__init__` 中（GLOBAL_CACHE_ENABLED 分支）：

```python
if is_enabled("GLOBAL_CACHE_ENABLED"):
    import config as _config
    cache_url = getattr(_config, "TURSO_CACHE_DB_URL", None)
    cache_token = getattr(_config, "TURSO_CACHE_AUTH_TOKEN", None)
    cache_timeout = getattr(_config, "CACHE_TIMEOUT_S", 3.0)
    if cache_url and cache_token:
        from database.cache_client import GlobalCacheClient, CacheWriteWorker
        self.cache_client = GlobalCacheClient(cache_url, cache_token, cache_timeout)
        self.cache_write_worker = CacheWriteWorker(self.cache_client)  # 专用写入线程
        self.word_lookup = WordLookup(
            logger=logger,
            ai_client=ai_client,
            cache_client=self.cache_client,
            db_path=db_path,
        )
        self.word_lookup.cache_write_worker = self.cache_write_worker  # 注入写入线程
        try:
            self.cache_client.init_table()
        except Exception:
            self.logger.warning("Cache table init failed (non-fatal)")
```

- [ ] **Step 2: Update _run_ai_batch with retry limit handling**

Edit `_run_ai_batch` 中的异常处理，确保 LLM 失败计数正确处理：

```python
    except APIError as e:
        # APIError 包含两种情况：LLM 调用失败 和 重试上限到达
        self.logger.warning(f"[Cache] AI failed for {word}: {e}")
        # 重试上限到达的词会由 WordLookup 内部计数，下次 lookup 直接 raise APIError
        # 这里捕获后不加入 pending，由下游自然留空
```

- [ ] **Step 3: Run existing tests**

```bash
pytest tests/core/test_study_workflow.py -v --tb=short
```

Expected: All pass (flag defaults to False, legacy path unchanged).

- [ ] **Step 4: Commit**

```bash
git add core/study_workflow.py
git commit -m "feat: integrate CacheWriteWorker + retry limit into study_workflow"
```

---

### Task 9: Update SQL Constants for is_customized

**Status: DONE** — `is_customized` 已在 `NOTE_UPSERT_SQL` 和 `build_note_upsert_args` 中。

---

### Task 10: Update conftest.py for Cache Env Var Isolation

**Files:**

- Modify: `tests/conftest.py`

- [ ] **Step 1: Add cache env vars to cloud isolation fixture**

Edit `tests/conftest.py`, 在 `isolate_cloud_configuration` fixture 中添加:

```python
    monkeypatch.delenv("TURSO_CACHE_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_CACHE_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CACHE_TIMEOUT_S", raising=False)
    monkeypatch.delenv("GLOBAL_CACHE_ENABLED", raising=False)
```

`delenv` 足以隔离——所有缓存配置都通过 `os.getenv()` 读取，清空 environ 即可。
不需要额外遍历模块做 `setattr` mock（过度设计，且 `import config` vs `from config import` 行为不一致易遗漏）。

- [ ] **Step 2: Run all tests**

```bash
pytest tests/ -v --tb=short -m "not slow"
```

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "chore: isolate cache env vars in test fixtures"
```

---

### Task 11: End-to-End Integration Test

**Files:**

-Create/Modify: `tests/integration/test_word_lookup_flow.py`

- [ ] **Step 1: Write integration test covering full L1→L2→L3 + retry limit + circuit breaker**

```python
"""tests/integration/test_word_lookup_flow.py: End-to-end 3-level lookup test."""
import sqlite3
import pytest
from unittest.mock import MagicMock, patch
from core.word_lookup import WordLookup, LookupResult
from database.cache_client import CacheNetworkError
from core.exceptions import APIError


@pytest.fixture
def lookup():
    logger = MagicMock()
    ai_client = MagicMock()
    cache_client = MagicMock()
    l = WordLookup(logger=logger, ai_client=ai_client, cache_client=cache_client)
    return l


class TestFullFlow:
    def test_l1_local_hit(self, lookup):
        mock_note = {"spelling": "hello", "basic_meanings": "你好", "is_customized": 0}
        with patch.object(lookup, "_find_local", return_value=mock_note):
            result = lookup.lookup("hello", "v1", "mimo")
            assert result.source == "local"
            lookup.cache_client.find.assert_not_called()

    def test_l1_customized_skips_l2_l3(self, lookup):
        mock_note = {"spelling": "hello", "is_customized": 1}
        with patch.object(lookup, "_find_local", return_value=mock_note):
            result = lookup.lookup("hello", "v1", "mimo")
            assert result.source == "local_customized"
            lookup.cache_client.find.assert_not_called()

    def test_l2_cache_hit_upserts_local(self, lookup):
        mock_note = {"spelling": "world", "basic_meanings": "世界"}
        with patch.object(lookup, "_find_local", return_value=None):
            with patch.object(lookup.cache_client, "find", return_value=mock_note):
                with patch.object(lookup, "_upsert_local") as mock_upsert:
                    result = lookup.lookup("world", "v1", "mimo")
                    assert result.source == "cache"
                    mock_upsert.assert_called_once()

    def test_l3_ai_full_chain(self, lookup):
        lookup.ai_client.generate_mnemonics.return_value = (
            [{"spelling": "new", "basic_meanings": "新"}], {})
        with patch.object(lookup, "_find_local", return_value=None):
            with patch.object(lookup.cache_client, "find", return_value=None):
                with patch.object(lookup, "_save_local"):
                    with patch.object(lookup, "_write_cache_async"):
                        result = lookup.lookup("new", "v1", "mimo")
                        assert result.source == "ai"

    def test_cache_network_error_circuit_breaker(self, lookup):
        lookup.cache_client.find.side_effect = CacheNetworkError("timeout")
        with patch.object(lookup, "_find_local", return_value=None):
            with pytest.raises(CacheNetworkError):
                lookup.lookup("hello", "v1", "mimo")

    def test_llm_retry_limit(self, lookup):
        lookup._llm_fail_counts["fail"] = 3
        with patch.object(lookup, "_find_local", return_value=None):
            with patch.object(lookup.cache_client, "find", return_value=None):
                with pytest.raises(APIError, match="retry limit"):
                    lookup.lookup("fail", "v1", "mimo")
```

- [ ] **Step 2: Run integration test**

```bash
pytest tests/integration/test_word_lookup_flow.py -v --tb=short
```

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_word_lookup_flow.py
git commit -m "test: add integration tests for 3-level WordLookup + retry limit + circuit breaker"
```

---

### Task 12: Full Test Suite Verification

- [ ] **Step 1: Run all tests**

```bash
pytest tests/ -v --tb=short -m "not slow"
```

- [ ] **Step 2: py_compile on new/modified files**

```bash
python -m py_compile core/word_lookup.py
python -m py_compile database/cache_client.py
python -m py_compile core/study_workflow.py
```

- [ ] **Step 3: Verify flag=false still works (legacy path)**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -k "not cache"
```

Expected: All pass.

---

## P6: pyturso 迁移（独立 feature branch）

> P6 在 P0-P5 稳定后执行。以下任务作为独立 feature branch。

### Task 13: pyturso 兼容性验证脚本

**Files:**

-Create: `scripts/validate_pyturso_compat.py`

- [ ] **Step 1: Write compatibility validation script**

```python
"""scripts/validate_pyturso_compat.py: Validate pyturso compatibility before P6 migration."""
import sys

def check_import():
    try:
        import turso.sync
        print("[OK] turso.sync importable")
        return True
    except ImportError as e:
        print(f"[FAIL] Cannot import turso.sync: {e}")
        return False

def check_connect():
    try:
        import turso.sync
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        db = turso.sync.connect(path)
        db.close()
        os.unlink(path)
        print("[OK] turso.sync.connect() works")
        return True
    except Exception as e:
        print(f"[FAIL] turso.sync.connect() failed: {e}")
        return False

def check_pragma():
    try:
        import turso.sync
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        db = turso.sync.connect(path)
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA synchronous=NORMAL")
        db.close()
        os.unlink(path)
        print("[OK] PRAGMA syntax compatible")
        return True
    except Exception as e:
        print(f"[FAIL] PRAGMA failed: {e}")
        return False

def check_vacuum_into():
    try:
        import turso.sync
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        db = turso.sync.connect(path)
        db.execute("CREATE TABLE t(x)")
        backup = path + ".bak"
        db.execute(f"VACUUM INTO '{backup}'")
        db.close()
        os.unlink(path)
        os.unlink(backup)
        print("[OK] VACUUM INTO supported")
        return True
    except Exception as e:
        print(f"[FAIL] VACUUM INTO failed: {e}")
        return False

def check_libsql_open():
    """尝试用 pyturso 打开现有 libSQL 格式 .db 文件。"""
    # 需要一个真实的 libSQL .db 文件路径
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not db_path:
        print("[SKIP] libSQL open test (pass db path as argument)")
        return True
    try:
        import turso.sync
        db = turso.sync.connect(db_path)
        db.close()
        print(f"[OK] pyturso can open libSQL file: {db_path}")
        return True
    except Exception as e:
        print(f"[FAIL] Cannot open libSQL file: {e}")
        return False

if __name__ == "__main__":
    results = [check_import(), check_connect(), check_pragma(), check_vacuum_into(), check_libsql_open()]
    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} checks passed")
    sys.exit(0 if all(results) else 1)
```

- [ ] **Step 2: Run validation script**

```bash
python scripts/validate_pyturso_compat.py data/history-asher.db
```

- [ ] **Step 3: Commit**

```bash
git add scripts/validate_pyturso_compat.py
git commit -m "chore: add pyturso compatibility validation script"
```

---

### Task 14: V007 .db 格式迁移

**Files:**

-Create: `database/migrations/V007_migrate_db_format.py`

- [ ] **Step 1: Write migration script**

```python
"""
V007_migrate_db_format.py: Migrate .db from libSQL format to pyturso-compatible format.

Strategy:
  1. Detect format (try turso.sync.connect)
  2. If compatible → no-op
  3. If not → export-import (iterdump with internal table filter + foreign key guard)
"""
from __future__ import annotations
import os
import shutil
import sqlite3
from typing import Any

# SQLite 内部表前缀，iterdump 时过滤
INTERNAL_PREFIXES = ("sqlite_sequence", "_litestream_", "sqlite_")


def _detect_format(db_path: str) -> str:
    """探测 .db 文件是否兼容 pyturso。"""
    try:
        import turso.sync
        db = turso.sync.connect(db_path)
        db.close()
        return "turso_sync"
    except Exception:
        return "libsql_embedded_replica"


def _migrate_libsql_to_turso(db_path: str) -> str:
    """将 libSQL 格式 .db 转换为 pyturso 兼容格式。

    Returns: backup_path
    """
    import turso.sync

    # 1. 备份
    backup_path = db_path + ".pre_pyturso.bak"
    shutil.copy2(db_path, backup_path)

    # 2. 用标准 sqlite3 导出，过滤内部表
    conn_old = sqlite3.connect(db_path)
    dump_path = db_path + ".dump.sql"
    with open(dump_path, "w") as f:
        for line in conn_old.iterdump():
            if any(f'"{p}"' in line or f" {p} " in line for p in INTERNAL_PREFIXES):
                continue
            f.write(line + "\n")
    conn_old.close()
    del conn_old  # 显式释放，防止 Windows 下 SQLite 文件句柄延迟释放

    # 3. 用 pyturso 创建新库并导入（关闭外键避免子表先于父表导入）
    import time
    for attempt in range(3):
        try:
            os.remove(db_path)
            break
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.5)  # Windows 句柄释放重试
    db_new = turso.sync.connect(db_path)
    db_new.execute("PRAGMA foreign_keys=OFF;")
    with open(dump_path, "r") as f:
        db_new.executescript(f.read())
    db_new.execute("PRAGMA foreign_keys=ON;")
    db_new.close()

    # 4. 清理临时文件
    os.remove(dump_path)
    return backup_path


def apply(cur: Any) -> None:
    """Run V007 migration. Detects format and migrates if needed."""
    # 获取 db_path 从 cursor 的 connection
    db_path = None
    try:
        row = cur.execute("PRAGMA database_list").fetchone()
        if row:
            db_path = row[2]  # file path
    except Exception:
        pass

    if not db_path or not os.path.exists(db_path):
        return

    fmt = _detect_format(db_path)
    if fmt == "turso_sync":
        return  # 已兼容，无需迁移

    backup = _migrate_libsql_to_turso(db_path)
    print(f"V007: Migrated {db_path} from libSQL to turso_sync format. Backup: {backup}")
```

- [ ] **Step 2: Commit**

```bash
git add database/migrations/V007_migrate_db_format.py
git commit -m "feat: V007 migration — libSQL to pyturso format conversion"
```

---

### Task 15: connection.py 重写 + Checkpoint 调度

**Files:**

- Modify: `database/connection.py`
- Modify: `database/sync_service.py`
- Modify: `database/execution_engine.py`

- [ ] **Step 1: Rewrite _connect_embedded_replica → _connect_turso_sync**

```python
# database/connection.py
import turso.sync

def _connect_turso_sync(db_path, remote_url, auth_token):
    """替代 _connect_embedded_replica()"""
    db = turso.sync.connect(
        db_path,
        remote_url=remote_url,
        auth_token=auth_token,
    )
    return db
```

- [ ] **Step 2: sync_service.py — conn.sync() → db.push()/db.pull()**

```python
# database/sync_service.py
def do_sync(db, ...):
    db.pull()  # 云端 → 本地
    # ... 业务逻辑 ...
    db.push()  # 本地 → 云端
```

- [ ] **Step 3: execution_engine.py — checkpoint 调度**

```python
# database/execution_engine.py

class SyncDaemon:
    def __init__(self, db):
        self.db = db

    def run_once(self):
        self.db.pull()
        # 每次 pull 后 checkpoint 合流 WAL
        # （无新 WAL 增量时空 checkpoint 极轻量，开销可忽略）
        self.db.checkpoint()
        self.db.push()
```

- [ ] **Step 4: requirements.txt — 添加 pyturso，保留 libsql 宽限期**

```
pyturso>=0.1.0
libsql-experimental  # 宽限期：P6 合并后保留 1 个版本周期
```

- [ ] **Step 5: Commit**

```bash
git add database/connection.py database/sync_service.py database/execution_engine.py requirements.txt
git commit -m "feat(P6): migrate connection.py to turso.sync + checkpoint scheduling"
```

---

### Task 16: P6 全量回归测试

- [ ] **Step 1: Run all tests**

```bash
pytest tests/ -v --tb=short -m "not slow"
```

- [ ] **Step 2: Manual verification**

```bash
python main.py
# 验证：CLI 启动正常、查词正常、push/pull 同步
python scripts/start_web.py
# 验证：Web 启动正常、编辑 memory_aid 正常
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test(P6): full regression after pyturso migration"
```

---

## Spec Coverage Checklist

| Spec Section | Implemented In | Status |
|---|---|---|
| §1.1 决策表 (LWW, CacheWriteWorker, retry limit) | Task 3, 6, 8 | In plan |
| §2.2 3-level lookup flow | Task 6 | Needs update |
| §3.1 WordLookup + retry limit | Task 6 | Needs update |
| §3.2 CacheWriteWorker + /v2/pipeline format | Task 3 | Needs update |
| §3.3 Module responsibility | Task 8 | Needs update |
| §4.1 is_customized (V005) | Already done | DONE |
| §4.2 ai_cache table | Task 3 (init_table) | Already in code |
| §4.3 Seed data (V006) | Already done | DONE |
| §5 Config changes | Already done | DONE |
| §6 File change list | All tasks | Covered |
| §7.1 VACUUM INTO snapshot | Task 14 (V007) | In plan |
| §7.5 回滚 (correct versions) | Task 14 | In plan |
| §8.1 3-level scenarios | Task 11 | In plan |
| §8.2 LWW conflict | Documentation in spec | No code change needed |
| §9.1 Feature flag | Already done | DONE |
| §9.2 P phases | Task sequence follows phases | In plan |
| §10.1 pyturso SDK | Task 13 | In plan |
| §10.2 Compat validation | Task 13 | In plan |
| §10.3 .db format migration (iterdump filter + FK guard) | Task 14 | In plan |
| §10.4 P6 steps (checkpoint, libsql grace) | Task 15 | In plan |
| §10.5 API diff table | Task 15 | In plan |

---

## Deferred Items

1. **ui_manager source tag** (§6): 显示 source 标签（"local"/"cache"/"ai"）— 低优先级
2. **Web UI integration**: Web 前端需要对应的 source 标签显示 — 不在本次范围
