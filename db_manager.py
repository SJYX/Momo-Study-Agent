import sqlite3
import os
import json
from config import DB_PATH, TEST_DB_PATH

# ──────────────────────────────────────────────────────────────────────────────
# 通用内部工具 (Internal Helpers)
# ──────────────────────────────────────────────────────────────────────────────

def _get_conn(db_path: str) -> sqlite3.Connection:
    """打开连接前确保父目录存在。"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return sqlite3.connect(db_path)

def _create_tables(cur: sqlite3.Cursor):
    """建表 DDL，正式库和测试库共用同一套 Schema。"""
    # 1. 单词处理历史记录（主表，最小化存储，仅用于判定是否处理过）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS processed_words (
            voc_id TEXT PRIMARY KEY,
            spelling TEXT,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. 增强型 AI 笔记表 (10+ 维度全量知识图谱)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_word_notes (
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
            raw_full_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 3. 运行日志表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS test_run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_count INTEGER,
            sample_count INTEGER,
            sample_words TEXT,
            ai_calls INTEGER,
            success_parsed INTEGER,
            is_dry_run BOOLEAN,
            error_msg TEXT,
            ai_results_json TEXT
        )
    """)

# ──────────────────────────────────────────────────────────────────────────────
# 初始化与通用操作
# ──────────────────────────────────────────────────────────────────────────────

def init_db(db_path: str = None):
    """初始化数据库环境。"""
    path = db_path or DB_PATH
    conn = _get_conn(path)
    cur = conn.cursor()
    _create_tables(cur)
    conn.commit()
    conn.close()

def is_processed(voc_id: str, db_path: str = None) -> bool:
    """检查单词是否已存在于处理历史中。"""
    path = db_path or DB_PATH
    conn = _get_conn(path)
    cur = conn.cursor()
    _create_tables(cur) # 兜底建表
    cur.execute("SELECT 1 FROM processed_words WHERE voc_id = ?", (str(voc_id),))
    res = cur.fetchone()
    conn.close()
    return res is not None

def mark_processed(voc_id: str, spelling: str, db_path: str = None):
    """将单词标记为已处理。"""
    path = db_path or DB_PATH
    conn = _get_conn(path)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO processed_words (voc_id, spelling) VALUES (?, ?)", (str(voc_id), spelling))
    conn.commit()
    conn.close()

# ──────────────────────────────────────────────────────────────────────────────
# 核心数据持久化 (Persistence)
# ──────────────────────────────────────────────────────────────────────────────

def save_ai_word_note(voc_id: str, payload: dict, db_path: str = None):
    """保存 AI 生成的详细笔记到指定库。"""
    path = db_path or DB_PATH
    conn = _get_conn(path)
    cur = conn.cursor()
    _create_tables(cur) # 确保环境
    
    spell = payload.get("spelling", "")
    raw_full_text = payload.get("raw_full_text") or _build_raw_markdown(payload)

    cur.execute("""
        INSERT OR REPLACE INTO ai_word_notes (
            voc_id, spelling, basic_meanings, ielts_focus, collocations,
            traps, synonyms, discrimination, example_sentences, memory_aid, raw_full_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(voc_id), spell,
        payload.get("basic_meanings", ""),
        payload.get("ielts_focus", ""),
        payload.get("collocations", ""),
        payload.get("traps", ""),
        payload.get("synonyms", ""),
        payload.get("discrimination", ""),
        payload.get("example_sentences", ""),
        payload.get("memory_aid", ""),
        raw_full_text
    ))
    conn.commit()
    conn.close()

def _build_raw_markdown(payload: dict) -> str:
    """按标准格式拼接完整的 Markdown 预览。"""
    spell = payload.get("spelling", "")
    text = f"### {spell}\n\n{payload.get('basic_meanings', '')}\n\n"
    for field in ["ielts_focus", "collocations", "traps", "synonyms", "discrimination", "example_sentences", "memory_aid"]:
        val = payload.get(field)
        if val:
            text += f"**[{field.replace('_', ' ').upper()}]**\n{val}\n\n"
    return text

# ──────────────────────────────────────────────────────────────────────────────
# 测试专用 (Testing Specific)
# ──────────────────────────────────────────────────────────────────────────────

def save_test_word_note(voc_id: str, payload: dict):
    """【测试专用】写入测试库隔离环境。"""
    save_ai_word_note(voc_id, payload, db_path=TEST_DB_PATH)

def log_test_run(
    total_count: int,
    sample_count: int,
    words_sampled: list,
    ai_calls: int,
    success_parsed: int,
    is_dry_run: bool = True,
    error_msg: str = "",
    ai_results: list = None
) -> int:
    """记录运行汇总日志（仅存入测试库）。"""
    conn = _get_conn(TEST_DB_PATH)
    cur = conn.cursor()
    _create_tables(cur)
    ai_json = json.dumps(ai_results, ensure_ascii=False) if ai_results else ""
    cur.execute("""
        INSERT INTO test_run_logs (
            total_count, sample_count, sample_words, ai_calls, 
            success_parsed, is_dry_run, error_msg, ai_results_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        total_count, sample_count, ",".join(words_sampled),
        ai_calls, success_parsed, is_dry_run, error_msg, ai_json
    ))
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id
