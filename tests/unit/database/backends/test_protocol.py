"""tests/unit/database/backends/test_protocol.py: TursoBackend Protocol 验证。

验证:
- get_active_backend() 返回的对象满足 TursoBackend Protocol
- do_sync_on() 对普通 sqlite3.Connection 无异常（鸭子类型安全）
- 无循环导入
"""
from __future__ import annotations

import sqlite3

from database.backends import HAS_PYTURSO
from database.backends._protocol import TursoBackend
from database.backends._pyturso import PytursoBackend


# ── 1. Protocol compliance ──


def test_get_active_backend_returns_turso_backend():
    """get_active_backend() 返回的对象满足 TursoBackend Protocol。"""
    if not HAS_PYTURSO:
        import pytest
        pytest.skip("pyturso is not installed")

    import database.backends as backends_mod

    backend = backends_mod.get_active_backend()
    assert isinstance(backend, TursoBackend)
    assert isinstance(backend, PytursoBackend)


# ── 2. is_supported reflects module-level flag ──


def test_pyturso_is_supported_reflects_has_pyturso():
    """PytursoBackend().is_supported() 返回的值与 HAS_PYTURSO 一致。"""
    assert PytursoBackend().is_supported() is HAS_PYTURSO


# ── 3. do_sync_on duck-type safety ──


def test_do_sync_on_hasattr_safety():
    """对普通 sqlite3.Connection 调用 do_sync_on() 不抛异常。"""
    mem = sqlite3.connect(":memory:")

    PytursoBackend().do_sync_on(mem)

    mem.close()


# ── 4. No circular import ──


def test_no_circular_import():
    """import database.backends 不触发 ImportError（循环导入检查）。"""
    import importlib

    mod = importlib.import_module("database.backends")
    assert mod is not None
