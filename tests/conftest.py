import os
import sys

import pytest


def _clear_all_resources():
    import database.connection as db_connection
    import database.execution_engine as db_engine
    import database.sync_coordinator as sync_coord
    import web.backend.deps as web_deps

    with db_connection._main_write_conn_lock:
        if db_connection._main_write_conn_singleton is not None:
            try:
                db_connection._main_write_conn_singleton.close()
            except Exception:
                pass
            db_connection._main_write_conn_singleton = None
            db_connection._main_write_conn_singleton_path = None
    with db_connection._hub_write_conn_lock:
        if db_connection._hub_write_conn_singleton is not None:
            try:
                db_connection._hub_write_conn_singleton.close()
            except Exception:
                pass
            db_connection._hub_write_conn_singleton = None

    try:
        db_engine.cleanup_concurrent_system()
    except Exception:
        pass

    try:
        with sync_coord._registry_lock:
            for coord in list(sync_coord._coordinators.values()):
                try:
                    coord.shutdown()
                except Exception:
                    pass
            sync_coord._coordinators.clear()
    except Exception:
        pass

    try:
        web_deps.cleanup_deps()
    except Exception:
        pass

    try:
        from database.sync_debouncer import reset_sync_debouncer
        reset_sync_debouncer()
    except Exception:
        pass



@pytest.fixture(autouse=True)
def isolate_cloud_configuration(monkeypatch):
    """让测试统一使用本地模式，避免仓库 .env 里的云端配置污染用例。"""
    import config
    try:
        config.switch_user("test_user")
    except Exception:
        pass

    _clear_all_resources()

    try:
        import database.sync_debouncer as sd
        mock_debouncer = sd.SyncDebouncer()
        monkeypatch.setattr(mock_debouncer, "trigger", lambda fn: None)
        monkeypatch.setattr(sd, "get_sync_debouncer", lambda: mock_debouncer)
    except Exception:
        pass

    monkeypatch.setenv("FORCE_CLOUD_MODE", "False")

    monkeypatch.delenv("TURSO_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TURSO_DB_HOSTNAME", raising=False)
    monkeypatch.delenv("TURSO_TEST_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_TEST_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TURSO_TEST_DB_HOSTNAME", raising=False)
    monkeypatch.delenv("TURSO_HUB_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_HUB_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TURSO_CACHE_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_CACHE_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CACHE_TIMEOUT_S", raising=False)
    monkeypatch.delenv("GLOBAL_CACHE_ENABLED", raising=False)

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

    _clear_all_resources()
    try:
        config.switch_user("test_user")
    except Exception:
        pass


@pytest.fixture
def cloud_integ_env(monkeypatch):
    """
    集成测试专用 Fixture: 自动从 .env 加载测试凭据并注入环境。
    """
    from dotenv import load_dotenv
    load_dotenv()

    test_url = os.getenv("TURSO_TEST_DB_URL")
    test_token = os.getenv("TURSO_TEST_AUTH_TOKEN")
    hub_url = os.getenv("TURSO_TEST_HUB_DB_URL")
    hub_token = os.getenv("TURSO_TEST_HUB_AUTH_TOKEN")

    if not test_url or not test_token:
        pytest.skip("未配置 TURSO_TEST_DB_URL/TOKEN，跳过集成测试")

    monkeypatch.setenv("FORCE_CLOUD_MODE", "True")
    monkeypatch.setenv("TURSO_DB_URL", test_url)
    monkeypatch.setenv("TURSO_AUTH_TOKEN", test_token)
    if hub_url:
        monkeypatch.setenv("TURSO_HUB_DB_URL", hub_url)
    if hub_token:
        monkeypatch.setenv("TURSO_HUB_AUTH_TOKEN", hub_token)

    for module_name in ("config", "database.connection", "database.schema", "database.momo_words", "database.hub_users", "database.utils", "main"):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        if hasattr(module, "FORCE_CLOUD_MODE"):
            monkeypatch.setattr(module, "FORCE_CLOUD_MODE", True, raising=False)
        if hasattr(module, "TURSO_DB_URL"):
            monkeypatch.setattr(module, "TURSO_DB_URL", test_url, raising=False)
        if hasattr(module, "TURSO_AUTH_TOKEN"):
            monkeypatch.setattr(module, "TURSO_AUTH_TOKEN", test_token, raising=False)
        if hub_url and hasattr(module, "TURSO_HUB_DB_URL"):
            monkeypatch.setattr(module, "TURSO_HUB_DB_URL", hub_url, raising=False)
        if hub_token and hasattr(module, "TURSO_HUB_AUTH_TOKEN"):
            monkeypatch.setattr(module, "TURSO_HUB_AUTH_TOKEN", hub_token, raising=False)

    _clear_all_resources()

    yield {
        "user_url": test_url,
        "hub_url": hub_url
    }

    _clear_all_resources()

