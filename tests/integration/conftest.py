"""tests/integration/conftest.py: 集成测试专用 fixture。

边界：
- 这里的 fixture 只在 tests/integration/ 下生效。
- 主 conftest（tests/conftest.py）的 cloud isolation 仍然 autouse 生效。
- 提供 in-memory SQLite fixture 给后续新写的纯 SQLite 集成测试使用，**不强制**改造既有 file-DB 测试。
"""
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def memory_sqlite_db():
    """单连接 in-memory SQLite。每个测试独立，跑完即销毁。

    适用：不需要跨连接共享数据的纯 SQL 单元/集成测试。

    不适用：
    - 需要 libsql Embedded Replica 的测试（用文件 DB + cloud_integ_env fixture）
    - 需要多连接共享同一 DB 的并发场景（用 shared_memory_sqlite_uri）
    - 测试触发 connection.py 内部建连逻辑的（用 tmp_path 文件 DB，让代码走真实路径）
    """
    conn = sqlite3.connect(":memory:")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def shared_memory_sqlite_uri():
    """共享内存 DB 的 URI 字符串（每个测试唯一名）。

    用法：
        def test_x(shared_memory_sqlite_uri):
            c1 = sqlite3.connect(shared_memory_sqlite_uri, uri=True)
            c2 = sqlite3.connect(shared_memory_sqlite_uri, uri=True)
            # c1 和 c2 看到同一个内存 DB

    适用：需要多连接读写同一内存 DB 的并发/隔离测试。
    """
    import uuid
    name = f"testdb_{uuid.uuid4().hex[:8]}"
    return f"file:{name}?mode=memory&cache=shared"
