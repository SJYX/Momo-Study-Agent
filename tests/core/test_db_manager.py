import os
import pytest
import sqlite3
import json
from core.db_manager import init_db, is_processed, mark_processed, save_ai_word_note, save_ai_batch

@pytest.fixture
def temp_db(tmp_path):
    """创建一个临时数据库文件。"""
    db_file = tmp_path / "test_isolated.db"
    return str(db_file)

def test_db_initialization(temp_db):
    """测试数据库初始化是否创建了所有的表。"""
    init_db(temp_db)
    
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    # 检查表是否存在
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]
    
    assert "processed_words" in tables
    assert "ai_word_notes" in tables
    assert "ai_batches" in tables
    conn.close()

def test_mark_and_check_processed(temp_db):
    """测试标记处理和查重逻辑。"""
    voc_id = "12345"
    spelling = "test_word"
    
    # 初始状态应为未处理
    assert is_processed(voc_id, temp_db) is False
    
    # 标记处理
    mark_processed(voc_id, spelling, temp_db)
    
    # 现在应为已处理
    assert is_processed(voc_id, temp_db) is True

def test_save_ai_word_note_with_metadata(temp_db):
    """测试保存带元数据的 AI 详细笔记。"""
    voc_id = "999"
    payload = {
        "spelling": "apple",
        "basic_meanings": "苹果",
        "ielts_focus": "High frequency",
        "memory_aid": "A is for Apple"
    }
    metadata = {
        "batch_id": "batch-1",
        "original_meanings": "n. 苹果",
        "maimemo_context": {"review_count": 5}
    }
    
    save_ai_word_note(voc_id, payload, db_path=temp_db, metadata=metadata)
    
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
    row = cur.fetchone()
    conn.close()
    
    assert row is not None
    assert row["spelling"] == "apple"
    assert row["batch_id"] == "batch-1"
    assert row["original_meanings"] == "n. 苹果"
    context = json.loads(row["maimemo_context"])
    assert context["review_count"] == 5

def test_save_ai_batch(temp_db):
    """测试保存 AI 批次元数据。"""
    batch_data = {
        "batch_id": "batch-1",
        "model_name": "gemini-flash",
        "total_latency_ms": 1500,
        "total_tokens": 500
    }
    save_ai_batch(batch_data, temp_db)
    
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM ai_batches WHERE batch_id = ?", ("batch-1",))
    row = cur.fetchone()
    conn.close()
    
    assert row is not None
    assert row["model_name"] == "gemini-flash"
    assert row["total_latency_ms"] == 1500
