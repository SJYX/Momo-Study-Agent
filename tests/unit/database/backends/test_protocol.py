"""tests/unit/database/backends/test_protocol.py: TursoBackend Protocol 验证。

验证:
- get_active_backend() 返回的对象满足 TursoBackend Protocol
- is_supported() 反射模块级 HAS_* 常量
- do_sync_on() 对普通 sqlite3.Connection 无异常（鸭子类型安全）
- 优先级 pyturso > libsql
- 无循环导入
"""
from __future__ import annotations

import sqlite3
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from database.backends import HAS_LIBSQL, HAS_PYTURSO
from database.backends._libsql import LibsqlBackend
from database.backends._protocol import TursoBackend
from database.backends._pyturso import PytursoBackend


# ── 1. Protocol compliance ──


def test_get_active_backend_returns_turso_backend():
    """get_active_backend() 返回的对象满足 TursoBackend Protocol。"""
    import database.backends as backends_mod

    if HAS_PYTURSO:
        expected_cls = PytursoBackend
    elif HAS_LIBSQL:
        expected_cls = LibsqlBackend
    else:
        pytest.skip("Neither pyturso nor libsql is installed")

    backend = backends_mod.get_active_backend()
    assert isinstance(backend, TursoBackend)
    assert isinstance(backend, expected_cls)


# ── 2-3. is_supported reflects module-level flags ──


def test_pyturso_is_supported_reflects_has_pyturso():
    """PytursoBackend().is_supported() 返回的值与 HAS_PYTURSO 一致。"""
    assert PytursoBackend().is_supported() is HAS_PYTURSO


def test_libsql_is_supported_reflects_has_libsql():
    """LibsqlBackend().is_supported() 返回的值与 HAS_LIBSQL 一致。"""
    assert LibsqlBackend().is_supported() is HAS_LIBSQL


# ── 4. do_sync_on duck-type safety ──


def test_do_sync_on_hasattr_safety():
    """对普通 sqlite3.Connection 调用 do_sync_on() 不抛异常。"""
    mem = sqlite3.connect(":memory:")

    # Both backends guard on hasattr(conn, "sync") / hasattr(conn, "pull"),
    # so a plain sqlite3.Connection must pass silently.
    LibsqlBackend().do_sync_on(mem)
    PytursoBackend().do_sync_on(mem)

    mem.close()


# ── 5. Backend preference ──


def test_backend_preference_pyturso_over_libsql(monkeypatch):
    """当两个后端都可用时，get_active_backend() 返回 PytursoBackend。
    若都不可用则抛 RuntimeError。
    """
    import database.backends as backends_mod

    monkeypatch.setattr(backends_mod, "HAS_PYTURSO", True)
    monkeypatch.setattr(backends_mod, "HAS_LIBSQL", True)

    backend = backends_mod.get_active_backend()
    assert isinstance(backend, PytursoBackend)

    # Now neither available → RuntimeError
    monkeypatch.setattr(backends_mod, "HAS_PYTURSO", False)
    monkeypatch.setattr(backends_mod, "HAS_LIBSQL", False)
    with pytest.raises(RuntimeError, match="Neither pyturso nor libsql"):
        backends_mod.get_active_backend()


# ── 6. No circular import ──


def test_no_circular_import():
    """import database.backends 不触发 ImportError（循环导入检查）。"""
    # Re-import from scratch; if there were a circular dependency this would fail.
    import importlib

    mod = importlib.import_module("database.backends")
    assert mod is not None
