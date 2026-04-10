import pytest
import json
import sqlite3
import os
from core.iteration_manager import IterationManager
from core.db_manager import init_db, log_progress_snapshots, _get_conn

@pytest.fixture
def temp_db(tmp_path, mocker):
    """提供一个完全隔离的临时测试数据库。"""
    db_path = str(tmp_path / "test_it.db")
    
    # 彻底 Patch 掉所有模块里的 DB_PATH，确保它们都指向这个临时文件
    mocker.patch("core.db_manager.DB_PATH", db_path)
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
            "refined_content": "Selected Best Note"
        }), {}
    )
    mock_momo.create_note.return_value = {"success": True}
    
    manager.run_iteration(familiarity_threshold=3.0)
    
    # 验证状态变更为 Level 1
    conn = _get_conn(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT it_level, it_history FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
    row = cur.fetchone()
    assert row[0] == 1
    assert "AI Scored 9" in row[1]
    
    # --- 阶段二：Level 2 (由于熟悉度未提升触发重炼) ---
    # 模拟用户又背了一次，但熟悉度只涨了 0.01 (低于 0.1 的阈值)
    log_progress_snapshots([
        {"voc_id": voc_id, "voc_spelling": spell, "short_term_familiarity": 1.01, "review_count": 6}
    ], db_path=temp_db)
    
    # 模拟强力重炼 AI 返回 (数组格式)
    mock_ai.generate_with_instruction.return_value = (
        json.dumps([{"spelling": spell, "memory_aid": "**[Refined]** Power Hook"}]), {}
    )
    
    manager.run_iteration(familiarity_threshold=3.0)
    
    # 验证状态变更为 Level 2
    cur.execute("SELECT it_level, it_history, memory_aid FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
    row = cur.fetchone()
    conn.close()
    
    assert row[0] == 2
    assert "Power Refined" in row[1]
    assert "**[Refined]**" in row[2]
    assert "Method A" in row[2] # 验证了旧内容被保留在下方
