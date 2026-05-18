"""
tests/web/test_preflight.py -- GET /api/preflight test.
"""
from __future__ import annotations
import pytest


class TestPreflight:
    def test_preflight_returns_ok(self, client, monkeypatch):
        fake_result = {"username":"testuser","root_dir":"/dir","profile_path":"/p.env","force_cloud_mode":False,"ok":True,"checks":[{"name":"config","ok":True,"status":"ok","blocking":False,"category":"config","detail":"fine","fix_hint":""}],"blocking_items":[]}
        monkeypatch.setattr("core.preflight.run_preflight", lambda root_dir, username: fake_result)
        monkeypatch.setattr("config.BASE_DIR", "/dir")
        resp = client.get("/api/preflight")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["ok"] is True
        assert len(body["data"]["checks"]) == 1

    def test_preflight_with_failures(self, client, monkeypatch):
        fake_result = {"username":"testuser","root_dir":"/dir","profile_path":"/p.env","force_cloud_mode":False,"ok":False,"checks":[{"name":"token","ok":False,"status":"fail","blocking":True,"category":"creds","detail":"bad","fix_hint":"fix"}],"blocking_items":[{"name":"token","ok":False,"status":"fail","blocking":True,"category":"creds","detail":"bad","fix_hint":"fix"}]}
        monkeypatch.setattr("core.preflight.run_preflight", lambda root_dir, username: fake_result)
        monkeypatch.setattr("config.BASE_DIR", "/dir")
        body = client.get("/api/preflight").json()
        assert body["data"]["ok"] is False
        assert len(body["data"]["blocking_items"]) == 1

    def test_preflight_user_id(self, client, monkeypatch):
        fake_result = {"username":"testuser","root_dir":"/dir","profile_path":"","force_cloud_mode":False,"ok":True,"checks":[],"blocking_items":[]}
        monkeypatch.setattr("core.preflight.run_preflight", lambda root_dir, username: fake_result)
        monkeypatch.setattr("config.BASE_DIR", "/dir")
        body = client.get("/api/preflight").json()
        assert body["user_id"] == "testuser"
