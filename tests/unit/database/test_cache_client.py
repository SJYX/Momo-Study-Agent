"""Tests for database/cache_client.py: GlobalCacheClient and CacheWriteWorker."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from database.cache_client import CacheNetworkError, CacheWriteWorker, GlobalCacheClient


@pytest.fixture
def client():
    return GlobalCacheClient(url="https://example.turso.io", token="test-token")


# ── cache_key ──────────────────────────────────────────────────────

def test_cache_key_deterministic(client):
    key1 = client.cache_key("hello", "v1", "mimo")
    key2 = client.cache_key("hello", "v1", "mimo")
    assert key1 == key2
    assert len(key1) == 16


def test_cache_key_different_inputs():
    k1 = GlobalCacheClient.cache_key("hello", "v1", "mimo")
    k2 = GlobalCacheClient.cache_key("world", "v1", "mimo")
    assert k1 != k2


# ── find() ─────────────────────────────────────────────────────────

def test_find_returns_note_on_200(client):
    note_data = {"spelling": "hello", "basic_meanings": "你好"}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [{
            "type": "ok",
            "response": {
                "result": {
                    "rows": [[{"value": json.dumps(note_data)}]]
                }
            }
        }]
    }
    with patch.object(client.session, "post", return_value=mock_resp):
        result = client.find("hello", "v1", "mimo")
        assert result is not None
        assert result["spelling"] == "hello"


def test_find_returns_none_on_non_200(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not found"
    with patch.object(client.session, "post", return_value=mock_resp):
        result = client.find("hello", "v1", "mimo")
        assert result is None


def test_find_returns_none_on_pipeline_error(client):
    """Pipeline returns type=error → find() returns None."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [{"type": "error", "error": {"message": "table not found"}}]
    }
    with patch.object(client.session, "post", return_value=mock_resp):
        result = client.find("hello", "v1", "mimo")
        assert result is None


def test_find_returns_none_on_empty_results(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": []}
    with patch.object(client.session, "post", return_value=mock_resp):
        result = client.find("hello", "v1", "mimo")
        assert result is None


def test_find_returns_none_on_empty_rows(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [{
            "type": "ok",
            "response": {
                "result": {"rows": []}
            }
        }]
    }
    with patch.object(client.session, "post", return_value=mock_resp):
        result = client.find("hello", "v1", "mimo")
        assert result is None


# ── _pipeline_request ──────────────────────────────────────────────

def test_pipeline_request_checks_result_type(client):
    """_pipeline_request returns None when results contain error type."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [{"type": "error", "error": {"message": "syntax error"}}]
    }
    with patch.object(client.session, "post", return_value=mock_resp):
        result = client._pipeline_request("BAD SQL")
        assert result is None


def test_pipeline_request_raises_on_timeout(client):
    import requests
    with patch.object(client.session, "post", side_effect=requests.Timeout("timeout")):
        with pytest.raises(CacheNetworkError, match="timeout"):
            client._pipeline_request("SELECT 1")


def test_pipeline_request_raises_on_connection_error(client):
    import requests
    with patch.object(client.session, "post", side_effect=requests.ConnectionError("conn refused")):
        with pytest.raises(CacheNetworkError, match="connection"):
            client._pipeline_request("SELECT 1")


# ── CacheWriteWorker ───────────────────────────────────────────────

def test_cache_write_worker_submit():
    """CacheWriteWorker.submit puts item in queue without blocking."""
    mock_client = MagicMock()
    worker = CacheWriteWorker(mock_client)
    worker.submit({"spelling": "hello"}, "v1", "mimo")
    time.sleep(0.1)
    mock_client.write.assert_called_once()


def test_cache_write_worker_full_queue():
    """CacheWriteWorker.submit drops item when queue is full (no exception)."""
    mock_client = MagicMock()
    worker = CacheWriteWorker(mock_client)
    # Fill the queue
    for i in range(256):
        worker._queue.put_nowait(({"spelling": f"w{i}"}, "v1", "mimo"))
    # This should not raise
    worker.submit({"spelling": "overflow"}, "v1", "mimo")
