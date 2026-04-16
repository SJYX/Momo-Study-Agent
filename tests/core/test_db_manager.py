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
        "content_origin": "community_reused",
        "content_source_db": "history_001.db",
        "content_source_scope": "local_history",
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
    assert row["content_origin"] == "community_reused"
    assert row["content_source_db"] == "history_001.db"
    assert row["content_source_scope"] == "local_history"
    context = json.loads(row["maimemo_context"])
    assert context["review_count"] == 5


def test_save_ai_word_note_defaults_content_origin(temp_db):
    """测试新生成笔记默认标记为 AI 来源。"""
    voc_id = "1000"
    payload = {
        "spelling": "banana",
        "basic_meanings": "香蕉",
    }

    save_ai_word_note(voc_id, payload, db_path=temp_db)

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT content_origin, content_source_db, content_source_scope FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row["content_origin"] == "ai_generated"
    assert row["content_source_db"] is None
    assert row["content_source_scope"] is None


def test_init_db_backfills_legacy_content_origin(temp_db):
    """测试旧数据在初始化时会被回填来源字段。"""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO ai_word_notes (voc_id, spelling, basic_meanings, batch_id, sync_status, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("old-1", "oldword", "旧词义", "batch-old", 0, None),
    )
    cur.execute(
        "INSERT INTO ai_word_notes (voc_id, spelling, basic_meanings, sync_status, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("old-2", "legacyword", "无来源旧词义", 0, None),
    )
    conn.commit()
    conn.close()

    init_db(temp_db)

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT content_origin, content_source_scope FROM ai_word_notes WHERE voc_id = ?", ("old-1",))
    row1 = cur.fetchone()
    cur.execute("SELECT content_origin, content_source_scope FROM ai_word_notes WHERE voc_id = ?", ("old-2",))
    row2 = cur.fetchone()
    conn.close()

    assert row1["content_origin"] == "ai_generated"
    assert row1["content_source_scope"] == "ai_batch"
    assert row2["content_origin"] == "legacy_unknown"
    assert row2["content_source_scope"] == "legacy"

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


def test_co_origin_notes_init_with_correct_sync_status(temp_db):
    """
    验证修复 1：co_origin 笔记在保存时的同步状态初始化
    
    - ai_generated 笔记应初始化为 sync_status=0（需要同步）
    - community_reused 笔记应初始化为 sync_status=1（已同步）
    - history_reused 笔记应初始化为 sync_status=1（已同步）
    - legacy_unknown 笔记应初始化为 sync_status=0（待审）
    """
    init_db(temp_db)
    
    # 保存不同来源的笔记
    ai_gen_note = {
        "voc_id": "ai_001",
        "payload": {"spelling": "word1", "basic_meanings": "意思1"},
        "metadata": {"content_origin": "ai_generated"}
    }
    
    community_note = {
        "voc_id": "cc_001",
        "payload": {"spelling": "word2", "basic_meanings": "意思2"},
        "metadata": {"content_origin": "community_reused"}
    }
    
    history_note = {
        "voc_id": "hist_001",
        "payload": {"spelling": "word3", "basic_meanings": "意思3"},
        "metadata": {"content_origin": "history_reused"}
    }
    
    legacy_note = {
        "voc_id": "leg_001",
        "payload": {"spelling": "word4", "basic_meanings": "意思4"},
        "metadata": {"content_origin": "legacy_unknown"}
    }
    
    db_manager.save_ai_word_notes_batch([ai_gen_note, community_note, history_note, legacy_note], temp_db)
    
    # 验证每个笔记的 sync_status
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    
    # ai_generated 应为 0
    cur.execute("SELECT sync_status FROM ai_word_notes WHERE voc_id = 'ai_001'")
    status = cur.fetchone()[0]
    assert status == 0, f"ai_generated 应初始化为 0，实际为 {status}"
    
    # community_reused 应为 1
    cur.execute("SELECT sync_status FROM ai_word_notes WHERE voc_id = 'cc_001'")
    status = cur.fetchone()[0]
    assert status == 1, f"community_reused 应初始化为 1，实际为 {status}"
    
    # history_reused 应为 1
    cur.execute("SELECT sync_status FROM ai_word_notes WHERE voc_id = 'hist_001'")
    status = cur.fetchone()[0]
    assert status == 1, f"history_reused 应初始化为 1，实际为 {status}"
    
    # legacy_unknown 应为 0
    cur.execute("SELECT sync_status FROM ai_word_notes WHERE voc_id = 'leg_001'")
    status = cur.fetchone()[0]
    assert status == 0, f"legacy_unknown 应初始化为 0，实际为 {status}"
    
    conn.close()


