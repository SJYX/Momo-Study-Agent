"""tests/unit/database/test_word_state.py: WordState 推导规则与 SQL 片段。"""
from __future__ import annotations

import pytest

from database.word_state import WordState, derive_state, state_to_where_clause


class TestDeriveState:
    """覆盖 (processed, sync_status) 全部 12 种组合，确保推导无歧义。"""

    @pytest.mark.parametrize(
        "processed,sync_status,expected",
        [
            # processed=False
            (False, None, WordState.NOT_STARTED),
            (False, 0, WordState.LOCAL_READY),  # 有笔记但漏标 processed → 历史漏标，归 LOCAL_READY
            (False, 1, WordState.SYNCED),        # 远端已同步但漏标 processed → 仍是 SYNCED
            (False, 2, WordState.CONFLICT),
            (False, 3, WordState.LOCAL_READY),
            (False, 4, WordState.LOCAL_READY),
            (False, 5, WordState.FAILED),
            # processed=True
            (True, None, WordState.LOCAL_READY),  # 标了 processed 但没笔记 → 推荐归 LOCAL_READY
            (True, 0, WordState.LOCAL_READY),
            (True, 1, WordState.SYNCED),
            (True, 2, WordState.CONFLICT),       # 异常态压过 SYNCED
            (True, 3, WordState.LOCAL_READY),
            (True, 4, WordState.LOCAL_READY),
            (True, 5, WordState.FAILED),
        ],
    )
    def test_all_combinations(self, processed, sync_status, expected):
        assert derive_state(processed, sync_status) == expected

    def test_exception_states_override(self):
        """CONFLICT 和 FAILED 不应被 processed=True/sync_status=1 等正常态覆盖。"""
        assert derive_state(True, 2) == WordState.CONFLICT
        assert derive_state(True, 5) == WordState.FAILED
        # 即使有 processed 标记，conflict 仍优先
        assert derive_state(False, 2) == WordState.CONFLICT

    def test_priority_order(self):
        """优先级文档化：CONFLICT > FAILED > SYNCED > LOCAL_READY > NOT_STARTED。"""
        # 同一个状态不可能两个 sync_status，所以这里验证的是"异常态的存在不影响正常态"
        # 仅有 sync_status=1 时不算 CONFLICT
        assert derive_state(True, 1) == WordState.SYNCED
        # 仅 processed 时不算 SYNCED
        assert derive_state(True, None) == WordState.LOCAL_READY


class TestStateToWhereClause:
    """SQL 片段语义自检：每个状态的 WHERE 与 derive_state 保持等价。"""

    def test_conflict(self):
        sql, params = state_to_where_clause(WordState.CONFLICT)
        assert sql == "n.sync_status = ?"
        assert params == (2,)

    def test_failed(self):
        sql, params = state_to_where_clause(WordState.FAILED)
        assert sql == "n.sync_status = ?"
        assert params == (5,)

    def test_synced(self):
        sql, params = state_to_where_clause(WordState.SYNCED)
        assert sql == "n.sync_status = ?"
        assert params == (1,)

    def test_local_ready(self):
        sql, params = state_to_where_clause(WordState.LOCAL_READY)
        # 关键约束：包含 processed 或 in-progress sync_status，排除终态
        assert "p.voc_id IS NOT NULL" in sql
        assert "n.sync_status IN (0, 3, 4)" in sql
        assert "NOT IN (1, 2, 5)" in sql
        assert params == ()

    def test_not_started(self):
        sql, params = state_to_where_clause(WordState.NOT_STARTED)
        assert sql == "p.voc_id IS NULL AND n.sync_status IS NULL"
        assert params == ()

    def test_all_states_have_clause(self):
        """枚举每个值都能产出一条 SQL，不抛 KeyError。"""
        for state in WordState:
            sql, params = state_to_where_clause(state)
            assert isinstance(sql, str) and sql
            assert isinstance(params, tuple)


class TestWordStateEnum:
    def test_str_serializable(self):
        """继承 str 便于 JSON 直出 / Web 端展示。"""
        assert WordState.NOT_STARTED.value == "not_started"
        assert WordState.LOCAL_READY.value == "local_ready"
        assert WordState.SYNCED.value == "synced"
        assert WordState.CONFLICT.value == "conflict"
        assert WordState.FAILED.value == "failed"

    def test_str_eq(self):
        """str 子类支持与字符串直接比较。"""
        assert WordState.SYNCED == "synced"
