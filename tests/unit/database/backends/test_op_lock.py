"""tests/unit/database/backends/test_op_lock.py: op_lock_for 单元测试。"""

from types import SimpleNamespace

from database.backends._pyturso import PytursoBackend


def _make_conn(role: str) -> SimpleNamespace:
    """创建模拟连接对象，支持 _momo_db_role 属性。"""
    return SimpleNamespace(_momo_db_role=role)


def test_pyturso_op_lock_is_noop():
    """PytursoBackend.op_lock_for() 不获取任何锁，直接 yield。"""
    backend = PytursoBackend()
    conn = _make_conn("main")

    with backend.op_lock_for(conn):
        pass
