import pytest
import sqlite3
import datetime
from core.weak_word_filter import WeakWordFilter

@pytest.fixture
def mock_db_manager(monkeypatch):
    """拦截 db_manager，提供一个完全真实的，运行在内存中的 SQLite 连接替代 _get_read_conn"""
    # 建立一个跨整个会话生命周期的内存库
    # 建立一个共享的内存库，只要这一个引用还在，数据就不灭
    # 这样被测试代码怎么 close 都可以
    shared_db_conn = sqlite3.connect("file:testdb?mode=memory&cache=shared", uri=True)
    
    # 模拟 get_read_conn 返回独立但连接到同一内存库的新连接
    def mock_get_read_conn(path):
        conn = sqlite3.connect("file:testdb?mode=memory&cache=shared", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    # 初始化 Schema 和 Dummy Data
    init_conn = sqlite3.connect("file:testdb?mode=memory&cache=shared", uri=True)
    cur = init_conn.cursor()
    cur.executescript('''
        CREATE TABLE IF NOT EXISTS word_progress_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voc_id TEXT NOT NULL,
            familiarity_short REAL,
            familiarity_long REAL,
            review_count INTEGER,
            it_level INTEGER DEFAULT 0,
            learning_stage TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS processed_words (
            voc_id TEXT PRIMARY KEY,
            spelling TEXT NOT NULL,
            basic_meanings TEXT,
            original_meanings TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS ai_word_notes (
            voc_id TEXT PRIMARY KEY,
            spelling TEXT,
            basic_meanings TEXT,
            it_level INTEGER DEFAULT 0,
            memory_aid TEXT,
            raw_full_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    import datetime
    now = datetime.datetime.now()
    records = []
    notes = []
    processed = []
    # 模拟高复习次数和各种熟悉度的单词，以测试 user stats
    for i in range(1, 101):
        voc_id = f"v_mock_{i}"
        fam = 0.5 + (i * 0.03)
        rev = i % 25 + 1
        
        # 历史记录
        records.append((voc_id, fam + 0.1, rev - 1, 0, (now - datetime.timedelta(days=2)).isoformat()))
        records.append((voc_id, fam, rev, 1, now.isoformat()))
        
        # 强关联记录
        notes.append((voc_id, f"word{i}"))
        processed.append((voc_id, f"word{i}"))
        
    cur.executemany("INSERT INTO word_progress_history (voc_id, familiarity_short, review_count, it_level, created_at) VALUES (?, ?, ?, ?, ?)", records)
    cur.executemany("INSERT INTO ai_word_notes (voc_id, spelling) VALUES (?, ?)", notes)
    cur.executemany("INSERT INTO processed_words (voc_id, spelling) VALUES (?, ?)", processed)
    init_conn.commit()
    init_conn.close()

    import core.weak_word_filter
    monkeypatch.setattr(core.weak_word_filter, "_get_read_conn", mock_get_read_conn)
    
    yield shared_db_conn
    shared_db_conn.close()

def test_get_user_stats(mock_db_manager):
    """测试完整执行不崩溃且能够查出所有指标"""
    fw = WeakWordFilter()
    stats = fw._get_user_stats()
    
    assert "avg_familiarity" in stats
    assert "total_words" in stats
    assert "study_frequency" in stats
    assert "avg_review_count" in stats
    
    assert stats["total_words"] == 100
    assert stats["avg_familiarity"] > 1.0 # 预期在2左右
    assert stats["study_frequency"] in ["low", "normal", "high"]

def test_calculate_weak_score():
    """纯逻辑测试，无 DB"""
    fw = WeakWordFilter()
    word = {
        "familiarity_short": 1.0,  # +26.66
        "review_count": 2,         # +20
        "it_level": 3,             # +6
        "created_at": (datetime.datetime.now() - datetime.timedelta(days=8)).isoformat() # +4
    }
    
    score = fw.calculate_weak_score(word)
    # 26.66 + 20 + 6 + 4 = 56.66
    assert 56 < score < 57

def test_dynamic_threshold(mock_db_manager):
    fw = WeakWordFilter()
    threshold = fw.get_dynamic_threshold()
    assert isinstance(threshold, float)
    assert 2.0 <= threshold <= 4.0

def test_get_weak_words_by_category(mock_db_manager):
    fw = WeakWordFilter()
    res = fw.get_weak_words_by_category()
    assert "urgent" in res
    assert "normal" in res
    assert "potential" in res
    
    # 应当返回真实从 SQLite 中组合推算分类的集合
    total = len(res["urgent"]) + len(res["normal"]) + len(res["potential"])
    assert total > 0
