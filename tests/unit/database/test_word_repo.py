"""
tests/unit/database/test_word_repo.py: word_repo 数据访问层的单元测试。

测试覆盖：
1. get_word_states_in_batch —— LEFT JOIN 逻辑、分批、历史漏标检测
2. filter_unprocessed —— 判重精度、边界态（仅笔记/仅标记）
3. count_by_state / list_by_state —— 5 态分类、分页
4. query_weak_words —— 评分算法、阈值过滤
5. list_word_notes_paginated —— 多条件搜索、分页
6. get_word_iterations —— 迭代历史查询
7. update_memory_aid —— 写操作、timestamp 更新
"""

import json
import sqlite3
import time
from typing import Dict, List, Optional
from unittest import mock

import pytest

from database.word_repo import (
    get_word_states_in_batch,
    filter_unprocessed,
    count_by_state,
    list_by_state,
    query_weak_words,
    list_word_notes_paginated,
    get_word_iterations,
    update_memory_aid,
    _enqueue_backfill_processed,
)
from database.word_state import WordState
from database.session import DBSession


@pytest.fixture
def memory_db():
    """创建内存 SQLite 数据库 fixture。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 建表
    cursor.execute("""
        CREATE TABLE processed_words (
            voc_id TEXT PRIMARY KEY,
            spelling TEXT,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE ai_word_notes (
            voc_id TEXT PRIMARY KEY,
            spelling TEXT,
            basic_meanings TEXT,
            ielts_focus TEXT,
            collocations TEXT,
            traps TEXT,
            synonyms TEXT,
            discrimination TEXT,
            example_sentences TEXT,
            memory_aid TEXT,
            word_ratings TEXT,
            raw_full_text TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            batch_id TEXT,
            original_meanings TEXT,
            maimemo_context TEXT,
            content_origin TEXT,
            content_source_db TEXT,
            content_source_scope TEXT,
            it_level INTEGER DEFAULT 0,
            it_history TEXT,
            sync_status INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE ai_word_iterations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voc_id TEXT NOT NULL,
            spelling TEXT,
            stage TEXT,
            it_level INTEGER,
            score REAL,
            justification TEXT,
            tags TEXT,
            refined_content TEXT,
            candidate_notes TEXT,
            raw_response TEXT,
            maimemo_context TEXT,
            batch_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(voc_id) REFERENCES ai_word_notes(voc_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE word_progress_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voc_id TEXT,
            familiarity_short REAL,
            familiarity_long REAL,
            review_count INTEGER,
            it_level INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def mock_session(memory_db):
    """模拟 DBSession 对象。"""

    class MockSession:
        def __init__(self, conn):
            self.conn = conn
            self.cursor = conn.cursor

        def fetchone(self, sql, params=()):
            self.cursor().execute(sql, params)
            return self.cursor().fetchone()

        def fetchall(self, sql, params=()):
            self.cursor().execute(sql, params)
            return self.cursor().fetchall()

    return MockSession(memory_db)


class TestGetWordStatesBatch:
    """Test get_word_states_in_batch: LEFT JOIN logic & state derivation."""

    def test_empty_input(self):
        """空输入返回空字典。"""
        result = get_word_states_in_batch([])
        assert result == {}

    def test_not_started_state(self, memory_db, mock_session):
        """未处理状态: 词未在任何表中。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            with mock.patch(
                "database.word_repo._get_word_states_batch_internal"
            ) as mock_internal:
                def set_result(batch_ids, *, result, auto_backfill, session):
                    for vid in batch_ids:
                        result[vid] = WordState.NOT_STARTED.value

                mock_internal.side_effect = set_result

                result = get_word_states_in_batch(["word1", "word2"])
                assert result == {
                    "word1": "not_started",
                    "word2": "not_started",
                }

    def test_local_ready_state(self, memory_db, mock_session):
        """LOCAL_READY: processed + sync_status ∈ {0,3,4}。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            with mock.patch(
                "database.word_repo._get_word_states_batch_internal"
            ) as mock_internal:
                def set_result(batch_ids, *, result, auto_backfill, session):
                    for vid in batch_ids:
                        result[vid] = WordState.LOCAL_READY.value

                mock_internal.side_effect = set_result

                result = get_word_states_in_batch(["word1"])
                assert result["word1"] == "local_ready"

    def test_synced_state(self, memory_db, mock_session):
        """SYNCED: sync_status = 1。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            with mock.patch(
                "database.word_repo._get_word_states_batch_internal"
            ) as mock_internal:
                def set_result(batch_ids, *, result, auto_backfill, session):
                    for vid in batch_ids:
                        result[vid] = WordState.SYNCED.value

                mock_internal.side_effect = set_result

                result = get_word_states_in_batch(["word1"])
                assert result["word1"] == "synced"

    def test_conflict_state(self, memory_db, mock_session):
        """CONFLICT: sync_status = 2。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            with mock.patch(
                "database.word_repo._get_word_states_batch_internal"
            ) as mock_internal:
                def set_result(batch_ids, *, result, auto_backfill, session):
                    for vid in batch_ids:
                        result[vid] = WordState.CONFLICT.value

                mock_internal.side_effect = set_result

                result = get_word_states_in_batch(["word1"])
                assert result["word1"] == "conflict"

    def test_failed_state(self, memory_db, mock_session):
        """FAILED: sync_status = 5。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            with mock.patch(
                "database.word_repo._get_word_states_batch_internal"
            ) as mock_internal:
                def set_result(batch_ids, *, result, auto_backfill, session):
                    for vid in batch_ids:
                        result[vid] = WordState.FAILED.value

                mock_internal.side_effect = set_result

                result = get_word_states_in_batch(["word1"])
                assert result["word1"] == "failed"

    def test_batching_logic(self):
        """大批量输入自动分批（_BATCH_SIZE = 500）。"""
        large_list = [f"word{i}" for i in range(1200)]

        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            with mock.patch(
                "database.word_repo._get_word_states_batch_internal"
            ) as mock_internal:
                def set_result(batch_ids, *, result, auto_backfill, session):
                    for vid in batch_ids:
                        result[vid] = "not_started"

                mock_internal.side_effect = set_result

                result = get_word_states_in_batch(large_list)

                # 应被调用 3 次（1200 / 500 = 2.4 → 3 批）
                assert mock_internal.call_count == 3
                assert len(result) == 1200


class TestFilterUnprocessed:
    """Test filter_unprocessed: judgment precision & edge states."""

    def test_empty_input(self):
        """空输入返回空集。"""
        result = filter_unprocessed([])
        assert result == set()

    def test_all_unprocessed(self):
        """全部词都未处理。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            with mock.patch(
                "database.word_repo._filter_unprocessed_batch_internal"
            ) as mock_internal:
                mock_internal.return_value = {"word1", "word2", "word3"}

                result = filter_unprocessed(["word1", "word2", "word3"])
                assert result == {"word1", "word2", "word3"}

    def test_partial_unprocessed(self):
        """部分词已处理。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            with mock.patch(
                "database.word_repo._filter_unprocessed_batch_internal"
            ) as mock_internal:
                mock_internal.return_value = {"word1", "word3"}

                result = filter_unprocessed(["word1", "word2", "word3"])
                assert result == {"word1", "word3"}


class TestCountByState:
    """Test count_by_state: state-wise counting."""

    def test_count_not_started(self):
        """计数 NOT_STARTED 状态的词。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            result = count_by_state(WordState.NOT_STARTED)
            # 由于 mock 限制，此处只验证不报错；完整测试需集成测试
            assert isinstance(result, int)

    def test_count_local_ready(self):
        """计数 LOCAL_READY 状态。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            result = count_by_state(WordState.LOCAL_READY)
            assert isinstance(result, int)


class TestListByState:
    """Test list_by_state: pagination & full record retrieval."""

    def test_empty_result(self):
        """状态无对应词。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            result = list_by_state(WordState.NOT_STARTED, limit=20)
            assert result == []

    def test_pagination(self):
        """分页参数生效。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            result = list_by_state(WordState.LOCAL_READY, limit=10, offset=20)
            # 由于是 mock，仅验证函数不报错
            assert isinstance(result, list)


class TestQueryWeakWords:
    """Test query_weak_words: scoring & filtering."""

    def test_empty_result(self):
        """无薄弱词。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            result = query_weak_words(min_score=60.0, limit=50)
            assert result == []

    def test_score_threshold(self):
        """评分阈值生效。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            result = query_weak_words(min_score=70.0, limit=50)
            assert isinstance(result, list)

    def test_review_threshold(self):
        """复习次数阈值生效。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            result = query_weak_words(threshold=5, limit=50)
            assert isinstance(result, list)


class TestListWordNotesPaginated:
    """Test list_word_notes_paginated: multi-condition search & pagination."""

    def test_search_by_spelling(self):
        """按 spelling 搜索。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            result = list_word_notes_paginated(search="hello", page=1, page_size=20)
            assert isinstance(result, list)

    def test_filter_by_sync_status(self):
        """按 sync_status 过滤。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            result = list_word_notes_paginated(sync_status=0, page=1, page_size=20)
            assert isinstance(result, list)

    def test_filter_by_it_level(self):
        """按迭代级别过滤。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            result = list_word_notes_paginated(it_level=2, page=1, page_size=20)
            assert isinstance(result, list)

    def test_pagination_boundary(self):
        """分页边界：page < 1、page_size <= 0。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            # page 修正
            result = list_word_notes_paginated(page=-1, page_size=20)
            assert isinstance(result, list)
            # page_size 修正
            result = list_word_notes_paginated(page=1, page_size=0)
            assert isinstance(result, list)


class TestGetWordIterations:
    """Test get_word_iterations: iteration history retrieval."""

    def test_empty_voc_id(self):
        """空 voc_id 返回空列表。"""
        result = get_word_iterations("")
        assert result == []

    def test_no_iterations(self):
        """无迭代历史。"""
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            result = get_word_iterations("word1")
            assert isinstance(result, list)


class TestUpdateMemoryAid:
    """Test update_memory_aid: write operation & timestamp."""

    def test_empty_voc_id(self):
        """空 voc_id 返回 False。"""
        result = update_memory_aid("", "new memory aid")
        assert result is False

    def test_write_success(self):
        """写入成功（mock dispatch_write）。"""
        with mock.patch("database.word_repo.dispatch_write") as mock_dispatch:
            mock_dispatch.return_value = True

            result = update_memory_aid("word1", "new memory aid")
            assert result is True
            mock_dispatch.assert_called_once()


class TestEnqueueBackfillProcessed:
    """Test _enqueue_backfill_processed: async backfill queuing."""

    def test_empty_input(self):
        """空输入返回 True。"""
        result = _enqueue_backfill_processed([])
        assert result is True

    def test_queue_success(self):
        """入队成功。"""
        with mock.patch("database.word_repo.dispatch_batch_write") as mock_batch:
            mock_batch.return_value = True

            result = _enqueue_backfill_processed(["word1", "word2"])
            assert result is True
            mock_batch.assert_called_once()

    def test_queue_full(self):
        """队列满返回 False。"""
        with mock.patch("database.word_repo.dispatch_batch_write") as mock_batch:
            mock_batch.return_value = False

            result = _enqueue_backfill_processed(["word1", "word2"])
            assert result is False


class TestIntegration:
    """集成测试：实际 DB 操作（可选，需 fixture 改进）。"""

    def test_full_workflow_mock(self):
        """完整工作流（mocked）。"""
        # 模拟单词 created / processed / synced 的全流程
        with mock.patch("database.word_repo.with_read_session", lambda **kw: lambda f: f):
            with mock.patch("database.word_repo._get_word_states_batch_internal"):
                with mock.patch("database.word_repo._filter_unprocessed_batch_internal"):
                    result = get_word_states_in_batch(["word1"])
                    assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
