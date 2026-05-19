# Hybrid Dual-Track Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor MOMO_Script from single-database architecture to a hybrid dual-track system: User_Sync_DB (embedded replica) + Global_Cache_DB (HTTP remote query). Provide a 3-level word lookup pipeline (local → cache → AI) with feature-flag gated rollout.

**Architecture:** Per-word lookup within batches: before calling AI for a batch, iterate each word through L1 (local ai_word_notes) → L2 (Global_Cache_DB via HTTP) → L3 (AI API). CacheNetworkError triggers batch-level circuit breaker. AI results are written to both User_Sync_DB (synchronous) and Global_Cache_DB (fire-and-forget async).

**Tech Stack:** Python 3.12+, SQLite/libsql (Turso), `requests.Session` for HTTP cache, pydantic-settings, existing write-queue pattern, pytest.

---

## Task 1: Register Feature Flag & Settings

**Files:**
- Modify: `core/feature_flags.py:17-23`
- Modify: `core/settings.py:43-49, 63-69`

- [ ] **Step 1: Add GLOBAL_CACHE_ENABLED to _KNOWN_FLAGS**

Edit `core/feature_flags.py`, add to the set:

```python
_KNOWN_FLAGS: Set[str] = {
    "AUTO_WARMUP_SYNC_ENABLED",
    "SYNC_STATUS_HEAVY_QUERY_ENABLED",
    "BACKGROUND_RETRY_ENABLED",
    "IDLE_ENGINE_ENABLED",
    "ISOLATED_READ_CONN_ENABLED",
    "GLOBAL_CACHE_ENABLED",  # NEW
}
```

- [ ] **Step 2: Add cache settings to Settings model**

Edit `core/settings.py`, add after the `IDLE_ENGINE_ENABLED` field:

```python
    # ─────────────── Global Cache DB ───────────────
    TURSO_CACHE_DB_URL: Optional[str] = None
    TURSO_CACHE_AUTH_TOKEN: Optional[str] = None
    CACHE_TIMEOUT_S: float = 3.0
    GLOBAL_CACHE_ENABLED: bool = False
```

Add `Optional` to the existing `from typing import Optional` import (already present).

- [ ] **Step 3: Run existing flag/settings tests**

```bash
pytest tests/unit/feature_flags/ tests/unit/settings/ -v --tb=short
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add core/feature_flags.py core/settings.py
git commit -m "feat: register GLOBAL_CACHE_ENABLED flag + cache DB settings"
```

---

## Task 2: Add Cache Config Exports to config.py

**Files:**
- Modify: `config.py:96-110`

- [ ] **Step 1: Add cache env var exports**

Edit `config.py`, add after `TURSO_ORG_SLUG` line (around line 108):

```python
# Global Cache DB (云端 AI 缓存池)
TURSO_CACHE_DB_URL = os.getenv('TURSO_CACHE_DB_URL')
TURSO_CACHE_AUTH_TOKEN = os.getenv('TURSO_CACHE_AUTH_TOKEN')
CACHE_TIMEOUT_S = float(os.getenv('CACHE_TIMEOUT_S', '3.0'))
```

- [ ] **Step 2: Add to switch_user function**

Edit `config.py` `switch_user()` function, add cache env refresh:

```python
    global ACTIVE_USER, MOMO_TOKEN, GEMINI_API_KEY, MIMO_API_KEY
    global AI_PROVIDER, DB_PATH, TEST_DB_PATH, TURSO_DB_URL, TURSO_AUTH_TOKEN
    global TURSO_CACHE_DB_URL, TURSO_CACHE_AUTH_TOKEN  # NEW

    # ... existing code ...

    TURSO_CACHE_DB_URL = os.getenv("TURSO_CACHE_DB_URL")
    TURSO_CACHE_AUTH_TOKEN = os.getenv("TURSO_CACHE_AUTH_TOKEN")
```

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add cache DB config exports + switch_user refresh"
```

---

## Task 3: Create GlobalCacheClient (database/cache_client.py)

**Files:**
- Create: `database/cache_client.py`
- Create: `tests/unit/database/test_cache_client.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/database/test_cache_client.py`:

```python
"""tests/unit/database/test_cache_client.py: GlobalCacheClient unit tests."""
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from database.cache_client import GlobalCacheClient, CacheNetworkError


@pytest.fixture
def client():
    return GlobalCacheClient(
        url="https://test.turso.io",
        token="test-token",
        timeout=2.0,
    )


def test_cache_key_deterministic():
    from database.cache_client import GlobalCacheClient
    key1 = GlobalCacheClient.cache_key("hello", "v1", "mimo")
    key2 = GlobalCacheClient.cache_key("hello", "v1", "mimo")
    assert key1 == key2
    assert len(key1) == 16


def test_cache_key_different_words():
    from database.cache_client import GlobalCacheClient
    key1 = GlobalCacheClient.cache_key("hello", "v1", "mimo")
    key2 = GlobalCacheClient.cache_key("world", "v1", "mimo")
    assert key1 != key2


def test_cache_key_different_versions():
    from database.cache_client import GlobalCacheClient
    key1 = GlobalCacheClient.cache_key("hello", "v1", "mimo")
    key2 = GlobalCacheClient.cache_key("hello", "v2", "mimo")
    assert key1 != key2


def test_cache_key_different_providers():
    from database.cache_client import GlobalCacheClient
    key1 = GlobalCacheClient.cache_key("hello", "v1", "mimo")
    key2 = GlobalCacheClient.cache_key("hello", "v1", "gemini")
    assert key1 != key2


def test_find_raises_cache_network_error_on_timeout(client):
    import requests
    with patch.object(client.session, "post", side_effect=requests.Timeout("timed out")):
        with pytest.raises(CacheNetworkError):
            client.find("hello", "v1", "mimo")


def test_find_raises_cache_network_error_on_connection_error(client):
    import requests
    with patch.object(client.session, "post", side_effect=requests.ConnectionError("refused")):
        with pytest.raises(CacheNetworkError):
            client.find("hello", "v1", "mimo")


