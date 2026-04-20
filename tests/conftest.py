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

    for module_name in ("config", "database.connection", "database.schema", "database.momo_words", "database.hub_users", "main"):
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


@pytest.fixture
def cloud_integ_env(monkeypatch):
    """
    集成测试专用 Fixture: 自动从 .env 加载测试凭据并注入环境。
    """
    # 模拟从 .env 加载测试专用变量
    from dotenv import load_dotenv
    load_dotenv()

    test_url = os.getenv("TURSO_TEST_DB_URL")
    test_token = os.getenv("TURSO_TEST_AUTH_TOKEN")
    hub_url = os.getenv("TURSO_TEST_HUB_DB_URL")
    hub_token = os.getenv("TURSO_TEST_HUB_AUTH_TOKEN")

    if not test_url or not test_token:
        pytest.skip("未配置 TURSO_TEST_DB_URL/TOKEN，跳过集成测试")

    # 注入到生产变量名中供 database 模块使用
    monkeypatch.setenv("FORCE_CLOUD_MODE", "True")
    monkeypatch.setenv("TURSO_DB_URL", test_url)
    monkeypatch.setenv("TURSO_AUTH_TOKEN", test_token)
    if hub_url:
        monkeypatch.setenv("TURSO_HUB_DB_URL", hub_url)
    if hub_token:
        monkeypatch.setenv("TURSO_HUB_AUTH_TOKEN", hub_token)

    # 同时修改 sys.modules 中的已加载模块变量（如果存在）
    import database.connection as db_connection
    monkeypatch.setattr(db_connection, "TURSO_DB_URL", test_url)
    monkeypatch.setattr(db_connection, "TURSO_AUTH_TOKEN", test_token)
    if hub_url:
        monkeypatch.setattr(db_connection, "TURSO_HUB_DB_URL", hub_url)
    if hub_token:
        monkeypatch.setattr(db_connection, "TURSO_HUB_AUTH_TOKEN", hub_token)

    yield {
        "user_url": test_url,
        "hub_url": hub_url
    }
