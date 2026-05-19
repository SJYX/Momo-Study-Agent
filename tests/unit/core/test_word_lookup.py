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
