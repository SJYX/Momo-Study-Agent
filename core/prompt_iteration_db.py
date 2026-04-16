# -*- coding: utf-8 -*-
"""Prompt 迭代优化数据库管理模块

独立于用户生产数据库，使用 data/prompt_iterations.db 存储所有迭代追溯数据。
"""
import sqlite3
import os
import json
import hashlib
from typing import Optional, Dict, List, Any
from config import PROMPT_ITERATION_DB


def _get_iteration_conn() -> sqlite3.Connection:
    """获取 prompt_iterations.db 连接。"""
    os.makedirs(os.path.dirname(os.path.abspath(PROMPT_ITERATION_DB)), exist_ok=True)
    conn = sqlite3.connect(PROMPT_ITERATION_DB, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_iteration_db():
    """初始化迭代数据库表结构。"""
    conn = _get_iteration_conn()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS prompt_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_hash TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            parent_hash TEXT,
            source TEXT DEFAULT 'optimizer',
            created_at TEXT NOT NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS evaluation_rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_number INTEGER NOT NULL,
            version_hash TEXT NOT NULL,
            ai_provider TEXT,
            model_name TEXT,
            test_words TEXT,
            avg_score REAL,
            total_prompt_tokens INTEGER DEFAULT 0,
            total_completion_tokens INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(version_hash) REFERENCES prompt_versions(version_hash)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS module_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id INTEGER NOT NULL,
            test_word TEXT NOT NULL,
            module_name TEXT NOT NULL,
            score REAL NOT NULL,
            feedback TEXT,
            fix_suggestion TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(round_id) REFERENCES evaluation_rounds(id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS optimization_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id INTEGER NOT NULL,
            target_modules TEXT NOT NULL,
            frozen_modules TEXT NOT NULL,
            input_version_hash TEXT NOT NULL,
            output_version_hash TEXT NOT NULL,
            optimizer_reasoning TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(round_id) REFERENCES evaluation_rounds(id)
        )
    ''')

    conn.commit()
    conn.close()


def compute_version_hash(content: str) -> str:
    """根据 Prompt 内容计算版本哈希（SHA256 前 12 位）。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def save_prompt_version(content: str, parent_hash: str = None, source: str = "init") -> str:
    """保存一个 Prompt 版本快照，返回 version_hash。"""
    from core.db_manager import get_timestamp_with_tz

    version_hash = compute_version_hash(content)
    conn = _get_iteration_conn()
    cur = conn.cursor()

    # 如果已存在相同 hash，跳过
    cur.execute("SELECT version_hash FROM prompt_versions WHERE version_hash = ?", (version_hash,))
    if cur.fetchone():
        conn.close()
        return version_hash

    cur.execute('''
        INSERT INTO prompt_versions (version_hash, content, parent_hash, source, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (version_hash, content, parent_hash, source, get_timestamp_with_tz()))

    conn.commit()
    conn.close()
    return version_hash


def save_evaluation_round(
    version_hash: str,
    ai_provider: str,
    model_name: str,
    test_words: list,
    avg_score: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> int:
    """保存一轮评估记录，返回 round_id。"""
    from core.db_manager import get_timestamp_with_tz

    conn = _get_iteration_conn()
    cur = conn.cursor()

    # 计算下一个 round_number
    cur.execute("SELECT COALESCE(MAX(round_number), 0) + 1 FROM evaluation_rounds")
    round_number = cur.fetchone()[0]

    cur.execute('''
        INSERT INTO evaluation_rounds
        (round_number, version_hash, ai_provider, model_name, test_words, avg_score,
         total_prompt_tokens, total_completion_tokens, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        round_number, version_hash, ai_provider, model_name,
        json.dumps(test_words, ensure_ascii=False),
        avg_score, prompt_tokens, completion_tokens,
        get_timestamp_with_tz()
    ))

    round_id = cur.lastrowid
    conn.commit()
    conn.close()
    return round_id


def save_module_scores(round_id: int, scores: List[Dict[str, Any]]):
    """批量保存模块级评分。

    Args:
        round_id: 评估轮次 ID
        scores: [{"field": "...", "word": "...", "score": X, "feedback": "...", "fix": "..."}]
    """
    from core.db_manager import get_timestamp_with_tz

    conn = _get_iteration_conn()
    cur = conn.cursor()
    ts = get_timestamp_with_tz()

    for s in scores:
        cur.execute('''
            INSERT INTO module_scores
            (round_id, test_word, module_name, score, feedback, fix_suggestion, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            round_id, s.get("word", ""), s.get("field", ""),
            s.get("score", 0), s.get("feedback", ""), s.get("fix", ""), ts
        ))

    conn.commit()
    conn.close()


def save_optimization_action(
    round_id: int,
    target_modules: list,
    frozen_modules: list,
    input_version_hash: str,
    output_version_hash: str,
    optimizer_reasoning: str = "",
):
    """保存一次优化决策记录。"""
    from core.db_manager import get_timestamp_with_tz

    conn = _get_iteration_conn()
    cur = conn.cursor()

    cur.execute('''
        INSERT INTO optimization_actions
        (round_id, target_modules, frozen_modules, input_version_hash,
         output_version_hash, optimizer_reasoning, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        round_id,
        json.dumps(target_modules, ensure_ascii=False),
        json.dumps(frozen_modules, ensure_ascii=False),
        input_version_hash, output_version_hash,
        optimizer_reasoning, get_timestamp_with_tz()
    ))

    conn.commit()
    conn.close()


def get_latest_round_number() -> int:
    """获取最新的轮次号。"""
    conn = _get_iteration_conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(round_number), 0) FROM evaluation_rounds")
    result = cur.fetchone()[0]
    conn.close()
    return result


def get_module_score_trends() -> List[Dict]:
    """获取模块分数趋势数据。"""
    conn = _get_iteration_conn()
    cur = conn.cursor()
    cur.execute('''
        SELECT er.round_number, ms.module_name, AVG(ms.score) as avg_score
        FROM module_scores ms
        JOIN evaluation_rounds er ON ms.round_id = er.id
        GROUP BY er.round_number, ms.module_name
        ORDER BY er.round_number, ms.module_name
    ''')

    rows = cur.fetchall()
    conn.close()

    results = []
    for row in rows:
        results.append({
            "round": row[0],
            "module": row[1],
            "avg_score": round(row[2], 2)
        })
    return results


def get_all_rounds_summary() -> List[Dict]:
    """获取所有评估轮次的概要信息。"""
    conn = _get_iteration_conn()
    cur = conn.cursor()
    cur.execute('''
        SELECT id, round_number, version_hash, ai_provider, model_name,
               avg_score, created_at
        FROM evaluation_rounds
        ORDER BY round_number DESC
    ''')

    rows = cur.fetchall()
    conn.close()

    return [{
        "id": r[0], "round": r[1], "version_hash": r[2],
        "ai_provider": r[3], "model_name": r[4],
        "avg_score": r[5], "created_at": r[6]
    } for r in rows]


def get_prompt_version_content(version_hash: str) -> Optional[str]:
    """获取指定版本的 Prompt 内容。"""
    conn = _get_iteration_conn()
    cur = conn.cursor()
    cur.execute("SELECT content FROM prompt_versions WHERE version_hash = ?", (version_hash,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def get_round_frozen_modules(round_id: int) -> list:
    """获取某轮被冻结的模块列表。"""
    conn = _get_iteration_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT frozen_modules FROM optimization_actions WHERE round_id = ?",
        (round_id,)
    )
    row = cur.fetchone()
    conn.close()
    if row and row[0]:
        return json.loads(row[0])
    return []
