"""
tests/web/test_app_factory.py -- create_app factory tests.
"""
from __future__ import annotations
from unittest.mock import patch
import pytest


class TestCreateApp:
    def test_create_app_returns_fastapi(self):
        from fastapi import FastAPI
        from web.backend.app import create_app
        with patch("web.backend.app.lifespan"):
            app = create_app()
        assert isinstance(app, FastAPI)
        assert app.title == "MOMO Study Agent Web UI"

    def test_create_app_has_cors(self):
        from web.backend.app import create_app
        with patch("web.backend.app.lifespan"):
            app = create_app()
        cors = any("CORSMiddleware" in str(m.cls) for m in app.user_middleware)
        assert cors

    def test_create_app_registers_routes(self):
        from web.backend.app import create_app
        with patch("web.backend.app.lifespan"):
            app = create_app()
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/api/health" in r for r in routes)
        assert any("/api/session" in r for r in routes)
        assert any("/api/study" in r for r in routes)

    def test_health_via_factory(self):
        from fastapi.testclient import TestClient
        from web.backend.app import create_app
        # Patch lifespan to a no-op async context manager
        import contextlib

        @contextlib.asynccontextmanager
        async def _noop(app):
            yield

        with patch("web.backend.app.lifespan", _noop):
            app = create_app()
        # Override lifespan_context on the router to avoid nested patch issues
        app.router.lifespan_context = _noop
        with TestClient(app) as c:
            resp = c.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
