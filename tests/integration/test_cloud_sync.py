import os
import pytest
import sqlite3
from config import DB_PATH
from database.connection import _get_hub_conn
from database.momo_words import find_words_in_community_batch, mark_processed, save_ai_word_note, sync_databases
from database.schema import init_db
from tests.factories import DataFactory


@pytest.mark.integration
def test_full_cloud_sync_loop(cloud_integ_env, monkeypatch):
    """
    验证完整同步闭环：本地写入 -> 云端同步 -> 查询验证。
    """
    print("\n!!! [ALIVE] test_full_cloud_sync_loop START !!!", flush=True)
    # 1. 初始化 DB (使用由 cloud_integ_env 自动注入的本地测试路径)
    local_db = DB_PATH
    print(f"[DEBUG] Local DB Path: {local_db}")
    init_db(local_db)
    
    # 2. 通过工厂生成测试数据并写入本地
    voc_id = f"test-sync-{os.urandom(4).hex()}"
    test_word = DataFactory.create_word_record(voc_id=voc_id, spelling="integration")
    
    save_ai_word_note(
        voc_id, 
        {"spelling": test_word["voc_spelling"], "basic_meanings": "integration test"},
        db_path=local_db,
        metadata={"content_origin": "ai_generated"}
    )
    mark_processed(voc_id, "integration", db_path=local_db)

    # 3. 执行同步 (Fixture 已确保此时环境为强制云端且 HTTPS 已开启)
    print(f"\n[STEP] Starting Sync to Cloud...")
    import time
    start_time = time.time()
    stats = sync_databases(local_db)
    elapsed = time.time() - start_time
    print(f"[STEP] Sync finished in {elapsed:.2f}s: {stats}")
    
    assert stats["status"] == "ok"

    # 4. 跨模块验证：直接从云端 Lookup
    print("[STEP] Verifying data presence in cloud via lookup...")
    # 内部会自动使用补丁后的凭证
    results = find_words_in_community_batch([voc_id], skip_cloud=False)
    
    assert voc_id in results
    note_dict, source = results[voc_id]
    assert note_dict["spelling"] == "integration"
    print(f"[SUCCESS] Data sync and cloud lookup verified successfully.")

@pytest.mark.integration
def test_hub_health_check(cloud_integ_env):
    """验证 Hub 数据库的连通性。"""
    conn = _get_hub_conn()
    cur = conn.cursor()
    
    # Hub 应该存在 users 表
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    assert cur.fetchone() is not None
    conn.close()
