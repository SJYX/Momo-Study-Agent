import pytest
import json
import sqlite3
import os
from core.iteration_manager import IterationManager
from database.connection import _get_conn
from database.momo_words import log_progress_snapshots
from database.schema import init_db

@pytest.fixture
def temp_db(tmp_path, mocker):
    """提供一个完全隔离的临时测试数据库。"""
    db_path = str(tmp_path / "test_it.db")
    
    # 彻底 Patch 掉所有模块里的 DB_PATH，确保它们都指向这个临时文件
    mocker.patch("database.connection.DB_PATH", db_path)
    mocker.patch("core.iteration_manager.DB_PATH", db_path)
    
    init_db(db_path)
    return db_path

@pytest.fixture
def mock_deps(mocker):
    """Mock AI 客户端和墨墨 API 接口。"""
    mock_ai = mocker.Mock()
    mock_momo = mocker.Mock()
    return mock_ai, mock_momo

def test_iteration_lifecycle(temp_db, mock_deps, mocker):
    """模拟一个完整的迭代生命周期：L0 -> L1 (选优) -> L2 (重炼)。"""
    mock_ai, mock_momo = mock_deps
    logger = mocker.Mock()
    
    # 1. 准备初始数据 (Level 0)
    voc_id = "test_v1"
    spell = "apple"
    
    conn = _get_conn(temp_db)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ai_word_notes (voc_id, spelling, memory_aid, it_level, it_history)
        VALUES (?, ?, ?, ?, ?)
    """, (voc_id, spell, "Method A\nMethod B", 0, "[]"))
    conn.commit()
    conn.close()
    
    # 模拟薄弱熟悉度
    mocker.patch("core.iteration_manager.WeakWordFilter._get_user_stats", return_value={"total": 1})
    mocker.patch("core.iteration_manager.WeakWordFilter.get_dynamic_threshold", return_value=3.0)
    mocker.patch("core.iteration_manager.WeakWordFilter.get_weak_words_by_category", return_value={"urgent": [], "normal": []})
    mocker.patch(
        "core.iteration_manager.WeakWordFilter.get_weak_words_by_score",
        side_effect=[
            [{"voc_id": voc_id, "spelling": spell, "it_level": 0, "familiarity_short": 1.0, "memory_aid": "Method A\nMethod B", "meanings": "n. 苹果"}],
            [{"voc_id": voc_id, "spelling": spell, "it_level": 1, "familiarity_short": 1.01, "memory_aid": "Method A\nMethod B", "meanings": "n. 苹果"}],
        ],
    )
    log_progress_snapshots([
        {"voc_id": voc_id, "voc_spelling": spell, "short_term_familiarity": 1.0, "review_count": 5}
    ], db_path=temp_db)

    # --- 阶段一：Level 1 (选优同步) ---
    manager = IterationManager(mock_ai, mock_momo, logger)
    
    # 模拟 AI 打分返回
    mock_ai.generate_with_instruction.return_value = (
        json.dumps({
            "score": 9,
            "justification": "Test justification",
            "refined_content": "Selected Best Note",
            "tags": ["词根词缀", "联想"]
        }), {}
    )
    mock_momo.create_note.return_value = {"success": True}
    mock_momo.list_notepads.return_value = {"notepads": []}
    mock_momo.create_notepad.return_value = {"success": True}
    
    manager.run_iteration()
    
    # 验证状态变更为 Level 1
    conn = _get_conn(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT it_level, it_history FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
    row = cur.fetchone()
    assert row[0] == 1
    assert "AI Scored 9" in row[1]
    assert mock_momo.create_note.call_args_list[0][1]["tags"] == ["词根词缀", "联想"]

    cur.execute("SELECT id, voc_id, stage, it_level, score, justification, tags, refined_content, candidate_notes, raw_response FROM ai_word_iterations WHERE voc_id = ? ORDER BY id ASC", (voc_id,))
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][2] == "level_1_selection"
    assert rows[0][3] == 1
    assert rows[0][4] == 9
    assert "Test justification" in rows[0][5]
    assert rows[0][6] == '["词根词缀", "联想"]'
    assert rows[0][7] == "Selected Best Note"
    assert "Method A" in rows[0][8]
    assert '"score": 9' in rows[0][9]
    
    # --- 阶段二：Level 2 (由于熟悉度未提升触发重炼) ---
    # 模拟用户又背了一次，但熟悉度只涨了 0.01 (低于 0.1 的阈值)
    log_progress_snapshots([
        {"voc_id": voc_id, "voc_spelling": spell, "short_term_familiarity": 1.01, "review_count": 6}
    ], db_path=temp_db)
    
    # 模拟强力重炼 AI 返回 (数组格式)
    mock_ai.generate_with_instruction.return_value = (
        json.dumps([{"spelling": spell, "memory_aid": "**[Refined]** Power Hook", "tags": ["帮助"]}]), {}
    )
    
    manager.run_iteration()
    
    # 验证状态变更为 Level 2
    cur.execute("SELECT it_level, it_history, memory_aid FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
    row = cur.fetchone()

    assert row[0] == 2
    assert "Power Refined" in row[1]
    assert "**[Refined]**" in row[2]
    assert "Method A" in row[2] # 验证了旧内容被保留在下方
    assert mock_momo.create_note.call_args_list[1][1]["tags"] == ["帮助"]

    cur.execute("SELECT stage, it_level, score, justification, tags, refined_content, candidate_notes, raw_response FROM ai_word_iterations WHERE voc_id = ? ORDER BY id ASC", (voc_id,))
    rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[1][0] == "level_2_refinement"
    assert rows[1][1] == 2
    assert rows[1][2] is None
    assert rows[1][3] is None
    assert rows[1][4] == '["帮助"]'
    assert rows[1][5] == "**[Refined]** Power Hook"
    assert "Method A" in rows[1][6]
    assert '"memory_aid": "**[Refined]** Power Hook"' in rows[1][7]
    conn.close()
