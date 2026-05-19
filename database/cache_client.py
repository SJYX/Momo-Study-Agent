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