def test_find_returns_none_on_404(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch.object(client.session, "post", return_value=mock_resp):
        result = client.find("hello", "v1", "mimo")
        assert result is None


def test_find_returns_note_on_200(client):
    note_data = {"spelling": "hello", "basic_meanings": "你好"}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": [{
            "response": {
                "result": [[{"value": json.dumps(note_data)}]]
            }
        }]
    }
    with patch.object(client.session, "post", return_value=mock_resp):
        result = client.find("hello", "v1", "mimo")
        assert result is not None
        assert result["spelling"] == "hello"


def test_write_does_not_raise(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch.object(client.session, "post", return_value=mock_resp):
        # Should not raise
        client.write({"spelling": "hello", "basic_meanings": "test"}, "v1", "mimo")


def test_write_swallows_exceptions(client):
    with patch.object(client.session, "post", side_effect=Exception("boom")):
        # Should not raise (fire-and-forget)
        client.write({"spelling": "hello"}, "v1", "mimo")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/database/test_cache_client.py -v --tb=short
```

Expected: FAIL with `ModuleNotFoundError: No module named 'database.cache_client'`

- [ ] **Step 3: Write implementation**

Create `database/cache_client.py`:

```python
"""
database/cache_client.py: HTTP client for Global_Cache_DB (Turso cloud).

Uses Turso's /v2/pipeline API for direct SQL queries without a local replica.
Connection reuse via requests.Session.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class CacheNetworkError(Exception):
    """Cache HTTP query timeout/connection failure. Triggers batch circuit breaker."""


class GlobalCacheClient:
    """HTTP client for the global AI cache database (Turso cloud, no local replica)."""

    def __init__(self, url: str, token: str, timeout: float = 3.0):
        self.endpoint = url.rstrip("/") + "/v2/pipeline"
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })

    @staticmethod
    def cache_key(spelling: str, prompt_version: str, ai_provider: str) -> str:
        raw = f"{spelling}:{prompt_version}:{ai_provider}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _pipeline_request(self, sql: str, args: Optional[list] = None) -> Optional[Dict[str, Any]]:
        """Execute a SQL statement via Turso /v2/pipeline API.

        Returns parsed response dict, or None on non-200.
        Raises CacheNetworkError on timeout/connection errors.
        """
        stmts = [{"sql": sql, "args": args or []}]
        payload = {"requests": [{"type": "execute", "stmts": stmts}]}

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
            return resp.json()
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"Cache JSON parse error: {e}")
            return None

    def find(self, spelling: str, prompt_version: str, ai_provider: str) -> Optional[Dict[str, Any]]:
        """Query cache for a word note. Returns note dict or None.

        Raises CacheNetworkError on network failures.
        """
        key = self.cache_key(spelling, prompt_version, ai_provider)
        sql = "SELECT ai_output_json FROM ai_cache WHERE cache_key = ?"
        result = self._pipeline_request(sql, [key])

        if result is None:
            return None

        try:
            rows = result.get("result", [{}])
            if not rows:
                return None
            first_result = rows[0]
            inner = first_result.get("response", {})
            data_rows = inner.get("result", [])
            if not data_rows or not data_rows[0]:
                return None
            json_str = data_rows[0][0].get("value", "")
            if not json_str:
                return None
            return json.loads(json_str)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            logger.debug(f"Cache parse error for {spelling}: {e}")
            return None

    def write(self, note: Dict[str, Any], prompt_version: str, ai_provider: str) -> None:
        """Write a note to cache (fire-and-forget). Exceptions logged, never raised."""
        spelling = note.get("spelling", "")
        if not spelling:
            return

        key = self.cache_key(spelling, prompt_version, ai_provider)
        sql = (
            "INSERT OR IGNORE INTO ai_cache "
            "(cache_key, spelling, prompt_version, ai_provider, ai_output_json) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        try:
            self._pipeline_request(sql, [key, spelling, prompt_version, ai_provider, json.dumps(note, ensure_ascii=False)])
            logger.debug(f"Cache write: {spelling}")
        except CacheNetworkError as e:
            logger.warning(f"Cache write failed (fire-and-forget): {e}")
        except Exception as e:
            logger.warning(f"Cache write unexpected error: {e}")

    def init_table(self) -> None:
        """Create ai_cache table if not exists. Called once at startup."""
        sql = (
            "CREATE TABLE IF NOT EXISTS ai_cache ("
            "cache_key TEXT PRIMARY KEY, spelling TEXT NOT NULL, "
            "prompt_version TEXT NOT NULL, ai_provider TEXT NOT NULL, "
            "ai_output_json TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "usage_count INTEGER DEFAULT 0)"
        )
        try:
            self._pipeline_request(sql)
            self._pipeline_request("CREATE INDEX IF NOT EXISTS idx_cache_spelling ON ai_cache (spelling)")
        except CacheNetworkError:
            logger.warning("Cache table init failed (non-fatal)")
        except Exception as e:
            logger.warning(f"Cache table init unexpected error: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/database/test_cache_client.py -v --tb=short
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add database/cache_client.py tests/unit/database/test_cache_client.py
git commit -m "feat: add GlobalCacheClient for HTTP-based cache DB access"
```

---

## Task 4: Create V005_is_customized Migration

**Files:**
- Create: `database/migrations/V005_is_customized.py`
- Create: `tests/unit/database/migrations/test_v005_is_customized.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/database/migrations/test_v005_is_customized.py`:

```python
"""tests: V005_is_customized migration adds is_customized column."""
import sqlite3
import pytest
from database.migrations.V005_is_customized import apply


def _setup_db():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE ai_word_notes (voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT)"
    )
    cur.execute(
        "INSERT INTO ai_word_notes VALUES ('v1', 'hello', '你好')"
    )
    conn.commit()
    return conn


def test_adds_is_customized_column():
    conn = _setup_db()
    cur = conn.cursor()
    apply(cur)
    conn.commit()

    cur.execute("PRAGMA table_info(ai_word_notes)")
    columns = [row[1] for row in cur.fetchall()]
    assert "is_customized" in columns


def test_default_is_zero():
    conn = _setup_db()
    cur = conn.cursor()
    apply(cur)
    conn.commit()

    cur.execute("SELECT is_customized FROM ai_word_notes WHERE voc_id = 'v1'")
    row = cur.fetchone()
    assert row[0] == 0


def test_is_idempotent():
    conn = _setup_db()
    cur = conn.cursor()
    apply(cur)
    conn.commit()
    # Second run should not raise
    apply(cur)
    conn.commit()

    cur.execute("SELECT is_customized FROM ai_word_notes WHERE voc_id = 'v1'")
    row = cur.fetchone()
    assert row[0] == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/database/migrations/test_v005_is_customized.py -v --tb=short
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write migration**

Create `database/migrations/V005_is_customized.py`:

```python
"""
V005_is_customized.py: Add is_customized column to ai_word_notes.

User-edited memory_aid entries are marked is_customized=1 to prevent
cache overwrite. Default 0 (pure AI-generated, not user-edited).
"""
from __future__ import annotations
from typing import Any


def _column_exists(cur: Any, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    rows = cur.fetchall() or []
    for row in rows:
        name = row[1] if not isinstance(row, dict) else row.get("name")
        if str(name) == column:
            return True
    return False


def apply(cur: Any) -> None:
    if _column_exists(cur, "ai_word_notes", "is_customized"):
        return
    cur.execute("ALTER TABLE ai_word_notes ADD COLUMN is_customized INTEGER DEFAULT 0")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/database/migrations/test_v005_is_customized.py -v --tb=short
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/V005_is_customized.py tests/unit/database/migrations/test_v005_is_customized.py
git commit -m "feat: V005 migration — add is_customized column to ai_word_notes"
```

---

## Task 5: Add update_memory_aid to notes_repo.py

**Files:**
- Modify: `database/notes_repo.py`
- Modify: `database/sql_constants.py`
- Create: `tests/unit/database/test_update_memory_aid.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/database/test_update_memory_aid.py`:

```python
"""tests: update_memory_aid sets memory_aid + is_customized=1."""
import sqlite3
import pytest
from database.notes_repo import update_memory_aid


def _setup_db():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE ai_word_notes ("
        "voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, "
        "memory_aid TEXT, is_customized INTEGER DEFAULT 0)"
    )
    cur.execute(
        "INSERT INTO ai_word_notes VALUES ('v1', 'hello', '你好', '原始记忆', 0)"
    )
    conn.commit()
    return conn


def test_update_memory_aid_sets_customized():
    conn = _setup_db()
    ok = update_memory_aid("v1", "用户自定义记忆", conn=conn)
    assert ok

    cur = conn.cursor()
    cur.execute("SELECT memory_aid, is_customized FROM ai_word_notes WHERE voc_id = 'v1'")
    row = cur.fetchone()
    assert row[0] == "用户自定义记忆"
    assert row[1] == 1


def test_update_memory_aid_nonexistent_voc_id():
    conn = _setup_db()
    # Should not raise, returns True (no rows affected but no error)
    ok = update_memory_aid("v999", "记忆", conn=conn)
    assert ok
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/database/test_update_memory_aid.py -v --tb=short
```

Expected: FAIL with `ImportError: cannot import name 'update_memory_aid'`.

- [ ] **Step 3: Implement update_memory_aid in notes_repo.py**

Edit `database/notes_repo.py`, add before `__all__`:

```python
def update_memory_aid(
    voc_id: str,
    memory_aid: str,
    db_path: Optional[str] = None,
    conn: Any = None,
) -> bool:
    """Update memory_aid and mark is_customized=1.

    Called when user edits a word note's memory aid via Web UI or CLI.
    The is_customized flag prevents cache from overwriting user edits.
    """
    try:
        ts = get_timestamp_with_tz()
        sql = (
            "UPDATE ai_word_notes SET memory_aid = ?, is_customized = 1, updated_at = ? "
            "WHERE voc_id = ?"
        )
        return dispatch_write(sql, (memory_aid, ts, str(voc_id)), db_path=db_path, conn=conn)
    except (sqlite3.DatabaseError, OSError, ValueError) as e:
        _log_repo_failure("update_memory_aid", e)
        return False
    except Exception as e:
        _log_repo_failure("update_memory_aid", e)
        return False
```

- [ ] **Step 4: Add to __all__**

Edit `database/notes_repo.py` `__all__` list, add `"update_memory_aid"`.

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/unit/database/test_update_memory_aid.py -v --tb=short
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add database/notes_repo.py tests/unit/database/test_update_memory_aid.py
git commit -m "feat: add update_memory_aid to notes_repo (sets is_customized=1)"
```

---

## Task 6: Create WordLookup Orchestrator (core/word_lookup.py)

**Files:**
- Create: `core/word_lookup.py`
- Create: `tests/unit/core/test_word_lookup.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/core/test_word_lookup.py`:

```python
"""tests/unit/core/test_word_lookup.py: 3-level lookup orchestrator."""
import pytest
from unittest.mock import MagicMock, patch
from core.word_lookup import WordLookup, LookupResult
from database.cache_client import CacheNetworkError


@pytest.fixture
def mock_logger():
    return MagicMock()


@pytest.fixture
def mock_ai_client():
    client = MagicMock()
    client.generate_mnemonics.return_value = (
        [{"spelling": "hello", "basic_meanings": "你好", "raw_full_text": "..."}],
        {"total_tokens": 10, "request_id": "req-1"},
    )
    return client


@pytest.fixture
def mock_cache_client():
    return MagicMock()


@pytest.fixture
def lookup(mock_logger, mock_ai_client, mock_cache_client):
    return WordLookup(
        logger=mock_logger,
        ai_client=mock_ai_client,
        cache_client=mock_cache_client,
    )


class TestLevel1Local:
    def test_returns_local_when_found(self, lookup):
        mock_note = {"spelling": "hello", "basic_meanings": "你好"}
        with patch.object(lookup, "_find_local", return_value=mock_note):
            result = lookup.lookup("hello", "v1", "mimo")
            assert result.source == "local"
            assert result.note["spelling"] == "hello"

    def test_returns_local_customized_when_is_customized(self, lookup):
        mock_note = {"spelling": "hello", "basic_meanings": "你好", "is_customized": 1}
        with patch.object(lookup, "_find_local", return_value=mock_note):
            result = lookup.lookup("hello", "v1", "mimo")
            assert result.source == "local_customized"
            assert result.note["is_customized"] == 1


class TestLevel2Cache:
    def test_returns_cache_and_upserts_local(self, lookup):
        mock_note = {"spelling": "world", "basic_meanings": "世界"}
        with patch.object(lookup, "_find_local", return_value=None):
            with patch.object(lookup.cache_client, "find", return_value=mock_note):
                with patch.object(lookup, "_upsert_local") as mock_upsert:
                    result = lookup.lookup("world", "v1", "mimo")
                    assert result.source == "cache"
                    mock_upsert.assert_called_once()

    def test_skips_level2_when_local_customized(self, lookup):
        mock_note = {"spelling": "hello", "is_customized": 1}
        with patch.object(lookup, "_find_local", return_value=mock_note):
            result = lookup.lookup("hello", "v1", "mimo")
            assert result.source == "local_customized"
            lookup.cache_client.find.assert_not_called()


class TestLevel3AI:
    def test_calls_ai_when_all_miss(self, lookup, mock_ai_client):
        with patch.object(lookup, "_find_local", return_value=None):
            with patch.object(lookup.cache_client, "find", return_value=None):
                with patch.object(lookup, "_write_cache_async"):
                    result = lookup.lookup("newword", "v1", "mimo")
                    assert result.source == "ai"
                    mock_ai_client.generate_mnemonics.assert_called_once_with(["newword"])

    def test_returns_cache_on_ai_miss_then_cache_hit(self, lookup, mock_ai_client):
        mock_note = {"spelling": "cached", "basic_meanings": "缓存"}
        with patch.object(lookup, "_find_local", return_value=None):
            with patch.object(lookup.cache_client, "find", return_value=mock_note):
                result = lookup.lookup("cached", "v1", "mimo")
                assert result.source == "cache"
                mock_ai_client.generate_mnemonics.assert_not_called()


class TestCircuitBreaker:
    def test_cache_network_error_propagates(self, lookup, mock_cache_client):
        mock_cache_client.find.side_effect = CacheNetworkError("timeout")
        with patch.object(lookup, "_find_local", return_value=None):
            with pytest.raises(CacheNetworkError):
                lookup.lookup("hello", "v1", "mimo")

    def test_ai_error_propagates(self, lookup, mock_ai_client):
        mock_ai_client.generate_mnemonics.side_effect = Exception("API error")
        with patch.object(lookup, "_find_local", return_value=None):
            with patch.object(lookup.cache_client, "find", return_value=None):
                with pytest.raises(Exception) as exc_info:
                    lookup.lookup("newword", "v1", "mimo")
                assert "API error" in str(exc_info.value)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/core/test_word_lookup.py -v --tb=short
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

Create `core/word_lookup.py`:

```python
"""
core/word_lookup.py: 3-level word lookup orchestrator.

Flow:
  Level 1: User_Sync_DB (local ai_word_notes)
  Level 2: Global_Cache_DB (HTTP remote query)
  Level 3: LLM API (mimo/gemini)

CacheNetworkError propagates upward for batch-level circuit breaker.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from database.cache_client import CacheNetworkError, GlobalCacheClient
from database.notes_repo import get_local_word_note


@dataclass
class LookupResult:
    note: Dict[str, Any]
    source: str  # "local" | "local_customized" | "cache" | "ai"


class WordLookup:
    def __init__(
        self,
        logger: Any,
        ai_client: Any,
        cache_client: Optional[GlobalCacheClient],
        db_path: Optional[str] = None,
    ):
        self.logger = logger
        self.ai_client = ai_client
        self.cache_client = cache_client
        self.db_path = db_path

    def lookup(self, spelling: str, prompt_version: str, ai_provider: str) -> LookupResult:
        """3-level lookup. CacheNetworkError and APIError propagate upward."""

        # Level 1: Local User_Sync_DB
        local_note = self._find_local(spelling, prompt_version, ai_provider)
        if local_note:
            if local_note.get("is_customized"):
                return LookupResult(note=local_note, source="local_customized")
            return LookupResult(note=local_note, source="local")

        # Level 2: Global_Cache_DB (requires network)
        if self.cache_client:
            cached_note = self.cache_client.find(spelling, prompt_version, ai_provider)
            if cached_note:
                self._upsert_local(cached_note, prompt_version, ai_provider)
                return LookupResult(note=cached_note, source="cache")

        # Level 3: AI API
        ai_note = self._call_ai([spelling], prompt_version, ai_provider)
        if ai_note:
            self._save_local(ai_note, prompt_version, ai_provider)
            self._write_cache_async(ai_note, prompt_version, ai_provider)
            return LookupResult(note=ai_note, source="ai")

        # Should not reach here — AI returns something or raises
        raise RuntimeError(f"WordLookup: all levels exhausted for '{spelling}'")

    def _find_local(self, spelling: str, prompt_version: str, ai_provider: str) -> Optional[Dict[str, Any]]:
        """Level 1: Query local ai_word_notes by spelling.

        Uses explicit column names (not SELECT *) to avoid index-order fragility
        when migrations add columns. The SQL column list and the row-to-dict mapping
        are in 1:1 correspondence.
        """
        try:
            from database.session import with_read_session, DBSession

            # Explicit column list — matches the physical table + JOIN columns exactly.
            # When adding a column via migration, add it here too.
            _NOTE_FIELDS = (
                "voc_id, spelling, basic_meanings, ielts_focus, collocations, "
                "traps, synonyms, discrimination, example_sentences, memory_aid, "
                "word_ratings, raw_full_text, prompt_tokens, completion_tokens, "
                "total_tokens, batch_id, original_meanings, maimemo_context, "
                "it_level, it_history, updated_at, content_origin, "
                "content_source_db, content_source_scope, sync_status, "
                "match_confidence, match_reason, last_synced_content, "
                "is_customized"
            )
            _JOIN_FIELDS = "b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version"

            @with_read_session(default_return=None)
            def _find_by_spelling(session: DBSession = None):
                row = session.fetchone(
                    f"SELECT {_NOTE_FIELDS}, {_JOIN_FIELDS} "
                    "FROM ai_word_notes n "
                    "LEFT JOIN ai_batches b ON n.batch_id = b.batch_id "
                    "WHERE LOWER(n.spelling) = LOWER(?) "
                    "ORDER BY n.updated_at DESC "
                    "LIMIT 1",
                    (spelling,),
                )
                if row is None:
                    return None
                # Column names in same order as the SELECT above.
                # Using row[i] by index is safe here because SELECT lists columns explicitly.
                _all_columns = [
                    "voc_id", "spelling", "basic_meanings", "ielts_focus", "collocations",
                    "traps", "synonyms", "discrimination", "example_sentences", "memory_aid",
                    "word_ratings", "raw_full_text", "prompt_tokens", "completion_tokens",
                    "total_tokens", "batch_id", "original_meanings", "maimemo_context",
                    "it_level", "it_history", "updated_at", "content_origin",
                    "content_source_db", "content_source_scope", "sync_status",
                    "match_confidence", "match_reason", "last_synced_content",
                    "is_customized",
                    "batch_ai_provider", "batch_prompt_version",
                ]
                result = {}
                for i, col in enumerate(_all_columns):
                    if i < len(row):
                        result[col] = row[i]
                return result

            return _find_by_spelling()
        except Exception as e:
            self.logger.debug(f"Level 1 lookup error for {spelling}: {e}")
            return None

    def _call_ai(
        self, spellings: list[str], prompt_version: str, ai_provider: str
    ) -> Optional[Dict[str, Any]]:
        """Level 3: Call AI API for a single word."""
        try:
            results, metadata = self.ai_client.generate_mnemonics(spellings)
            if results and len(results) > 0:
                return results[0]
        except Exception as e:
            from core.exceptions import APIError
            raise APIError(f"AI generation failed for {spellings}: {e}") from e
        return None

    def _upsert_local(self, note: Dict[str, Any], prompt_version: str, ai_provider: str) -> None:
        """Merge cache note into local ai_word_notes (Level 2 hit)."""
        try:
            from database.notes_repo import save_ai_word_note
            from database.notes_repo import build_note_upsert_args
            voc_id = note.get("voc_id", "")
            if not voc_id:
                return
            # Build payload from cache note
            payload = {k: v for k, v in note.items() if k not in ("batch_ai_provider", "batch_prompt_version")}
            metadata = {
                "content_origin": "cache_hit",
                "prompt_version": prompt_version,
                "ai_provider": ai_provider,
            }
            save_ai_word_note(voc_id, payload, db_path=self.db_path, metadata=metadata)
        except Exception as e:
            self.logger.warning(f"Cache upsert local failed (non-fatal): {e}")

    def _save_local(self, note: Dict[str, Any], prompt_version: str, ai_provider: str) -> None:
        """Save AI result to local User_Sync_DB (Level 3)."""
        try:
            from database.notes_repo import save_ai_word_note
            voc_id = note.get("voc_id", "")
            if not voc_id:
                return
            metadata = {
                "content_origin": "ai_generated",
                "prompt_version": prompt_version,
                "ai_provider": ai_provider,
            }
            save_ai_word_note(voc_id, note, db_path=self.db_path, metadata=metadata)
        except Exception as e:
            self.logger.warning(f"AI result local save failed: {e}")

    def _write_cache_async(self, note: Dict[str, Any], prompt_version: str, ai_provider: str) -> None:
        """Fire-and-forget write to Global_Cache_DB."""
        if not self.cache_client:
            return
        try:
            import threading
            t = threading.Thread(
                target=self.cache_client.write,
                args=(note, prompt_version, ai_provider),
                daemon=True,
            )
            t.start()
        except Exception as e:
            self.logger.warning(f"Cache async write thread failed: {e}")
```

- [ ] **Step 4: Check if core/exceptions.py has APIError**

```bash
grep -n "APIError" core/exceptions.py
```

If not found, add to `core/exceptions.py`:

```python
class APIError(Exception):
    """AI API call failure."""
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/unit/core/test_word_lookup.py -v --tb=short
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add core/word_lookup.py core/exceptions.py tests/unit/core/test_word_lookup.py
git commit -m "feat: add WordLookup 3-level orchestrator with circuit breaker support"
```

---

## Task 7: Create V006_seed_global_cache Migration

**Files:**
- Create: `database/migrations/V006_seed_global_cache.py`
- Create: `tests/unit/database/migrations/test_v006_seed_global_cache.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/database/migrations/test_v006_seed_global_cache.py`:

```python
"""tests: V006 seeds ai_cache from existing ai_word_notes (when cache DB configured)."""
import sqlite3
import json
import pytest
from unittest.mock import patch, MagicMock
from database.migrations.V006_seed_global_cache import apply


def _setup_local_db():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE ai_word_notes ("
        "voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, "
        "content_origin TEXT, batch_id TEXT)"
    )
    cur.execute(
        "CREATE TABLE ai_batches ("
        "batch_id TEXT PRIMARY KEY, ai_provider TEXT, prompt_version TEXT)"
    )
    cur.execute(
        "INSERT INTO ai_word_notes VALUES ('v1', 'hello', '你好', 'ai_generated', 'b1')"
    )
    cur.execute(
        "INSERT INTO ai_batches VALUES ('b1', 'mimo', 'v1')"
    )
    conn.commit()
    return conn


def test_apply_skips_when_no_cache_config():
    """When TURSO_CACHE_DB_URL is not set, apply is a no-op."""
    conn = _setup_local_db()
    cur = conn.cursor()
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("TURSO_CACHE_DB_URL", None)
        # Should not raise
        apply(cur, cache_client=None)


def test_apply_seeds_with_cache_client():
    """When cache_client is provided, seeds ai_cache from ai_word_notes."""
    conn = _setup_local_db()
    cur = conn.cursor()

    mock_cache = MagicMock()
    mock_cache._seed_calls = []

    def fake_write(note, prompt_version, ai_provider):
        mock_cache._seed_calls.append((note, prompt_version, ai_provider))

    mock_cache.write = fake_write

    apply(cur, cache_client=mock_cache)
    assert len(mock_cache._seed_calls) == 1
    note, pv, provider = mock_cache._seed_calls[0]
    assert note["spelling"] == "hello"
    assert pv == "v1"
    assert provider == "mimo"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/database/migrations/test_v006_seed_global_cache.py -v --tb=short
```

Expected: FAIL.

- [ ] **Step 3: Write migration**

Create `database/migrations/V006_seed_global_cache.py`:

```python
"""
V006_seed_global_cache.py: Seed Global_Cache_DB with existing ai_generated notes.

Reads from local ai_word_notes WHERE content_origin = 'ai_generated',
JOINs ai_batches for prompt_version/ai_provider, writes to cache via GlobalCacheClient.

This is a one-time seeding operation. The migration itself is idempotent
(INSERT OR IGNORE on cache keys), but the heavy lifting depends on cache_client.
"""
from __future__ import annotations

import json
from typing import Any, Optional


def apply(cur: Any, cache_client: Optional[Any] = None) -> None:
    """Seed global cache from local ai_word_notes.

    Args:
        cur: Local DB cursor (for reading ai_word_notes).
        cache_client: GlobalCacheClient instance. If None, skip (no cache configured).
    """
    if cache_client is None:
        return

    try:
        cur.execute(
            "SELECT n.voc_id, n.spelling, n.basic_meanings, n.ielts_focus, "
            "n.collocations, n.traps, n.synonyms, n.discrimination, "
            "n.example_sentences, n.memory_aid, n.word_ratings, n.raw_full_text, "
            "n.batch_id, b.ai_provider, b.prompt_version "
            "FROM ai_word_notes n "
            "LEFT JOIN ai_batches b ON n.batch_id = b.batch_id "
            "WHERE n.content_origin = 'ai_generated'"
        )
        rows = cur.fetchall()
    except Exception:
        return

    columns = [
        "voc_id", "spelling", "basic_meanings", "ielts_focus", "collocations",
        "traps", "synonyms", "discrimination", "example_sentences", "memory_aid",
        "word_ratings", "raw_full_text", "batch_id", "ai_provider", "prompt_version",
    ]

    for row in rows:
        note = {}
        for i, col in enumerate(columns):
            if i < len(row):
                note[col] = row[i]

        spelling = note.get("spelling", "")
        prompt_version = note.get("prompt_version") or "v1_legacy_structured"
        ai_provider = note.get("ai_provider") or "mimo"

        if not spelling:
            continue

        # Fire-and-forget: each write is independent
        try:
            cache_client.write(note, prompt_version, ai_provider)
        except Exception:
            pass  # fire-and-forget, individual failures don't block others
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/database/migrations/test_v006_seed_global_cache.py -v --tb=short
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/V006_seed_global_cache.py tests/unit/database/migrations/test_v006_seed_global_cache.py
git commit -m "feat: V006 migration — seed Global_Cache_DB from existing ai_generated notes"
```

---

## Task 8: Integrate WordLookup into study_workflow.py

**Files:**
- Modify: `core/study_workflow.py`
- Modify: `core/word_service.py` (if needed for `get_notes_in_batch` compatibility)

- [ ] **Step 1: Add WordLookup initialization to StudyWorkflow.__init__**

Edit `core/study_workflow.py`, add imports and initialization:

```python
from core.feature_flags import is_enabled
from core.word_lookup import WordLookup
from database.cache_client import GlobalCacheClient, CacheNetworkError
from core.exceptions import APIError
```

In `__init__`, after `self.word_service = ...`:

```python
        # Global Cache Client (initialized only when flag is enabled)
        self.cache_client = None
        self.word_lookup = None
        if is_enabled("GLOBAL_CACHE_ENABLED"):
            import config as _config
            cache_url = getattr(_config, "TURSO_CACHE_DB_URL", None)
            cache_token = getattr(_config, "TURSO_CACHE_AUTH_TOKEN", None)
            cache_timeout = getattr(_config, "CACHE_TIMEOUT_S", 3.0)
            if cache_url and cache_token:
                self.cache_client = GlobalCacheClient(cache_url, cache_token, cache_timeout)
                self.word_lookup = WordLookup(
                    logger=logger,
                    ai_client=ai_client,
                    cache_client=self.cache_client,
                    db_path=db_path,
                )
                try:
                    self.cache_client.init_table()
                except Exception:
                    self.logger.warning("Cache table init failed (non-fatal)")
```

- [ ] **Step 2: Modify _run_ai_batch to use per-word lookup before AI**

Replace `_run_ai_batch`. Key design: each word is fully resolved within the per-word loop (L1/L2/L3 are all闭环). No post-loop batch AI call needed — that would cause duplicate token charges for L1/L3 hits.

```python
    def _run_ai_batch(self, batch_no, total_batches, batch_spells):
        """Execute single batch: per-word L1/L2 lookup → AI for misses."""
        self.logger.info(
            f"[AI] 批次 {batch_no}/{total_batches} 开始处理（{len(batch_spells)} 词）",
            module="study_workflow",
        )

        if not self.word_lookup:
            # Legacy path: direct batch AI call (flag disabled)
            try:
                results, metadata = self.ai_client.generate_mnemonics(batch_spells)
                return results or [], metadata or {}
            except Exception as exc:
                self.logger.warning(f"AI 批次 {batch_no}/{total_batches} 失败: {exc}")
                return [], {}

        # Unified results list — all L1/L2/L3 hits go here
        ai_results = []
        network_available = True
        prompt_version = getattr(self.ai_client, "prompt_version", "")
        ai_provider = config.AI_PROVIDER

        for word in batch_spells:
            if not network_available:
                # Circuit broken — skip remaining words (they go to pending)
                continue
            try:
                result = self.word_lookup.lookup(word, prompt_version, ai_provider)

                if result.source in ("local", "local_customized"):
                    self.logger.debug(f"[Cache] L1 hit: {word} ({result.source})")
                    ai_results.append(result.note)  # 合流：L1 命中也必须收集
                elif result.source == "cache":
                    self.logger.debug(f"[Cache] L2 hit: {word}")
                    ai_results.append(result.note)
                elif result.source == "ai":
                    self.logger.debug(f"[Cache] L3 miss → AI generated: {word}")
                    ai_results.append(result.note)

            except CacheNetworkError:
                self.logger.warning(f"[Cache] Network unavailable, circuit broken at word: {word}")
                network_available = False  # 触发熔断
            except APIError as e:
                self.logger.warning(f"[Cache] AI failed for {word}: {e}")
                # 单词 AI 失败不触发熔断，由下游自然留空

        # No post-loop batch AI call — every word was already resolved in the loop
        if not ai_results and not network_available:
            self.logger.warning(f"Batch {batch_no}/{total_batches}: cache unavailable, all words pending")
            return [], {}

        return ai_results, {"total_latency_ms": 0}
```

**Why no post-loop batch AI?** In the per-word loop, WordLookup.lookup() already handles L3 internally — if a word isn't in L1 or L2, it calls `generate_mnemonics([single_word])` and returns the result. Every word is fully resolved before the loop ends. A post-loop batch call would re-invoke AI for L1/L3 hits, wasting tokens.

- [ ] **Step 3: Add is_customized protection in _process_results**

In `_process_results`, when saving results, check if existing note has `is_customized=1` and skip overwrite:

```python
    # Add at the beginning of the for loop in _process_results, before notes_to_save.append:
            # Check if user has customized this note — skip AI overwrite
            if self.word_lookup:
                try:
                    existing = self.word_lookup._find_local(spell, "", "")
                    if existing and existing.get("is_customized"):
                        self.logger.info(f"[保护] {spell} 已自定义，跳过 AI 覆盖")
                        continue
                except Exception:
                    pass  # Non-fatal
```

- [ ] **Step 4: Run existing tests**

```bash
pytest tests/core/test_study_workflow.py -v --tb=short
```

Expected: All pass (flag defaults to `False`, legacy path unchanged).

- [ ] **Step 5: Run all unit tests**

```bash
pytest tests/ -v --tb=short -m "not slow"
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add core/study_workflow.py
git commit -m "feat: integrate WordLookup into study_workflow with per-word L1/L2 lookup"
```

---

## Task 9: Update SQL Constants for is_customized

**Files:**
- Modify: `database/sql_constants.py`

- [ ] **Step 1: Add is_customized to NOTE_UPSERT_SQL**

Edit `database/sql_constants.py`, update `NOTE_UPSERT_SQL`:

The current SQL has 25 placeholders. We need to add `is_customized` as the 26th column.

Change:
```python
NOTE_UPSERT_SQL = (
    "INSERT OR REPLACE INTO ai_word_notes ("
    "voc_id, spelling, basic_meanings, ielts_focus, collocations, traps, synonyms, discrimination, "
    "example_sentences, memory_aid, word_ratings, raw_full_text, prompt_tokens, completion_tokens, "
    "total_tokens, batch_id, original_meanings, maimemo_context, content_origin, content_source_db, "
    "content_source_scope, sync_status, match_confidence, match_reason, updated_at"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
```

To:
```python
NOTE_UPSERT_SQL = (
    "INSERT OR REPLACE INTO ai_word_notes ("
    "voc_id, spelling, basic_meanings, ielts_focus, collocations, traps, synonyms, discrimination, "
    "example_sentences, memory_aid, word_ratings, raw_full_text, prompt_tokens, completion_tokens, "
    "total_tokens, batch_id, original_meanings, maimemo_context, content_origin, content_source_db, "
    "content_source_scope, sync_status, match_confidence, match_reason, updated_at, is_customized"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
```

- [ ] **Step 2: Update build_note_upsert_args in notes_repo.py**

Add `is_customized` to the args tuple (append at end):

```python
    return (
        # ... existing 25 values ...
        timestamp,
        int(note.get("is_customized", 0)),  # NEW: 26th placeholder
    )
```

- [ ] **Step 3: Update _NOTE_COLUMNS list**

Add `"is_customized"` to the `_NOTE_COLUMNS` list in `notes_repo.py`.

- [ ] **Step 4: Run existing notes_repo tests**

```bash
pytest tests/unit/database/ -v --tb=short
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add database/sql_constants.py database/notes_repo.py
git commit -m "feat: add is_customized to NOTE_UPSERT_SQL and build_note_upsert_args"
```

---

## Task 10: Update conftest.py for New Env Vars

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add cache env vars to cloud isolation fixture**

Edit `tests/conftest.py`, add to `isolate_cloud_configuration`:

```python
    monkeypatch.delenv("TURSO_CACHE_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_CACHE_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CACHE_TIMEOUT_S", raising=False)
    monkeypatch.delenv("GLOBAL_CACHE_ENABLED", raising=False)
```

And in the module patching loop:

```python
        if hasattr(module, "TURSO_CACHE_DB_URL"):
            monkeypatch.setattr(module, "TURSO_CACHE_DB_URL", None, raising=False)
        if hasattr(module, "TURSO_CACHE_AUTH_TOKEN"):
            monkeypatch.setattr(module, "TURSO_CACHE_AUTH_TOKEN", None, raising=False)
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/ -v --tb=short -m "not slow"
```

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "chore: isolate cache env vars in test fixtures"
```

---

## Task 11: End-to-End Integration Test

**Files:**
- Create: `tests/integration/test_word_lookup_flow.py`

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_word_lookup_flow.py`:

```python
"""tests/integration/test_word_lookup_flow.py: End-to-end 3-level lookup test."""
import sqlite3
import pytest
from unittest.mock import MagicMock, patch
from core.word_lookup import WordLookup, LookupResult
from database.cache_client import CacheNetworkError


def _setup_local_db():
    """Create an in-memory DB with ai_word_notes + ai_batches."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE ai_word_notes ("
        "voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, "
        "ielts_focus TEXT, collocations TEXT, traps TEXT, synonyms TEXT, "
        "discrimination TEXT, example_sentences TEXT, memory_aid TEXT, "
        "word_ratings TEXT, raw_full_text TEXT, prompt_tokens INTEGER DEFAULT 0, "
        "completion_tokens INTEGER DEFAULT 0, total_tokens INTEGER DEFAULT 0, "
        "batch_id TEXT, original_meanings TEXT, maimemo_context TEXT, "
        "content_origin TEXT, content_source_db TEXT, content_source_scope TEXT, "
        "it_level INTEGER DEFAULT 0, it_history TEXT, sync_status INTEGER DEFAULT 0, "
        "match_confidence REAL, match_reason TEXT, last_synced_content TEXT, "
        "is_customized INTEGER DEFAULT 0, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "CREATE TABLE ai_batches ("
        "batch_id TEXT PRIMARY KEY, request_id TEXT, ai_provider TEXT, "
        "model_name TEXT, prompt_version TEXT, batch_size INTEGER, "
        "total_latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, "
        "total_tokens INTEGER, finish_reason TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    return conn


def test_level1_local_hit():
    """L1: word exists in local ai_word_notes → return local."""
    conn = _setup_local_db()
    conn.execute(
        "INSERT INTO ai_word_notes (voc_id, spelling, basic_meanings) VALUES ('v1', 'hello', '你好')"
    )
    conn.commit()

    logger = MagicMock()
    ai_client = MagicMock()
    cache_client = MagicMock()

    lookup = WordLookup(logger=logger, ai_client=ai_client, cache_client=cache_client)

    # Patch _find_local to use our test DB
    def fake_find_local(spelling, prompt_version, ai_provider):
        cur = conn.cursor()
        cur.execute("SELECT * FROM ai_word_notes WHERE LOWER(spelling) = LOWER(?)", (spelling,))
        row = cur.fetchone()
        if row:
            return {"voc_id": "v1", "spelling": "hello", "basic_meanings": "你好", "is_customized": 0}
        return None

    with patch.object(lookup, "_find_local", side_effect=fake_find_local):
        result = lookup.lookup("hello", "v1", "mimo")
        assert result.source == "local"
        cache_client.find.assert_not_called()


def test_level1_customized_skip_cache():
    """L1 customized: is_customized=1 → skip L2/L3, return local_customized."""
    conn = _setup_local_db()
    conn.execute(
        "INSERT INTO ai_word_notes (voc_id, spelling, memory_aid, is_customized) "
        "VALUES ('v1', 'hello', '自定义记忆', 1)"
    )
    conn.commit()

    logger = MagicMock()
    ai_client = MagicMock()
    cache_client = MagicMock()

    lookup = WordLookup(logger=logger, ai_client=ai_client, cache_client=cache_client)

    def fake_find_local(spelling, prompt_version, ai_provider):
        return {"voc_id": "v1", "spelling": "hello", "memory_aid": "自定义记忆", "is_customized": 1}

    with patch.object(lookup, "_find_local", side_effect=fake_find_local):
        result = lookup.lookup("hello", "v1", "mimo")
        assert result.source == "local_customized"
        cache_client.find.assert_not_called()
        ai_client.generate_mnemonics.assert_not_called()


def test_network_error_circuit_breaker():
    """CacheNetworkError propagates up — batch-level circuit breaker can catch it."""
    logger = MagicMock()
    ai_client = MagicMock()
    cache_client = MagicMock()
    cache_client.find.side_effect = CacheNetworkError("timeout")

    lookup = WordLookup(logger=logger, ai_client=ai_client, cache_client=cache_client)

    with patch.object(lookup, "_find_local", return_value=None):
        with pytest.raises(CacheNetworkError):
            lookup.lookup("hello", "v1", "mimo")


def test_full_flow_cache_miss_then_ai():
    """Full flow: L1 miss → L2 miss → L3 AI → save local + async cache write."""
    conn = _setup_local_db()

    logger = MagicMock()
    ai_client = MagicMock()
    ai_client.generate_mnemonics.return_value = (
        [{"spelling": "newword", "basic_meanings": "新词", "voc_id": "v99"}],
        {"total_tokens": 5, "request_id": "req-1"},
    )

    cache_client = MagicMock()
    cache_client.find.return_value = None  # cache miss

    lookup = WordLookup(logger=logger, ai_client=ai_client, cache_client=cache_client)

    with patch.object(lookup, "_find_local", return_value=None):
        with patch.object(lookup, "_save_local") as mock_save:
            with patch.object(lookup, "_write_cache_async") as mock_cache_write:
                result = lookup.lookup("newword", "v1", "mimo")
                assert result.source == "ai"
                mock_save.assert_called_once()
                mock_cache_write.assert_called_once()
```

- [ ] **Step 2: Run integration test**

```bash
pytest tests/integration/test_word_lookup_flow.py -v --tb=short
```

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_word_lookup_flow.py
git commit -m "test: add integration tests for 3-level WordLookup flow"
```

---

## Task 12: Full Test Suite Verification

- [ ] **Step 1: Run all tests**

```bash
pytest tests/ -v --tb=short -m "not slow"
```

Expected: All pass.

- [ ] **Step 2: Run py_compile on new/modified files**

```bash
python -m py_compile core/word_lookup.py
python -m py_compile database/cache_client.py
python -m py_compile database/notes_repo.py
python -m py_compile database/sql_constants.py
python -m py_compile core/study_workflow.py
python -m py_compile core/feature_flags.py
python -m py_compile core/settings.py
python -m py_compile config.py
python -m py_compile database/migrations/V005_is_customized.py
python -m py_compile database/migrations/V006_seed_global_cache.py
```

Expected: No errors.

- [ ] **Step 3: Verify migration runner discovers new migrations**

```python
python -c "from database.migrations.runner import target_version; print(target_version())"
```

Expected: `6`

---

## Spec Coverage Checklist

| Spec Section | Implemented In |
|---|---|
| §2.1 Two DB entities | Task 2 (config), Task 3 (cache_client) |
| §2.2 3-level lookup flow | Task 6 (word_lookup.py) |
| §3.1 core/word_lookup.py | Task 6 |
| §3.2 database/cache_client.py | Task 3 |
| §3.3 Module responsibility split | Task 8 (study_workflow) |
| §4.1 is_customized column | Task 4 (V005 migration), Task 9 (SQL) |
| §4.2 ai_cache table | Task 3 (init_table) |
| §4.3 Seed data | Task 7 (V006 migration) |
| §5 Config changes | Task 2 (config.py) |
| §6 File change list | All tasks above |
| §7 Data safety (VACUUM INTO) | Deferred — can add as separate task |
| §8 Offline/exception matrix | Tested in Tasks 6, 11 |
| §9.1 Feature flag | Task 1 |
| §9.2 Incremental dev strategy | Each task is independently deployable with flag=false |
| §9.3 Flag branch code | Task 8 |
| §10 Turso setup guide | Documentation only, no code changes needed |

## Deferred Items

1. **VACUUM INTO backup** (§7.1): The V005 migration does not yet include automatic pre-migration backup. Add in a follow-up task if needed.
2. **ui_manager source tag** (§6 file list): Display source label ("local" / "cache" / "ai") in CLI output — low priority, can be a follow-up.
3. **Web UI integration**: The Web frontend would need similar source-tag display. Not in scope for this plan.
