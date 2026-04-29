"""
tests/web/test_deps.py -- web.backend.deps module tests.
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from web.backend import deps


class TestInitDeps:
    def setup_method(self):
        deps._active_user = None
        deps._logger = None
        deps._momo_api = None
        deps._ai_client = None
        deps._workflow = None
        deps._task_registry = None
        deps._logger_bridge = None

    def test_init_deps_sets_singletons(self):
        ml, mm, ma, mw, mr, mb = MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()
        deps.init_deps(active_user="u", logger=ml, momo_api=mm, ai_client=ma, workflow=mw, task_registry=mr, logger_bridge=mb)
        assert deps.get_active_user() == "u"
        assert deps.get_logger() is ml
        assert deps.get_momo_api() is mm
        assert deps.get_ai_client() is ma
        assert deps.get_workflow() is mw
        assert deps.get_task_registry() is mr

    def test_cleanup_calls_shutdown(self):
        mw = MagicMock()
        mm = MagicMock()
        ma = MagicMock()
        mr = MagicMock()
        mm.close = MagicMock()
        ma.close = MagicMock()
        deps.init_deps(active_user="u", logger=MagicMock(), momo_api=mm, ai_client=ma, workflow=mw, task_registry=mr, logger_bridge=MagicMock())
        deps.cleanup_deps()
        mw.shutdown.assert_called_once()
        mr.shutdown.assert_called_once()

    def test_get_active_user_default(self):
        deps._active_user = None
        assert deps.get_active_user() == "default"

    def test_reload_user_services_gemini(self):
        import config as cfg
        cfg.MOMO_TOKEN = "fake"
        cfg.AI_PROVIDER = "gemini"
        cfg.GEMINI_API_KEY = "fake"
        mw = MagicMock()
        deps._workflow = mw
        deps._momo_api = MagicMock()
        deps._ai_client = MagicMock()
        with patch("core.maimemo_api.MaiMemoAPI", return_value=MagicMock()), \
             patch("core.gemini_client.GeminiClient", return_value=MagicMock()):
            deps.reload_user_services()
        assert deps._momo_api is not None
        assert deps._ai_client is not None

    def test_reload_user_services_mimo(self):
        import config as cfg
        cfg.MOMO_TOKEN = "fake"
        cfg.AI_PROVIDER = "mimo"
        cfg.MIMO_API_KEY = "fake"
        mw = MagicMock()
        deps._workflow = mw
        deps._momo_api = MagicMock()
        deps._ai_client = MagicMock()
        with patch("core.maimemo_api.MaiMemoAPI", return_value=MagicMock()), \
             patch("core.mimo_client.MimoClient", return_value=MagicMock()):
            deps.reload_user_services()
        assert deps._ai_client is not None
