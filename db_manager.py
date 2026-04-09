import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "history.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS processed_words (
            voc_id TEXT PRIMARY KEY,
            spelling TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_processed(voc_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # 强制将 voc_id 判定为 string
    cur.execute("SELECT 1 FROM processed_words WHERE voc_id = ?", (str(voc_id),))
    result = cur.fetchone() is not None
    conn.close()
    return result

def mark_processed(voc_id: str, spelling: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO processed_words (voc_id, spelling) VALUES (?, ?)", (str(voc_id), spelling))
    conn.commit()
    conn.close()
