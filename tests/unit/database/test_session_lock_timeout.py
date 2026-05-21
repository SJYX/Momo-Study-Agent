"""tests/unit/database/test_session_lock_timeout.py: DBSession backend lock integration.

验证：
- backend 传入时，op_lock_for 被正确调用
- backend=None 时，操作直接执行（无锁）
- read/write 操作均产生正确结果
"""
from __future__ import annotations

import sqlite3
import contextlib
from unittest.mock import MagicMock

import pytest

from database.session import DBSession


@pytest.fixture
def in_memory_db():
    """创建一个内存中的 SQLite 数据库供测试使用。"""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE test_t (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO test_t VALUES (1, 'hello')")
    conn.commit()
    return conn


@pytest.fixture
def mock_backend():
    """创建一个 mock backend，其 op_lock_for 返回 nullcontext。"""
    backend = MagicMock()
    backend.op_lock_for.return_value = contextlib.nullcontext()
    return backend


class TestDBSessionWithBackend:
    """DBSession 使用 backend 并发控制的行为。"""

    def test_fetchall_with_backend(self, in_memory_db, mock_backend):
        """有 backend 时 fetchall 正常工作。"""
        session = DBSession(in_memory_db, backend=mock_backend)

        rows = session.fetchall("SELECT * FROM test_t")
        assert len(rows) == 1

        # 验证 op_lock_for 被调用
        mock_backend.op_lock_for.assert_called()

    def test_fetchone_with_backend(self, in_memory_db, mock_backend):
        """有 backend 时 fetchone 正常工作。"""
        session = DBSession(in_memory_db, backend=mock_backend)

        row = session.fetchone("SELECT * FROM test_t WHERE id = 1")
        assert row is not None
        mock_backend.op_lock_for.assert_called()

    def test_execute_with_backend(self, in_memory_db, mock_backend):
        """有 backend 时 execute 正常工作。"""
        session = DBSession(in_memory_db, backend=mock_backend)

        session.execute("INSERT INTO test_t VALUES (2, 'world')")
        row = session.fetchone("SELECT * FROM test_t WHERE id = 2")
        assert row is not None
        mock_backend.op_lock_for.assert_called()

    def test_executemany_with_backend(self, in_memory_db, mock_backend):
        """有 backend 时 executemany 正常工作。"""
        session = DBSession(in_memory_db, backend=mock_backend)

        session.executemany("INSERT INTO test_t VALUES (?, ?)", [(2, "world"), (3, "foo")])
        rows = session.fetchall("SELECT * FROM test_t WHERE id > 1")
        assert len(rows) == 2


class TestDBSessionWithoutBackend:
    """DBSession 在没有 backend 时的行为（无锁路径）。"""

    def test_fetchall_without_backend(self, in_memory_db):
        """backend=None 时 fetchall 正常工作。"""
        session = DBSession(in_memory_db, backend=None)

        rows = session.fetchall("SELECT * FROM test_t")
        assert len(rows) == 1

    def test_fetchone_without_backend(self, in_memory_db):
        """backend=None 时 fetchone 正常工作。"""
        session = DBSession(in_memory_db, backend=None)

        row = session.fetchone("SELECT * FROM test_t WHERE id = 1")
        assert row is not None

    def test_execute_without_backend(self, in_memory_db):
        """backend=None 时 execute 正常工作。"""
        session = DBSession(in_memory_db, backend=None)

        session.execute("INSERT INTO test_t VALUES (2, 'world')")
        row = session.fetchone("SELECT * FROM test_t WHERE id = 2")
        assert row is not None

    def test_default_no_backend(self, in_memory_db):
        """不传 backend 参数时等同于 backend=None。"""
        session = DBSession(in_memory_db)

        rows = session.fetchall("SELECT * FROM test_t")
        assert len(rows) == 1

        session.execute("INSERT INTO test_t VALUES (2, 'world')")
        row = session.fetchone("SELECT * FROM test_t WHERE id = 2")
        assert row is not None


class TestDBSessionBackendInteraction:
    """验证 backend.op_lock_for 的调用细节。"""

    def test_op_lock_for_called_with_conn(self, in_memory_db, mock_backend):
        """op_lock_for 应传入当前连接。"""
        session = DBSession(in_memory_db, backend=mock_backend)

        session.fetchall("SELECT * FROM test_t")
        mock_backend.op_lock_for.assert_called_with(in_memory_db)

    def test_op_lock_for_called_on_each_operation(self, in_memory_db, mock_backend):
        """每次操作都应调用 op_lock_for。"""
        session = DBSession(in_memory_db, backend=mock_backend)
        call_count_before = mock_backend.op_lock_for.call_count

        session.fetchall("SELECT * FROM test_t")
        session.fetchone("SELECT * FROM test_t WHERE id = 1")
        session.execute("INSERT INTO test_t VALUES (2, 'world')")

        assert mock_backend.op_lock_for.call_count == call_count_before + 3

    def test_backend_that_returns_failing_context(self, in_memory_db):
        """如果 backend.op_lock_for 返回的 contextmanager 抛异常，操作应失败。"""
        backend = MagicMock()
        def _fail_ctx(conn):
            raise RuntimeError("lock acquisition failed")
        backend.op_lock_for.side_effect = _fail_ctx

        session = DBSession(in_memory_db, backend=backend)
        with pytest.raises(RuntimeError, match="lock acquisition failed"):
            session.fetchall("SELECT * FROM test_t")
