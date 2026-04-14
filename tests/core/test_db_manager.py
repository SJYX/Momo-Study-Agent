import os
import pytest
import sqlite3
import json
import core.db_manager as db_manager
from core.db_manager import init_db, is_processed, mark_processed, save_ai_word_note, save_ai_batch, find_word_in_community, find_words_in_community_batch

@pytest.fixture
def temp_db(tmp_path):
    """创建一个临时数据库文件。"""
    db_file = tmp_path / "test_isolated.db"
    init_db(str(db_file))
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


def test_find_word_in_community_requires_matching_ai_context(temp_db, monkeypatch):
    voc_id = "777"
    payload = {
        "spelling": "context_word",
        "basic_meanings": "上下文单词",
    }
    metadata = {
        "batch_id": "batch-ctx-1",
    }

    save_ai_batch(
        {
            "batch_id": "batch-ctx-1",
            "ai_provider": "gemini",
            "prompt_version": "prompt-v1",
            "model_name": "gemini-flash",
        },
        temp_db,
    )
    save_ai_word_note(voc_id, payload, db_path=temp_db, metadata=metadata)

    monkeypatch.setattr(db_manager, "DB_PATH", temp_db)
    monkeypatch.setattr(db_manager, "TURSO_DB_URL", None)
    monkeypatch.setattr(db_manager, "TURSO_AUTH_TOKEN", None)
    monkeypatch.setattr(db_manager, "HAS_LIBSQL", False)

    matched = find_word_in_community(voc_id, ai_provider="gemini", prompt_version="prompt-v1")
    assert matched is not None
    assert matched[1] == "当前数据库"

    mismatched_provider = find_word_in_community(voc_id, ai_provider="mimo", prompt_version="prompt-v1")
    assert mismatched_provider is None

    mismatched_prompt = find_word_in_community(voc_id, ai_provider="gemini", prompt_version="prompt-v2")
    assert mismatched_prompt is None


def test_find_words_in_community_batch_queries_cloud_for_local_misses(temp_db, monkeypatch):
    local_voc_id = "1001"
    cloud_voc_id = "1002"

    save_ai_batch(
        {
            "batch_id": "batch-local",
            "ai_provider": "gemini",
            "prompt_version": "prompt-v1",
            "model_name": "gemini-flash",
        },
        temp_db,
    )
    save_ai_word_note(
        local_voc_id,
        {"spelling": "local_word", "basic_meanings": "本地单词"},
        db_path=temp_db,
        metadata={"batch_id": "batch-local"},
    )

    monkeypatch.setattr(db_manager, "DB_PATH", temp_db)
    monkeypatch.setattr(db_manager, "TURSO_DB_URL", "cloud-url")
    monkeypatch.setattr(db_manager, "TURSO_AUTH_TOKEN", "cloud-token")
    monkeypatch.setattr(db_manager, "HAS_LIBSQL", True)
    monkeypatch.setattr(db_manager, "_collect_cloud_lookup_targets", lambda: [("cloud-url", "cloud-token", "云端数据库")])

    class FakeCloudCursor:
        def __init__(self):
            self.description = [("voc_id",), ("spelling",), ("basic_meanings",), ("batch_ai_provider",), ("batch_prompt_version",), ("batch_id",)]
            self.executed_params = None

        def execute(self, sql, params):
            self.executed_params = list(params)
            assert self.executed_params == [cloud_voc_id]
            return self

        def fetchall(self):
            return [
                (cloud_voc_id, "cloud_word", "云端单词", "gemini", "prompt-v1", "batch-cloud"),
            ]

    class FakeCloudConn:
        def __init__(self):
            self.cursor_obj = FakeCloudCursor()

        def cursor(self):
            return self.cursor_obj

        def close(self):
            pass

    monkeypatch.setattr(db_manager, "_get_cloud_conn", lambda url, token: FakeCloudConn())

    results = find_words_in_community_batch(
        [local_voc_id, cloud_voc_id],
        skip_cloud=False,
        ai_provider="gemini",
        prompt_version="prompt-v1",
    )

    assert local_voc_id in results
    assert results[local_voc_id][1] == "当前数据库"
    assert cloud_voc_id in results
    assert results[cloud_voc_id][1] == "云端数据库"
