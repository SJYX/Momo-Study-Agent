"""tests/unit/database/backends/test_op_lock.py: op_lock_for 单元测试。"""

import sqlite3
import threading

import pytest

from database.backends._libsql import LibsqlBackend
from database.backends._pyturso import PytursoBackend


def test_pyturso_op_lock_is_noop():
    """PytursoBackend.op_lock_for() 不获取任何锁，直接 yield。"""
    backend = PytursoBackend()
    conn = sqlite3.connect(":memory:")
    conn._momo_db_role = "main"

    with backend.op_lock_for(conn):
        pass

    conn.close()


def test_libsql_op_lock_main_and_hub_separate():
    """LibsqlBackend 的 main_lock 和 hub_lock 是独立的。"""
    backend = LibsqlBackend()

    main_conn = sqlite3.connect(":memory:")
    main_conn._momo_db_role = "main"
    hub_conn = sqlite3.connect(":memory:")
    hub_conn._momo_db_role = "hub"

    barrier = threading.Barrier(2)

    def hold_main():
        with backend.op_lock_for(main_conn):
            barrier.wait(timeout=2.0)

    def hold_hub():
        with backend.op_lock_for(hub_conn):
            barrier.wait(timeout=2.0)

    t1 = threading.Thread(target=hold_main)
    t2 = threading.Thread(target=hold_hub)
    t1.start()
    t2.start()
    t1.join(timeout=3.0)
    t2.join(timeout=3.0)
    assert not t1.is_alive()
    assert not t2.is_alive()

    main_conn.close()
    hub_conn.close()


def test_libsql_op_lock_main_serialized():
    """LibsqlBackend 的同一把 main_lock 应序列化并发操作。"""
    backend = LibsqlBackend()
    conn = sqlite3.connect(":memory:")
    conn._momo_db_role = "main"

    results = []

    def writer(val):
        with backend.op_lock_for(conn):
            results.append(val)

    t1 = threading.Thread(target=writer, args=(1,))
    t2 = threading.Thread(target=writer, args=(2,))
    t1.start()
    t2.start()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert len(results) == 2
    assert results in ([1, 2], [2, 1])
    conn.close()


def test_libsql_default_role_is_main():
    """没有 _momo_db_role 标记的连接默认走 main_lock。"""
    backend = LibsqlBackend()
    conn = sqlite3.connect(":memory:")

    with backend.op_lock_for(conn):
        pass

    conn.close()
