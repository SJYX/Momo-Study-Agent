import os
import sys

import pytest


@pytest.fixture(autouse=True)
def isolate_cloud_configuration(monkeypatch):
    """让测试统一使用本地模式，避免仓库 .env 里的云端配置污染用例。"""
    monkeypatch.setenv("FORCE_CLOUD_MODE", "False")
    monkeypatch.delenv("TURSO_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TURSO_DB_HOSTNAME", raising=False)
    monkeypatch.delenv("TURSO_TEST_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_TEST_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TURSO_TEST_DB_HOSTNAME", raising=False)
    monkeypatch.delenv("TURSO_HUB_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_HUB_AUTH_TOKEN", raising=False)

    for module_name in ("config", "core.db_manager", "main"):
        module = sys.modules.get(module_name)
        if module is None:
            continue

        if hasattr(module, "FORCE_CLOUD_MODE"):
            monkeypatch.setattr(module, "FORCE_CLOUD_MODE", False, raising=False)
        if hasattr(module, "TURSO_DB_URL"):
            monkeypatch.setattr(module, "TURSO_DB_URL", None, raising=False)
        if hasattr(module, "TURSO_AUTH_TOKEN"):
            monkeypatch.setattr(module, "TURSO_AUTH_TOKEN", None, raising=False)
        if hasattr(module, "TURSO_DB_HOSTNAME"):
            monkeypatch.setattr(module, "TURSO_DB_HOSTNAME", None, raising=False)
        if hasattr(module, "TURSO_TEST_DB_URL"):
            monkeypatch.setattr(module, "TURSO_TEST_DB_URL", None, raising=False)
        if hasattr(module, "TURSO_TEST_AUTH_TOKEN"):
            monkeypatch.setattr(module, "TURSO_TEST_AUTH_TOKEN", None, raising=False)
        if hasattr(module, "TURSO_TEST_DB_HOSTNAME"):
            monkeypatch.setattr(module, "TURSO_TEST_DB_HOSTNAME", None, raising=False)
        if hasattr(module, "TURSO_HUB_DB_URL"):
            monkeypatch.setattr(module, "TURSO_HUB_DB_URL", None, raising=False)
        if hasattr(module, "TURSO_HUB_AUTH_TOKEN"):
            monkeypatch.setattr(module, "TURSO_HUB_AUTH_TOKEN", None, raising=False)

    yield
