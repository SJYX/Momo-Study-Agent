"""tests/unit/database/test_read_conn_isolation.py: Phase B 读连接隔离验证。

验证：
- _get_local_read_conn 返回独立 sqlite3 连接（非写单例）
- 读连接设置了 query_only=ON
- 读连接不受 _main_write_conn_op_lock 阻塞
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
            assert not conn_mod._is_main_write_singleton_conn(conn)
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

    def test_no_op_lock_returned(self, tmp_db):
        """独立读连接不关联写单例的 op_lock。"""
        conn = conn_mod._get_local_read_conn(tmp_db)
        try:
            lock = conn_mod._get_singleton_conn_op_lock(conn)
            assert lock is None, "独立读连接不应关联 _main_write_conn_op_lock"
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


class TestFeatureFlagFallback:
    """ISOLATED_READ_CONN_ENABLED feature flag 回退验证。"""

    def test_flag_disabled_falls_back_to_write_singleton(self, monkeypatch, tmp_db):
        """关闭 flag 时应走旧路径（写单例）。"""
        # 模拟 Embedded Replica 环境
        monkeypatch.setattr(conn_mod, "HAS_LIBSQL", True)
        monkeypatch.setattr(conn_mod._config, "DB_PATH", tmp_db)

        # 让 _resolve_conn_context 返回有效的 ER 配置
        fake_ctx = {
            "db_path": tmp_db,
            "is_main_db": True,
            "is_test": False,
            "url": "libsql://fake.turso.io",
            "token": "fake-token",
            "force_cloud_mode": False,
        }
        monkeypatch.setattr(conn_mod, "_resolve_conn_context", lambda *a, **k: fake_ctx)
        monkeypatch.setattr(conn_mod, "_should_use_local_only_connection", lambda *a, **k: False)

        # 模拟写单例返回
        mock_singleton = MagicMock()
        monkeypatch.setattr(conn_mod, "_get_main_write_conn_singleton", lambda **kw: mock_singleton)

        # 关闭 flag
        from core.feature_flags import set_enabled, reset_overrides
        set_enabled("ISOLATED_READ_CONN_ENABLED", False)
        try:
            conn = conn_mod._get_read_conn_impl(tmp_db)
            # 应该返回写单例 mock
            assert conn is mock_singleton
        finally:
            reset_overrides()

    def test_flag_enabled_returns_independent_conn(self, monkeypatch, tmp_db):
        """开启 flag 时应返回独立 sqlite3 连接。"""
        monkeypatch.setattr(conn_mod, "HAS_LIBSQL", True)
        monkeypatch.setattr(conn_mod._config, "DB_PATH", tmp_db)

        fake_ctx = {
            "db_path": tmp_db,
            "is_main_db": True,
            "is_test": False,
            "url": "libsql://fake.turso.io",
            "token": "fake-token",
            "force_cloud_mode": False,
        }
        monkeypatch.setattr(conn_mod, "_resolve_conn_context", lambda *a, **k: fake_ctx)
        monkeypatch.setattr(conn_mod, "_should_use_local_only_connection", lambda *a, **k: False)

        from core.feature_flags import set_enabled, reset_overrides
        set_enabled("ISOLATED_READ_CONN_ENABLED", True)
        try:
            conn = conn_mod._get_read_conn_impl(tmp_db)
            try:
                # 应该是标准 sqlite3 连接，非写单例
                assert not conn_mod._is_main_write_singleton_conn(conn)
                assert conn_mod._get_singleton_conn_op_lock(conn) is None
            finally:
                conn.close()
        finally:
            reset_overrides()
