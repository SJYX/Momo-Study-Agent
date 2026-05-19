"""tests/integration/test_word_lookup_flow.py: End-to-end 3-level lookup test.

Covers: L1 local hit, L1 customized skip, L2 cache hit, L3 AI full chain,
        cache network error circuit breaker, LLM retry limit.
"""
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
