"""tests/unit/database/test_dispatch_paths.py: 双写路径（本地直写 vs 队列）一致性与异常恢复。

通过 monkeypatch database.connection 内部函数，验证：
- 当 _should_use_local_only_connection 返回 True 时走本地同步执行
- 否则走队列入队
- 写入失败异常被 repo 层吞错并返回 False，且不向上抛
"""
from __future__ import annotations

import sqlite3

import pytest

from database import connection as conn_mod
from database._repo_helpers import dispatch_batch_write, dispatch_write
from database.notes_repo import (
    save_ai_word_iteration,
    save_ai_word_note,
    set_note_sync_status,
)
from database.progress_repo import mark_processed, mark_processed_batch


@pytest.fixture
def fake_dispatch(monkeypatch):
    """记录每次写入分发的去向（local-direct vs queue）。"""
    calls = {"local_single": 0, "local_batch": 0, "queue_single": 0, "queue_batch": 0}

    def fake_local_only(db_path, conn):
        # 测试默认走本地直写路径
        return True

    def fake_exec_sync(sql, args, *, db_path=None, conn=None):
        calls["local_single"] += 1

    def fake_batch_sync(sql, args_list, *, db_path=None, conn=None):
        calls["local_batch"] += 1

    def fake_queue(sql, args, op_type="insert_or_replace"):
        calls["queue_single"] += 1
        return True

    def fake_queue_batch(sql, args_list):
        calls["queue_batch"] += 1
        return True

    monkeypatch.setattr(conn_mod, "_should_use_local_only_connection", fake_local_only)
    monkeypatch.setattr(conn_mod, "_execute_write_sql_sync", fake_exec_sync)
    monkeypatch.setattr(conn_mod, "_execute_batch_write_sql_sync", fake_batch_sync)
    monkeypatch.setattr(conn_mod, "_queue_write_operation", fake_queue)
    monkeypatch.setattr(conn_mod, "_queue_batch_write_operation", fake_queue_batch)
    return calls


def test_dispatch_write_uses_local_path_when_local_only(fake_dispatch):
    ok = dispatch_write("INSERT INTO t VALUES (?)", ("x",))
    assert ok is True
    assert fake_dispatch["local_single"] == 1
    assert fake_dispatch["queue_single"] == 0


def test_dispatch_write_falls_back_to_queue(monkeypatch, fake_dispatch):
    """当 _should_use_local_only_connection 返回 False 时走入队路径。"""
    monkeypatch.setattr(conn_mod, "_should_use_local_only_connection", lambda *_a, **_k: False)
    ok = dispatch_write("INSERT INTO t VALUES (?)", ("x",))
    assert ok is True
    assert fake_dispatch["queue_single"] == 1
    assert fake_dispatch["local_single"] == 0


def test_dispatch_batch_write_local_path(fake_dispatch):
    ok = dispatch_batch_write("INSERT INTO t VALUES (?)", [("a",), ("b",)])
    assert ok is True
    assert fake_dispatch["local_batch"] == 1


def test_dispatch_batch_write_queue_path(monkeypatch, fake_dispatch):
    monkeypatch.setattr(conn_mod, "_should_use_local_only_connection", lambda *_a, **_k: False)
    ok = dispatch_batch_write("INSERT INTO t VALUES (?)", [("a",), ("b",)])
    assert ok is True
    assert fake_dispatch["queue_batch"] == 1


def test_save_ai_word_note_swallows_db_error_and_returns_false(monkeypatch):
    """sqlite3 异常不应向上抛，repo 层吞错并返回 False。"""
    def boom(*_a, **_k):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr("database.notes_repo.dispatch_write", boom)
    ok = save_ai_word_note("v1", {"spelling": "x"})
    assert ok is False


def test_save_ai_word_note_swallows_unexpected_exception_and_returns_false(monkeypatch):
    """未分类的异常仍兜底返回 False（且会附 traceback 到日志，但不抛）。"""
    def boom(*_a, **_k):
        raise RuntimeError("libsql segfault simulation")

    monkeypatch.setattr("database.notes_repo.dispatch_write", boom)
    ok = save_ai_word_note("v1", {"spelling": "x"})
    assert ok is False


def test_set_note_sync_status_with_invalid_status_returns_false(monkeypatch):
    """非数值 sync_status 触发 ValueError 也应被吞掉并返回 False。"""
    monkeypatch.setattr("database.notes_repo.dispatch_write", lambda *_a, **_k: True)
    ok = set_note_sync_status("v1", "not-a-number")  # type: ignore[arg-type]
    assert ok is False


def test_save_ai_word_iteration_returns_false_for_empty_voc_id():
    assert save_ai_word_iteration("", {"spelling": "x"}) is False


def test_save_ai_word_iteration_swallows_db_error(monkeypatch):
    monkeypatch.setattr("database.notes_repo.dispatch_write", lambda *_a, **_k: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    assert save_ai_word_iteration("v1", {"spelling": "x"}) is False


def test_mark_processed_swallows_db_error(monkeypatch):
    monkeypatch.setattr("database.progress_repo.dispatch_write", lambda *_a, **_k: (_ for _ in ()).throw(sqlite3.OperationalError("busy")))
    assert mark_processed("v1", "apple") is False


def test_mark_processed_batch_returns_true_for_empty_input():
    assert mark_processed_batch([]) is True


def test_mark_processed_batch_swallows_db_error(monkeypatch):
    monkeypatch.setattr("database.progress_repo.dispatch_batch_write", lambda *_a, **_k: (_ for _ in ()).throw(sqlite3.OperationalError("busy")))
    assert mark_processed_batch([("v1", "apple"), ("v2", "bee")]) is False
