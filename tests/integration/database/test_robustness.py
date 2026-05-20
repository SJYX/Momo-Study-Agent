import pytest
import json
import os
from core.mimo_client import MimoClient
from database.connection import _get_cloud_conn
import sqlite3

class FakeResponse:
    def __init__(self, json_data):
        self.json_data = json_data
        self.status_code = 200
    def json(self):
        return self.json_data

def test_mimo_client_robustness_mixed_types(monkeypatch):
    """验证 MimoClient 能够处理 AI 返回的非对象 JSON 条目（防止 'str' object does not support item assignment）"""
    client = MimoClient(api_key="fake-key")
    
    # 模拟 AI 返回混合类型的列表
    fake_payload = {
        "choices": [{
            "message": {
                "content": json.dumps([
                    {"spelling": "apple", "memory_aid": "A"},
                    "THIS IS A RAW STRING THAT SHOULD BE SKIPPED",
                    {"spelling": "banana", "memory_aid": "B"}
                ])
            }
        }],
        "usage": {"total_tokens": 100}
    }
    
    monkeypatch.setattr(client.session, "post", lambda *args, **kwargs: FakeResponse(fake_payload))
    
    results, metadata = client.generate_mnemonics(["apple", "banana"])
    
    # 验证是否成功跳过了字符串，且没有崩溃
    assert len(results) == 2
    assert results[0]["spelling"] == "apple"
    assert results[1]["spelling"] == "banana"
    assert "raw_full_text" in results[0]

def test_mimo_client_robustness_object_format(monkeypatch):
    """验证 MimoClient 能够处理带 'results' 键的 JSON 对象格式 (回退后的标准格式)"""
    client = MimoClient(api_key="fake-key")
    
    fake_payload = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "results": [
                        {"spelling": "cherry", "memory_aid": "C"},
                        {"spelling": "date", "memory_aid": "D"}
                    ]
                })
            }
        }],
        "usage": {"total_tokens": 100}
    }
    
    monkeypatch.setattr(client.session, "post", lambda *args, **kwargs: FakeResponse(fake_payload))
    
    results, metadata = client.generate_mnemonics(["cherry", "date"])
    
    assert len(results) == 2
    assert results[0]["spelling"] == "cherry"
    assert results[1]["spelling"] == "date"

def test_db_manager_get_cloud_conn_self_healing_regression(tmp_path, monkeypatch):
    """验证 _get_cloud_conn 的自愈功能：首次 sync 失败后重连成功。

    注意：_connect_embedded_replica 会在 libsql.connect 之前删除无元数据的 .db 文件
    （metadata 缺失 → .db 无法被 libsql 识别为有效副本），因此自愈路径中
    _backup_broken_database_file 无法备份已删除的文件。测试只验证重连次数和连接成功。
    """
    import database.connection as db_connection
    db_path = tmp_path / "replica_test.db"
    db_path.write_text("corrupt-content", encoding="utf-8")
    # 创建配套的 .db-info 元数据，避免 _connect_embedded_replica 在连接前删除 .db
    (tmp_path / "replica_test.db-info").write_text("fake-metadata", encoding="utf-8")

    call_state = {"count": 0}

    class FakeLibsqlConn:
        def __init__(self, fail=False):
            self.fail = fail
        def sync(self):
            if self.fail:
                raise RuntimeError("database disk image is malformed")
        def close(self): pass

    def fake_connect(path, sync_url=None, auth_token=None, timeout=None, **kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            return FakeLibsqlConn(fail=True)
        return FakeLibsqlConn(fail=False)

    import libsql  # noqa: F401 — ensure libsql is importable so backends work

    # Force the libsql backend (this test validates libsql-specific self-healing).
    # Reset the lazy backend singleton so it re-evaluates after we patch HAS_PYTURSO.
    import database.backends as backends_mod
    monkeypatch.setattr(backends_mod, "HAS_PYTURSO", False)
    monkeypatch.setattr(db_connection, "_backend", None)  # reset lazy singleton

    # Patch libsql.connect at the source (_libsql backend).
    from database.backends import _libsql as backend_libsql
    monkeypatch.setattr(backend_libsql.libsql, "connect", fake_connect)

    conn = db_connection._get_cloud_conn("libsql://test", "token", db_path=str(db_path))
    assert conn is not None
    assert call_state["count"] == 2 # 第一次失败后应重连

if __name__ == "__main__":
    pytest.main([__file__])
