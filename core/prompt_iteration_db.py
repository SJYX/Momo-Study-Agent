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
    """初始化迭代数据库表结构（含幂等性检查）。"""
    conn = _get_iteration_conn()
    try:
        cur = conn.cursor()

        # 1. Prompt 版本记录
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

        # 2. 评估轮次概览
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
                gen_batch_size INTEGER DEFAULT 5,
                audit_batch_size INTEGER DEFAULT 5,
                created_at TEXT NOT NULL,
                FOREIGN KEY(version_hash) REFERENCES prompt_versions(version_hash)
            )
        ''')

        # 字段兼容性升级
        for col in ["gen_batch_size", "audit_batch_size"]:
            try:
                cur.execute(f"ALTER TABLE evaluation_rounds ADD COLUMN {col} INTEGER DEFAULT 5")
            except:
                pass

        # 3. 模块级细分分数
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

        # 4. 优化决策记录
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
                FOREIGN KEY (round_id) REFERENCES evaluation_rounds(id)
            )
        ''')

        # 5. 中间解析结果缓存 (用于跳过重复生成)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS generation_cache (
                version_hash TEXT PRIMARY KEY,
                test_words_json TEXT,
                outputs_json TEXT,
                model_name TEXT,
                batch_size INTEGER DEFAULT 5,
                created_at TEXT NOT NULL
            )
        ''')
        
        # 字段兼容性升级
        try:
            cur.execute("ALTER TABLE generation_cache ADD COLUMN batch_size INTEGER DEFAULT 5")
        except:
            pass

        conn.commit()
    finally:
        conn.close()


def save_generation_cache(version_hash: str, test_words: list, outputs: list, model_name: str, batch_size: int = 5):
    """缓存中间生成结果。"""
    from core.db_manager import get_timestamp_with_tz
    conn = _get_iteration_conn()
    try:
        cur = conn.cursor()
        cur.execute('''
            INSERT OR REPLACE INTO generation_cache 
            (version_hash, test_words_json, outputs_json, model_name, batch_size, created_at) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (version_hash, json.dumps(test_words), json.dumps(outputs), model_name, batch_size, get_timestamp_with_tz()))
        conn.commit()
    finally:
        conn.close()


def get_generation_cache(version_hash: str) -> Optional[dict]:
    """获取缓存的中间生成结果（包含 24 小时效期检查）。"""
    from datetime import datetime, timedelta
    from core.db_manager import get_timestamp_with_tz
    
    conn = _get_iteration_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT outputs_json, test_words_json, created_at, batch_size FROM generation_cache WHERE version_hash = ?', (version_hash,))
        row = cur.fetchone()
        if row:
            outputs_json, words_json, created_at, batch_size = row
            # 检查是否过期 (24小时)
            try:
                # 简单解析 ISO 格式 (假设格式一致)
                created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                now_dt = datetime.fromisoformat(get_timestamp_with_tz().replace('Z', '+00:00'))
                if now_dt - created_dt > timedelta(hours=24):
                    return None 
            except:
                pass # 解析失败则保守起见不返回缓存
                
            return {
                "outputs": json.loads(outputs_json),
                "test_words": json.loads(words_json),
                "batch_size": batch_size
            }
        return None
    finally:
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
    gen_batch_size: int = 5,
    audit_batch_size: int = 5
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
         total_prompt_tokens, total_completion_tokens, gen_batch_size, audit_batch_size, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        round_number, version_hash, ai_provider, model_name,
        json.dumps(test_words, ensure_ascii=False),
        avg_score, prompt_tokens, completion_tokens,
        gen_batch_size, audit_batch_size,
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
