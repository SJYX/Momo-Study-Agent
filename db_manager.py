import sqlite3
import os
import json
import re
from config import DB_PATH, TEST_DB_PATH

# ──────────────────────────────────────────────────────────────────────────────
# 文本清洗工具 (Text Sanitizer for MaiMemo)
# ──────────────────────────────────────────────────────────────────────────────

def clean_for_maimemo(text: str) -> str:
    """
    将 Markdown 格式的字符串转为墨墨背单词兼容的纯文本。
    规则：
      - 保留换行符 \n（墨墨支持，关键！）
      - **bold** / __bold__  → 去掉标记，保留文字
      - *italic* / _italic_  → 去掉标记，保留文字
      - `code`               → 去掉反引号，保留文字
      - 行首 Markdown 列表 '- ' 或 '* ' → 替换为 '• '
      - 行首 '### ' / '## ' / '# '     → 去掉 '#'，保留标题文字
    """
    if not text or not isinstance(text, str):
        return text

    # 1. 处理行首标题 (### foo → foo)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # 2. 行首无序列表符号 (- item 或 * item → • item)
    text = re.sub(r'^[\-\*]\s+', '• ', text, flags=re.MULTILINE)

    # 3. 去掉加粗/斜体标记，保留内容（顺序重要：先处理 ** 再处理 *）
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text, flags=re.DOTALL)  # ***bold+italic***
    text = re.sub(r'\*\*(.+?)\*\*',     r'\1', text, flags=re.DOTALL)  # **bold**
    text = re.sub(r'__(.+?)__',         r'\1', text, flags=re.DOTALL)  # __bold__
    text = re.sub(r'\*(.+?)\*',         r'\1', text, flags=re.DOTALL)  # *italic*
    text = re.sub(r'_(.+?)_',           r'\1', text, flags=re.DOTALL)  # _italic_

    # 4. 去掉行内代码反引号
    text = re.sub(r'`(.+?)`', r'\1', text)

    # 5. 收尾：去掉首尾多余空白，但保留内部换行节奏
    text = text.strip()

    return text

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
            word_ratings TEXT,
            raw_full_text TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 无缝升表（兼容已经生成的本地 SQLite 环境）
    for col, col_def in [
        ("prompt_tokens", "INTEGER DEFAULT 0"),
        ("completion_tokens", "INTEGER DEFAULT 0"),
        ("total_tokens", "INTEGER DEFAULT 0"),
        ("word_ratings", "TEXT"),
    ]:
        try:
            cur.execute(f"ALTER TABLE ai_word_notes ADD COLUMN {col} {col_def}")
        except sqlite3.OperationalError:
            pass  # 列已存在

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
    # raw_full_text 保留原始 Markdown，供本地预览/评估报告使用
    raw_full_text = payload.get("raw_full_text") or _build_raw_markdown(payload)

    # 其余字段入库前清洗为墨墨兼容的纯文本（保留换行，去除 Markdown 标记）
    def _c(field: str) -> str:
        return clean_for_maimemo(payload.get(field, ""))

    cur.execute("""
        INSERT OR REPLACE INTO ai_word_notes (
            voc_id, spelling, basic_meanings, ielts_focus, collocations,
            traps, synonyms, discrimination, example_sentences, memory_aid,
            word_ratings, raw_full_text, prompt_tokens, completion_tokens, total_tokens
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(voc_id), spell,
        _c("basic_meanings"),
        _c("ielts_focus"),
        _c("collocations"),
        _c("traps"),
        _c("synonyms"),
        _c("discrimination"),
        _c("example_sentences"),
        _c("memory_aid"),
        _c("word_ratings"),
        raw_full_text,
        payload.get("prompt_tokens", 0),
        payload.get("completion_tokens", 0),
        payload.get("total_tokens", 0)
    ))
    conn.commit()
    conn.close()

def _build_raw_markdown(payload: dict) -> str:
    """按标准格式拼接完整的 Markdown 预览。"""
    spell = payload.get("spelling", "")
    text = f"### {spell}\n\n{payload.get('basic_meanings', '')}\n\n"
    for field in ["ielts_focus", "collocations", "traps", "synonyms", "discrimination", "example_sentences", "memory_aid", "word_ratings"]:
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
