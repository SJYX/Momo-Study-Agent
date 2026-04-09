import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "history.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # 清理掉过去只有两个字段的废库，使用全新的 10+ 维度知识图谱表
    cur.execute("DROP TABLE IF EXISTS processed_words")
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
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_processed(voc_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM ai_word_notes WHERE voc_id = ?", (str(voc_id),))
    result = cur.fetchone() is not None
    conn.close()
    return result

def mark_processed(voc_id: str, payload: dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
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
        payload.get("raw_full_text", "")
    ))
    conn.commit()
    conn.close()
