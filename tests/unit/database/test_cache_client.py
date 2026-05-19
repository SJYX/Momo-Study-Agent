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
