"""
tests/web/test_deps.py -- web.backend.deps module tests.

P1 重构后 deps 不再持有单例服务实例，改为通过 UserContextManager
按请求级 profile 解析 ctx。本测试覆盖：
- init_deps 注册 UserContextManager
- cleanup_deps 调用 cleanup_all
- get_active_user header 优先级（缺失时 fallback → "default"）
- reload_user_services 已废弃为 no-op
"""
from __future__ import annotations
from unittest.mock import MagicMock
import pytest
from web.backend import deps


class TestInitDeps:
    def setup_method(self):
        deps._context_manager = None
        deps._fallback_user = None

    def test_init_deps_registers_context_manager(self):
        cm = MagicMock()
        deps.init_deps(cm, fallback_user="alice")
        assert deps._context_manager is cm
        assert deps._fallback_user == "alice"

    def test_cleanup_deps_calls_cleanup_all(self):
        cm = MagicMock()
        deps.init_deps(cm, fallback_user="alice")
        deps.cleanup_deps()
        cm.cleanup_all.assert_called_once()
        assert deps._context_manager is None

    def test_resolve_profile_uses_header(self):
        deps._fallback_user = "alice"
        assert deps._resolve_profile("Bob") == "bob"

    def test_resolve_profile_falls_back_when_no_header(self):
        deps._fallback_user = "alice"
        assert deps._resolve_profile(None) == "alice"

    def test_resolve_profile_default_when_no_fallback(self):
        deps._fallback_user = None
        assert deps._resolve_profile(None) == "default"

    def test_reload_user_services_is_noop(self):
        # P1 后该函数仅保留兼容签名
        assert deps.reload_user_services() is None
