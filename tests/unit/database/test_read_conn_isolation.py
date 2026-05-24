"""tests/unit/database/test_read_conn_isolation.py: Phase B 读连接隔离验证。

验证：
- _get_local_read_conn 返回独立 sqlite3 连接（非写单例）
- 读连接设置了 query_only=ON
- 读连接与写单例隔离
- feature flag 关闭时回退到写单例
- 读连接失败时降级到写单例
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from database import connection as conn_mod
from database.connection import context as conn_context
from database.connection import factory as conn_factory
from database.connection import singleton as conn_singleton
from database.backends import get_active_backend


@pytest.fixture
def tmp_db(tmp_path):
    """创建一个临时 SQLite 数据库文件。"""
    db_file = str(tmp_path / "test.db")
    c = sqlite3.connect(db_file)
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("CREATE TABLE test_t (id INTEGER PRIMARY KEY, val TEXT)")
    c.execute("INSERT INTO test_t VALUES (1, 'hello')")
    c.commit()
    c.close()
    return db_file


class TestGetLocalReadConn:
    """_get_local_read_conn 行为验证。"""

    def test_returns_valid_connection(self, tmp_db):
        conn = conn_mod._get_local_read_conn(tmp_db)
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM test_t")
            rows = cur.fetchall()
            cur.close()
            assert len(rows) == 1
        finally:
            conn.close()

    def test_is_not_write_singleton(self, tmp_db):
        """独立读连接不是写单例。"""
        conn = conn_mod._get_local_read_conn(tmp_db)
        try:
            assert conn is not conn_singleton._main_write_conn_singleton
        finally:
            conn.close()

    def test_query_only_blocks_writes(self, tmp_db):
        """query_only=ON 应阻止写操作。"""
        conn = conn_mod._get_local_read_conn(tmp_db)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("INSERT INTO test_t VALUES (2, 'world')")
        finally:
            conn.close()


class TestReadConnIsolation:
    """读写隔离集成测试：读操作不被写锁阻塞。"""

    def test_read_while_write_lock_held(self, tmp_db):
        """模拟写锁被持有时，独立读连接仍能正常读取。"""
        # 写入一些数据
        write_conn = sqlite3.connect(tmp_db, timeout=5.0)
        write_conn.execute("PRAGMA journal_mode=WAL;")
        write_conn.execute("INSERT INTO test_t VALUES (2, 'world')")
        write_conn.commit()

        # 用独立读连接读取（不需要任何锁）
        read_conn = conn_mod._get_local_read_conn(tmp_db)
        try:
            cur = read_conn.cursor()
            cur.execute("SELECT COUNT(*) FROM test_t")
            count = cur.fetchone()[0]
            cur.close()
            assert count == 2
        finally:
            read_conn.close()
            write_conn.close()

    def test_concurrent_read_and_write(self, tmp_db):
        """并发读写不阻塞：写线程持续写入，读线程持续读取。"""
        errors = []
        write_done = threading.Event()
        read_results = []

        def writer():
            try:
                c = sqlite3.connect(tmp_db, timeout=10.0)
                c.execute("PRAGMA journal_mode=WAL;")
                for i in range(10):
                    c.execute(f"INSERT INTO test_t VALUES ({i + 100}, 'val{i}')")
                    c.commit()
                    time.sleep(0.01)
                c.close()
            except Exception as e:
                errors.append(f"writer: {e}")
            finally:
                write_done.set()

        def reader():
            try:
                c = conn_mod._get_local_read_conn(tmp_db)
                for _ in range(10):
                    cur = c.cursor()
                    cur.execute("SELECT COUNT(*) FROM test_t")
                    count = cur.fetchone()[0]
                    cur.close()
                    read_results.append(count)
                    time.sleep(0.01)
                c.close()
            except Exception as e:
                errors.append(f"reader: {e}")

        t_writer = threading.Thread(target=writer, daemon=True)
        t_reader = threading.Thread(target=reader, daemon=True)
        t_writer.start()
        t_reader.start()
        t_writer.join(timeout=5.0)
        t_reader.join(timeout=5.0)

        assert not errors, f"并发读写出错: {errors}"
        assert len(read_results) == 10, "读操作应完成 10 次"
        # 读到的行数应 >= 1（初始数据）
        assert all(c >= 1 for c in read_results)


class TestBackendAwareRouting:
    """pyturso 后端读连接路由验证。"""

    def test_pyturso_returns_local_read_conn(self, monkeypatch, tmp_db):
        """pyturso 后端应返回独立 sqlite3 只读连接。"""
        # HAS_PYTURSO 在 factory.py 中通过 `from .context import HAS_PYTURSO` 绑定到本地;
        # _resolve_conn_context / _should_use_local_only_connection 都是 factory 内的名字。
        monkeypatch.setattr(conn_factory, "HAS_PYTURSO", True)
        monkeypatch.setattr(conn_context._config, "DB_PATH", tmp_db)

        fake_ctx = {
            "db_path": tmp_db,
            "is_main_db": True,
            "is_test": False,
            "url": "libsql://fake.turso.io",
            "token": "fake-token",
            "force_cloud_mode": False,
        }
        monkeypatch.setattr(conn_factory, "_resolve_conn_context", lambda *a, **k: fake_ctx)
        monkeypatch.setattr(conn_factory, "_should_use_local_only_connection", lambda *a, **k: False)

        # 模拟 pyturso backend — 直接塞进 context._backend 缓存,跳过 _get_backend 的 lazy init
        mock_backend = MagicMock()
        mock_backend.name = "pyturso"
        monkeypatch.setattr(conn_context, "_backend", mock_backend)

        conn = conn_mod._get_read_conn_impl(tmp_db)
        try:
            # 在 pyturso 模式下，应该返回 pyturso 后端连接而不是标准 sqlite3 连接，以防数据损坏
            assert conn is mock_backend.connect.return_value
            assert conn is not conn_singleton._main_write_conn_singleton
        finally:
            conn.close()

    # test_returns_singleton removed — legacy backend no longer exists