def test_get_unsynced_notes_only_returns_ai_generated(temp_db):
    """
    验证修复 2：get_unsynced_notes 仅返回 ai_generated 的待同步笔记
    
    - co_origin 笔记不应出现在待同步队列中（即使 sync_status=0）
    - 仅 ai_generated 的 sync_status=0 笔记应被返回
    """
    init_db(temp_db)
    
    # 保存混合的笔记
    notes_batch = [
        {
            "voc_id": "ai_1",
            "payload": {"spelling": "ai_word", "basic_meanings": "AI 生成"},
            "metadata": {"content_origin": "ai_generated"}
        },
        {
            "voc_id": "cc_1",
            "payload": {"spelling": "cc_word", "basic_meanings": "社区复用"},
            "metadata": {"content_origin": "community_reused"}
        },
        {
            "voc_id": "hist_1",
            "payload": {"spelling": "hist_word", "basic_meanings": "历史复用"},
            "metadata": {"content_origin": "history_reused"}
        },
        {
            "voc_id": "ai_2",
            "payload": {"spelling": "ai_word2", "basic_meanings": "AI 生成 2"},
            "metadata": {"content_origin": "ai_generated"}
        },
    ]
    
    db_manager.save_ai_word_notes_batch(notes_batch, temp_db)
    
    # 获取未同步笔记
    unsynced = db_manager.get_unsynced_notes(temp_db)
    
    # 应该只有 2 条 ai_generated 笔记
    assert len(unsynced) == 2, f"应返回 2 条未同步笔记，实际返回 {len(unsynced)} 条"
    
    voc_ids = [note["voc_id"] for note in unsynced]
    assert "ai_1" in voc_ids, "ai_1 应在未同步队列中"
    assert "ai_2" in voc_ids, "ai_2 应在未同步队列中"
    assert "cc_1" not in voc_ids, "cc_1 不应在未同步队列中"
    assert "hist_1" not in voc_ids, "hist_1 不应在未同步队列中"


def test_set_note_sync_status_dual_db_sync(temp_db):
    """
    验证修复 3：set_note_sync_status 在双库模式下的状态同步
    
    当更新 sync_status 时，本地缓存库也应该被同步（模拟云端+本地场景）
    """
    init_db(temp_db)
    
    # 保存一条笔记
    voc_id = "test_voc"
    payload = {"spelling": "test", "basic_meanings": "测试"}
    metadata = {"content_origin": "ai_generated"}
    
    db_manager.save_ai_word_note(voc_id, payload, db_path=temp_db, metadata=metadata)
    
    # 初始状态应为 0
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT sync_status FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
    initial_status = cur.fetchone()[0]
    assert initial_status == 0, f"初始状态应为 0，实际为 {initial_status}"
    conn.close()
    
    # 更新为 sync_status=1
    success = db_manager.set_note_sync_status(voc_id, 1, temp_db)
    assert success is True, "更新状态应成功"
    
    # 验证更新后的状态
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT sync_status FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
    updated_status = cur.fetchone()[0]
    assert updated_status == 1, f"更新后状态应为 1，实际为 {updated_status}"
    conn.close()
    
    # 再次更新为 sync_status=2
    success = db_manager.set_note_sync_status(voc_id, 2, temp_db)
    assert success is True, "第二次更新应成功"
    
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT sync_status FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
    final_status = cur.fetchone()[0]
    assert final_status == 2, f"最终状态应为 2，实际为 {final_status}"
    conn.close()
