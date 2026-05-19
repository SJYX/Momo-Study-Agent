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
