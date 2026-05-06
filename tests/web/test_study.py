"""
tests/web/test_study.py -- /api/study/* endpoint tests.
"""
from __future__ import annotations
from unittest.mock import MagicMock
import pytest


class TestStudyToday:
    def test_today_returns_items(self, client):
        resp = client.get("/api/study/today")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["count"] == 2

    def test_today_api_error(self, client, mock_momo):
        mock_momo.get_today_items = MagicMock(side_effect=RuntimeError("Network error"))
        resp = client.get("/api/study/today")
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "MAIMO_API_ERROR"


class TestStudyFuture:
    def test_future_default_days(self, client):
        resp = client.get("/api/study/future")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["days"] == 7

    def test_future_custom_days(self, client):
        resp = client.get("/api/study/future?days=14")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["days"] == 14

    def test_future_days_validation(self, client):
        resp = client.get("/api/study/future?days=0")
        assert resp.status_code == 422

    def test_future_api_error(self, client, mock_momo):
        mock_momo.query_study_records = MagicMock(side_effect=RuntimeError("Timeout"))
        resp = client.get("/api/study/future")
        body = resp.json()
        assert body["ok"] is False

    def test_future_empty_records(self, client, mock_momo):
        mock_momo.query_study_records = MagicMock(return_value={"data": {"records": []}})
        resp = client.get("/api/study/future")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["count"] == 0


class TestStudyProcess:
    def test_process_returns_task_id(self, client):
        resp = client.post("/api/study/process")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["task_id"] is not None
        assert body["data"]["word_count"] == 2

    def test_process_no_items(self, client, mock_momo):
        mock_momo.get_today_items = MagicMock(return_value={"data": {"today_items": []}})
        resp = client.post("/api/study/process")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["task_id"] is None

    def test_process_api_error(self, client, mock_momo):
        mock_momo.get_today_items = MagicMock(side_effect=RuntimeError("Auth failed"))
        resp = client.post("/api/study/process")
        body = resp.json()
        assert body["ok"] is False

    def test_process_with_voc_ids_filters_items(self, client):
        resp = client.post("/api/study/process", json={"voc_ids": ["v1"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["task_id"] is not None
        assert body["data"]["word_count"] == 1

    def test_process_with_unmatched_voc_ids(self, client):
        resp = client.post("/api/study/process", json={"voc_ids": ["not_exist"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["task_id"] is None
        assert body["data"]["message"] == "指定的单词今日无需处理或不存在"


class TestStudyProcessFuture:
    def test_process_future_returns_task_id(self, client):
        resp = client.post("/api/study/process-future")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["task_id"] is not None

    def test_process_future_no_records(self, client, mock_momo):
        mock_momo.query_study_records = MagicMock(return_value={"data": {"records": []}})
        resp = client.post("/api/study/process-future")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["task_id"] is None


class TestStudyIterate:
    def test_iterate_returns_task_id(self, client):
        resp = client.post("/api/study/iterate")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["task_id"] is not None
