"""tests/unit/database/test_session_lock_timeout.py: DBSession 读锁超时降级验证。

验证：
- 锁空闲时正常获取并释放
- 锁被其他线程长时间持有时，读操作在 timeout 后降级执行而非死等
- 写操作（execute）始终强制持锁，不降级
"""
from __future__ import annotations

import sqlite3
import threading
import time
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


class TestDBSessionLockTimeout:
    """DBSession 读锁超时降级行为。"""

    def test_fetchall_acquires_and_releases_lock(self, in_memory_db):
        """锁空闲时，fetchall 正常获取锁并在完成后释放。"""
        lock = threading.RLock()
        session = DBSession(in_memory_db, lock=lock, lock_timeout=1.0)

        rows = session.fetchall("SELECT * FROM test_t")
        assert len(rows) == 1

        # 锁应该已被释放，可以再次获取
        assert lock.acquire(timeout=0.1)
        lock.release()

    def test_fetchone_acquires_and_releases_lock(self, in_memory_db):
        """锁空闲时，fetchone 正常获取锁并在完成后释放。"""
        lock = threading.RLock()
        session = DBSession(in_memory_db, lock=lock, lock_timeout=1.0)

        row = session.fetchone("SELECT * FROM test_t WHERE id = 1")
        assert row is not None

        assert lock.acquire(timeout=0.1)
        lock.release()

    def test_fetchall_degrades_when_lock_held(self, in_memory_db):
        """锁被其他线程长时间持有时，fetchall 超时后降级执行，不会死等。"""
        lock = threading.RLock()
        session = DBSession(in_memory_db, lock=lock, lock_timeout=0.2)

        # 在另一个线程中持有锁
        lock_held = threading.Event()
        release_signal = threading.Event()

        def hold_lock():
            lock.acquire()
            lock_held.set()
            release_signal.wait(timeout=5.0)
            lock.release()

        holder = threading.Thread(target=hold_lock, daemon=True)
        holder.start()
        lock_held.wait(timeout=2.0)

        # fetchall 应在 ~0.2s 后降级执行，不会死等
        start = time.time()
        rows = session.fetchall("SELECT * FROM test_t")
        elapsed = time.time() - start

        # 验证：降级执行成功返回数据
        assert len(rows) == 1
        # 验证：超时时间在合理范围内（0.2 ± 0.3 秒容差）
        assert elapsed < 0.5, f"降级耗时过长: {elapsed:.2f}s"

        release_signal.set()
        holder.join(timeout=2.0)

    def test_fetchone_degrades_when_lock_held(self, in_memory_db):
        """锁被其他线程长时间持有时，fetchone 超时后降级执行。"""
        lock = threading.RLock()
        session = DBSession(in_memory_db, lock=lock, lock_timeout=0.2)

        lock_held = threading.Event()
        release_signal = threading.Event()

        def hold_lock():
            lock.acquire()
            lock_held.set()
            release_signal.wait(timeout=5.0)
            lock.release()

        holder = threading.Thread(target=hold_lock, daemon=True)
        holder.start()
        lock_held.wait(timeout=2.0)

        start = time.time()
        row = session.fetchone("SELECT * FROM test_t WHERE id = 1")
        elapsed = time.time() - start

        assert row is not None
        assert elapsed < 0.5, f"降级耗时过长: {elapsed:.2f}s"

        release_signal.set()
        holder.join(timeout=2.0)

    def test_no_lock_still_works(self, in_memory_db):
        """lock=None 时，fetchall/fetchone 正常工作（无锁路径）。"""
        session = DBSession(in_memory_db, lock=None)

        rows = session.fetchall("SELECT * FROM test_t")
        assert len(rows) == 1

        row = session.fetchone("SELECT * FROM test_t WHERE id = 1")
        assert row is not None

    def test_write_operations_still_require_lock(self, in_memory_db):
        """execute 写操作在有锁时始终使用 with self.lock，不降级。"""
        lock = threading.RLock()
        session = DBSession(in_memory_db, lock=lock, lock_timeout=0.2)

        # 正常写入
        session.execute("INSERT INTO test_t VALUES (2, 'world')")
        row = session.fetchone("SELECT * FROM test_t WHERE id = 2")
        assert row is not None

    def test_custom_lock_timeout(self, in_memory_db):
        """可自定义锁超时时间。"""
        lock = threading.RLock()
        session = DBSession(in_memory_db, lock=lock, lock_timeout=0.05)

        lock_held = threading.Event()
        release_signal = threading.Event()

        def hold_lock():
            lock.acquire()
            lock_held.set()
            release_signal.wait(timeout=5.0)
            lock.release()

        holder = threading.Thread(target=hold_lock, daemon=True)
        holder.start()
        lock_held.wait(timeout=2.0)

        start = time.time()
        rows = session.fetchall("SELECT * FROM test_t")
        elapsed = time.time() - start

        # 0.05s timeout 应更快降级
        assert len(rows) == 1
        assert elapsed < 0.3, f"短超时降级耗时过长: {elapsed:.2f}s"

        release_signal.set()
        holder.join(timeout=2.0)
"""tests/unit/database/test_session_lock_timeout.py"""
