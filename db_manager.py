import sqlite3
import os
import json

# ── 路径配置 ───────────────────────────────────────────────────────────────────
_DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
DB_PATH      = os.path.join(_DATA_DIR, "history.db")   # 正式库
TEST_DB_PATH = os.path.join(_DATA_DIR, "test.db")      # 测试库（隔离，不影响正式数据）


# ══════════════════════════════════════════════════════════════════════════════
# 通用内部工具
# ══════════════════════════════════════════════════════════════════════════════
def _conn(db_path: str) -> sqlite3.Connection:
    """打开连接前确保目录存在。"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return sqlite3.connect(db_path)


def _create_tables(cur: sqlite3.Cursor):
    """建表 DDL，正式库和测试库共用同一套 Schema。"""
    cur.execute("DROP TABLE IF EXISTS processed_words")   # 清理废旧表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_word_notes (
            voc_id            TEXT PRIMARY KEY,
            spelling          TEXT,
            basic_meanings    TEXT,
            ielts_focus       TEXT,
            collocations      TEXT,
            traps             TEXT,
            synonyms          TEXT,
            discrimination    TEXT,
            example_sentences TEXT,
            memory_aid        TEXT,
            raw_full_text     TEXT,
            created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS test_run_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
            total_today     INTEGER,
            sample_size     INTEGER,
            words_sampled   TEXT,       -- JSON 数组
            ai_call_count   INTEGER,
            words_returned  INTEGER,
            success         INTEGER,    -- 1=成功, 0=失败
            error_msg       TEXT,
            ai_results_json TEXT        -- 完整 AI 返回 JSON
        )
    """)


# ══════════════════════════════════════════════════════════════════════════════
# 初始化
# ══════════════════════════════════════════════════════════════════════════════
def init_db(db_path: str = None):
    """初始化数据库（默认正式库）。"""
    path = db_path or DB_PATH
    conn = _conn(path)
    cur  = conn.cursor()
    _create_tables(cur)
    conn.commit()
    conn.close()


def init_test_db():
    """初始化测试专用数据库 data/test.db。"""
    init_db(db_path=TEST_DB_PATH)


# ══════════════════════════════════════════════════════════════════════════════
# 正式库：去重 & 写入
# ══════════════════════════════════════════════════════════════════════════════
def is_processed(voc_id: str) -> bool:
    conn = _conn(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT 1 FROM ai_word_notes WHERE voc_id = ?", (str(voc_id),))
    result = cur.fetchone() is not None
    conn.close()
    return result


def mark_processed(voc_id: str, payload: dict):
    conn = _conn(DB_PATH)
    cur  = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO ai_word_notes (
            voc_id, spelling, basic_meanings, ielts_focus, collocations,
            traps, synonyms, discrimination, example_sentences, memory_aid, raw_full_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(voc_id),
        payload.get("spelling", ""),
        payload.get("basic_meanings", ""),
        payload.get("ielts_focus", ""),
        payload.get("collocations", ""),
        payload.get("traps", ""),
        payload.get("synonyms", ""),
        payload.get("discrimination", ""),
        payload.get("example_sentences", ""),
        payload.get("memory_aid", ""),
        payload.get("raw_full_text", ""),
    ))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 测试库：写入 ai_word_notes（结构与正式库完全一致）
# ══════════════════════════════════════════════════════════════════════════════
def save_test_word_note(voc_id: str, payload: dict):
    """
    将单个 AI 分析结果按 ai_word_notes 字段结构写入测试库。
    使用 INSERT OR REPLACE 以便重复测试可覆盖旧记录。
    """
    # 组装 raw_full_text（与正式流程保持一致）
    spell         = payload.get("spelling", "")
    raw_full_text = payload.get("raw_full_text") or _build_raw(payload)

    conn = _conn(TEST_DB_PATH)
    cur  = conn.cursor()
    _create_tables(cur)   # 确保表存在（首次独立运行场景）
    cur.execute("""
        INSERT OR REPLACE INTO ai_word_notes (
            voc_id, spelling, basic_meanings, ielts_focus, collocations,
            traps, synonyms, discrimination, example_sentences, memory_aid, raw_full_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(voc_id),
        spell,
        payload.get("basic_meanings", ""),
        payload.get("ielts_focus", ""),
        payload.get("collocations", ""),
        payload.get("traps", ""),
        payload.get("synonyms", ""),
        payload.get("discrimination", ""),
        payload.get("example_sentences", ""),
        payload.get("memory_aid", ""),
        raw_full_text,
    ))
    conn.commit()
    conn.close()


def _build_raw(payload: dict) -> str:
    """按正式流程的格式拼接 raw_full_text。"""
    spell = payload.get("spelling", "")
    text  = f"### {spell}\n\n"
    text += f"{payload.get('basic_meanings', '')}\n\n"
    text += f"**[IELTS Focus]**\n{payload.get('ielts_focus', '')}\n\n"
    text += f"**[Collocations]**\n{payload.get('collocations', '')}\n\n"
    text += f"**[Traps]**\n{payload.get('traps', '')}\n\n"
    text += f"**[Synonyms]**\n{payload.get('synonyms', '')}\n\n"
    text += f"**[Discrimination]**\n{payload.get('discrimination', '')}\n\n"
    text += f"**[Example Sentences]**\n{payload.get('example_sentences', '')}\n\n"
    text += f"**[Memory Aid]**\n{payload.get('memory_aid', '')}\n\n"
    return text


# ══════════════════════════════════════════════════════════════════════════════
# 测试库：运行日志
# ══════════════════════════════════════════════════════════════════════════════
def log_test_run(
    total_today:    int,
    sample_size:    int,
    words_sampled:  list,
    ai_call_count:  int,
    words_returned: int,
    success:        bool,
    error_msg:      str  = "",
    ai_results:     list = None,
) -> int:
    """将测试脚本的一次运行摘要写入测试库的 test_run_logs 表，返回新行 id。"""
    conn = _conn(TEST_DB_PATH)
    cur  = conn.cursor()
    _create_tables(cur)
    cur.execute("""
        INSERT INTO test_run_logs (
            total_today, sample_size, words_sampled,
            ai_call_count, words_returned, success, error_msg, ai_results_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        total_today,
        sample_size,
        json.dumps(words_sampled, ensure_ascii=False),
        ai_call_count,
        words_returned,
        1 if success else 0,
        error_msg or "",
        json.dumps(ai_results or [], ensure_ascii=False),
    ))
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id
