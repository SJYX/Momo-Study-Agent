
from __future__ import annotations
"""
database/schema.py: 数据库表结构、迁移与初始化逻辑。
"""
# -*- coding: utf-8 -*-
"""Database schema/migration and initialization layer."""

import json
import os
import threading
import time
from typing import Any, Dict, Optional

from config import DATA_DIR, DB_PATH

from . import connection
from .utils import _debug_log, _hash_fingerprint, _hub_db_fingerprint, _main_db_fingerprint, _normalize_turso_url

# Table existence cache (avoid repeated sqlite_master checks)
_table_exists_cache: Dict[str, bool] = {}

_HUB_INIT_STATE_TTL_SECONDS = int(os.getenv("HUB_INIT_STATE_TTL_SECONDS", "600"))
_HUB_SCHEMA_VERSION = os.getenv("HUB_SCHEMA_VERSION", "1")
_hub_init_state_cache: Dict[str, Any] = {"expire_at": 0.0, "state": None}


def _get_table_exists_cache() -> Dict[str, bool]:
    return _table_exists_cache


def _hub_init_state_path() -> str:
    marker_dir = os.path.join(DATA_DIR, "db_init_markers")
    os.makedirs(marker_dir, exist_ok=True)
    return os.path.join(marker_dir, "hub_init_state.json")


def _load_hub_init_state(force_refresh: bool = False) -> Optional[dict]:
    now = time.time()
    if not force_refresh and _hub_init_state_cache.get("state") and now < _hub_init_state_cache.get("expire_at", 0.0):
        return _hub_init_state_cache["state"]

    path = _hub_init_state_path()
    if not os.path.exists(path):
        _hub_init_state_cache["state"] = None
        _hub_init_state_cache["expire_at"] = now + _HUB_INIT_STATE_TTL_SECONDS
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if isinstance(state, dict):
            _hub_init_state_cache["state"] = state
            _hub_init_state_cache["expire_at"] = now + _HUB_INIT_STATE_TTL_SECONDS
            return state
    except Exception as e:
        _debug_log(f"读取 Hub 初始化状态失败: {e}", level="WARNING", module="database.schema")

    _hub_init_state_cache["state"] = None
    _hub_init_state_cache["expire_at"] = now + _HUB_INIT_STATE_TTL_SECONDS
    return None


def _save_hub_init_state(state: dict) -> None:
    path = _hub_init_state_path()
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        _hub_init_state_cache["state"] = state
        _hub_init_state_cache["expire_at"] = time.time() + _HUB_INIT_STATE_TTL_SECONDS
    except Exception as e:
        _debug_log(f"保存 Hub 初始化状态失败: {e}", level="WARNING", module="database.schema")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _hub_init_state_is_fresh(hub_fp: str) -> bool:
    state = _load_hub_init_state()
    if not state:
        return False

    if state.get("hub_fp") != hub_fp:
        return False
    if state.get("schema_version") != _HUB_SCHEMA_VERSION:
        return False

    last_success_at = float(state.get("last_success_at", 0.0) or 0.0)
    if not last_success_at:
        return False

    return (time.time() - last_success_at) <= _HUB_INIT_STATE_TTL_SECONDS


def _get_db_init_marker_path(db_type: str, db_fingerprint: Optional[str] = None) -> str:
    marker_dir = os.path.join(DATA_DIR, "db_init_markers")
    os.makedirs(marker_dir, exist_ok=True)
    if db_fingerprint:
        digest = _hash_fingerprint(db_fingerprint)
        return os.path.join(marker_dir, f"{db_type}_{digest}_initialized.flag")
    return os.path.join(marker_dir, f"{db_type}_initialized.flag")


def _is_db_initialized(db_type: str, db_fingerprint: Optional[str] = None) -> bool:
    return os.path.exists(_get_db_init_marker_path(db_type, db_fingerprint))


def _mark_db_initialized(db_type: str, db_fingerprint: Optional[str] = None) -> None:
    marker_path = _get_db_init_marker_path(db_type, db_fingerprint)
    with open(marker_path, "w", encoding="utf-8") as f:
        f.write(f"initialized at {time.time()}")


def _check_table_exists(cursor: Any, table_name: str, db_type: str = "main", cache_scope: Optional[str] = None) -> bool:
    scope = cache_scope or "default"
    cache_key = f"{db_type}_{scope}_{table_name}"

    if cache_key in _table_exists_cache:
        return _table_exists_cache[cache_key]

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    exists = cursor.fetchone() is not None
    _table_exists_cache[cache_key] = exists
    return exists


def _create_tables(cur: Any, skip_migrations: bool = False) -> None:
    """Create main DB tables (idempotent CREATE IF NOT EXISTS).

    Phase 6 起：列演进一律走 ``database/migrations/``（PRAGMA user_version + V001+）。
    本函数只负责"v0 setup"：建表骨架 + 索引。`skip_migrations` 名字保留兼容，但
    实际语义已变——已无内联 ALTER 逻辑。
    """
    cur.execute(
        "CREATE TABLE IF NOT EXISTS processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT, "
        "processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS ai_word_notes ("
        "voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, ielts_focus TEXT, collocations TEXT, "
        "traps TEXT, synonyms TEXT, discrimination TEXT, example_sentences TEXT, memory_aid TEXT, "
        "word_ratings TEXT, raw_full_text TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, "
        "batch_id TEXT, original_meanings TEXT, maimemo_context TEXT, content_origin TEXT, content_source_db TEXT, "
        "content_source_scope TEXT, it_level INTEGER DEFAULT 0, it_history TEXT, sync_status INTEGER DEFAULT 0, "
        "match_confidence REAL, match_reason TEXT, last_synced_content TEXT, is_customized INTEGER DEFAULT 0, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS ai_word_iterations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT NOT NULL, spelling TEXT, stage TEXT, it_level INTEGER, "
        "score REAL, justification TEXT, tags TEXT, refined_content TEXT, candidate_notes TEXT, raw_response TEXT, "
        "maimemo_context TEXT, batch_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY(voc_id) REFERENCES ai_word_notes(voc_id))"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS word_progress_history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT, familiarity_short REAL, familiarity_long REAL, "
        "review_count INTEGER, it_level INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    try:
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_progress_unique ON word_progress_history (voc_id, created_at, review_count)")
    except Exception:
        pass
    cur.execute(
        "CREATE TABLE IF NOT EXISTS ai_batches ("
        "batch_id TEXT PRIMARY KEY, request_id TEXT, ai_provider TEXT, model_name TEXT, prompt_version TEXT, "
        "batch_size INTEGER, total_latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, "
        "finish_reason TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur.execute(
        "CREATE TABLE IF NOT EXISTS test_run_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, total_count INTEGER, "
        "sample_count INTEGER, sample_words TEXT, ai_calls INTEGER, success_parsed INTEGER, is_dry_run BOOLEAN, "
        "error_msg TEXT, ai_results_json TEXT)"
    )


def _init_hub_schema(conn: Any) -> None:
    # 缓存短路：如果 Hub schema 已在最近初始化过，直接返回
    hub_fp = _hub_db_fingerprint()
    if _hub_init_state_is_fresh(hub_fp):
        _debug_log("Hub schema 已在缓存窗口内初始化，短路跳过重复校验", module="database.schema")
        return
    
    cur = conn.cursor()

    cur.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "user_id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, "
        "first_login_at TEXT, last_login_at TEXT, status TEXT DEFAULT 'active', role TEXT DEFAULT 'user', notes TEXT, updated_at TEXT)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS user_auth ("
        "user_id TEXT PRIMARY KEY, password_hash TEXT, auth_type TEXT DEFAULT 'local', failed_attempts INTEGER DEFAULT 0, "
        "last_failed_at TEXT, last_password_change TEXT, must_change_password INTEGER DEFAULT 0, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(user_id))"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS user_sync_history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, sync_type TEXT NOT NULL, source TEXT, target TEXT, "
        "record_count INTEGER, sync_status TEXT, error_msg TEXT, timestamp TEXT NOT NULL, "
        "FOREIGN KEY(user_id) REFERENCES users(user_id))"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS user_stats ("
        "user_id TEXT PRIMARY KEY, total_words_processed INTEGER DEFAULT 0, total_ai_calls INTEGER DEFAULT 0, "
        "total_prompt_tokens INTEGER DEFAULT 0, total_completion_tokens INTEGER DEFAULT 0, total_sync_count INTEGER DEFAULT 0, "
        "last_activity_at TEXT, updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(user_id))"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS user_sessions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, session_id TEXT UNIQUE NOT NULL, client_info TEXT NOT NULL, "
        "ip_address TEXT NOT NULL, login_at TEXT NOT NULL, logout_at TEXT, last_activity_at TEXT, session_status TEXT DEFAULT 'active', "
        "FOREIGN KEY(user_id) REFERENCES users(user_id))"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS admin_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, action_type TEXT NOT NULL, action_detail TEXT, admin_username TEXT, "
        "target_user_id TEXT, timestamp TEXT NOT NULL, result TEXT DEFAULT 'success')"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS user_credentials ("
        "user_id TEXT PRIMARY KEY, turso_db_url_enc TEXT, turso_auth_token_enc TEXT, momo_token_enc TEXT, "
        "mimo_api_key_enc TEXT, gemini_api_key_enc TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "FOREIGN KEY(user_id) REFERENCES users(user_id))"
    )
    conn.commit()


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize main db schema locally/cloud and ensure hub schema is ready.

    Phase 6 起：建表后调用 ``database.migrations.apply_migrations`` 推进 PRAGMA user_version
    到当前已知最高版本。第一次跑（v=0）会跑 V001 的幂等 ALTER + backfill。
    """
    return _init_db_impl(db_path)


def _init_db_impl(db_path: Optional[str] = None) -> None:
    from database.migrations import apply_migrations

    path = db_path or DB_PATH
    start_time = time.time()

    try:
        main_fp = _main_db_fingerprint(path)
        marker_exists = _is_db_initialized("main", main_fp)

        _debug_log("[init_db] 本地模式：获取连接...", module="database.schema")
        lc = connection._get_local_conn(path)

        if not marker_exists:
            lcur = lc.cursor()
            _t_create = time.time()
            _debug_log("[init_db] 开始建表...", module="database.schema")
            _create_tables(lcur)
            lc.commit()
            lcur.close()
            _mark_db_initialized("main", main_fp)
            _debug_log("[init_db] 建表成功", start_time=_t_create, level="INFO", module="database.schema")
        else:
            _debug_log("数据库已初始化（通过标记文件），跳过建表检查", module="database.schema")

        _debug_log("[init_db] 开始应用迁移...", module="database.schema")
        start_v, end_v = apply_migrations(lc, local_only=True)
        if start_v != end_v:
            _debug_log(
                f"数据库迁移完成 v{start_v} → v{end_v}",
                module="database.schema",
            )
        else:
            _debug_log(f"[init_db] 迁移无需执行 (v{start_v})", module="database.schema")

        lc.close()
        _debug_log("数据库初始化完成", start_time=start_time, module="database.schema")
    except Exception as e:
        _debug_log(f"数据库初始化失败: {e}", start_time=start_time, level="WARNING", module="database.schema")

    _debug_log("[init_db] 主库初始化完毕，开始 Hub 初始化...", module="database.schema")
    hub_start = time.time()
    hub_ok = init_users_hub_tables()
    if hub_ok:
        _debug_log("Hub 数据库初始化完成", start_time=hub_start, module="database.schema")
    else:
        _debug_log("Hub 数据库初始化失败（已记录原因）", start_time=hub_start, level="WARNING", module="database.schema")


def init_users_hub_tables() -> bool:
    """Initialize central hub schema and perform idempotent upgrade checks."""
    try:
        hub_fp = _hub_db_fingerprint()
        if _hub_init_state_is_fresh(hub_fp):
            _debug_log("Hub 数据库已在有效缓存窗口内初始化，跳过重复 schema 校验", module="database.schema")
            return True

        if _is_db_initialized("hub", hub_fp):
            _debug_log("Hub 数据库已初始化（通过旧标记文件），执行轻量 schema 校验", module="database.schema")

        _debug_log("[init_hub] 正在获取 Hub 连接...", module="database.schema")
        hub_conn = connection._get_hub_conn()
        _debug_log("[init_hub] Hub 连接获取成功", module="database.schema")

        from database.backends import get_active_backend
        cur = hub_conn.cursor()
        
        # 检查所有关键表是否都已存在，若都存在则短路返回
        required_tables = ["users", "user_api_keys", "user_sync_history", "user_stats", "user_sessions", "admin_logs", "user_credentials"]
        all_tables_exist = all(_check_table_exists(cur, table, "hub", cache_scope=hub_fp) for table in required_tables)
        
        if all_tables_exist:
            _debug_log("Hub 所有关键表已存在，跳过重复 CREATE TABLE 操作", module="database.schema")
            _mark_db_initialized("hub", hub_fp)
            _save_hub_init_state(
                {
                    "hub_fp": hub_fp,
                    "schema_version": _HUB_SCHEMA_VERSION,
                    "last_success_at": time.time(),
                    "last_checked_at": time.time(),
                }
            )
            if get_active_backend().should_close(hub_conn):
                hub_conn.close()
            return True

        table_exists = _check_table_exists(cur, "users", "hub", cache_scope=hub_fp)
        if table_exists:
            _debug_log("中央 Hub users 表已存在，将执行增量 schema 校验", module="database.schema")

        _backend = get_active_backend()

        def _exec(sql: str, args: Optional[tuple] = None) -> None:
            with _backend.op_lock_for(hub_conn):
                cur.execute(sql, args or ())

        _exec(
            "CREATE TABLE IF NOT EXISTS users ("
            "user_id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, "
            "first_login_at TEXT, last_login_at TEXT, status TEXT DEFAULT 'active', role TEXT DEFAULT 'user', notes TEXT, updated_at TEXT)"
        )
        try:
            _exec("ALTER TABLE users ADD COLUMN updated_at TEXT")
        except Exception:
            pass
        _exec(
            "CREATE TABLE IF NOT EXISTS user_api_keys ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, api_key_encrypted TEXT NOT NULL, api_key_name TEXT, "
            "created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT, FOREIGN KEY(user_id) REFERENCES users(user_id))"
        )
        _exec(
            "CREATE TABLE IF NOT EXISTS user_sync_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, sync_type TEXT NOT NULL, source TEXT, target TEXT, "
            "record_count INTEGER, sync_status TEXT, error_msg TEXT, timestamp TEXT NOT NULL, "
            "FOREIGN KEY(user_id) REFERENCES users(user_id))"
        )
        _exec(
            "CREATE TABLE IF NOT EXISTS user_stats ("
            "user_id TEXT PRIMARY KEY, total_words_processed INTEGER DEFAULT 0, total_ai_calls INTEGER DEFAULT 0, "
            "total_prompt_tokens INTEGER DEFAULT 0, total_completion_tokens INTEGER DEFAULT 0, total_sync_count INTEGER DEFAULT 0, "
            "last_activity_at TEXT, updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(user_id))"
        )
        _exec(
            "CREATE TABLE IF NOT EXISTS user_sessions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, session_id TEXT UNIQUE NOT NULL, client_info TEXT NOT NULL, "
            "ip_address TEXT NOT NULL, login_at TEXT NOT NULL, logout_at TEXT, last_activity_at TEXT, session_status TEXT DEFAULT 'active', "
            "FOREIGN KEY(user_id) REFERENCES users(user_id))"
        )
        _exec(
            "CREATE TABLE IF NOT EXISTS admin_logs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, action_type TEXT NOT NULL, action_detail TEXT, admin_username TEXT, "
            "target_user_id TEXT, timestamp TEXT NOT NULL, result TEXT DEFAULT 'success')"
        )
        _exec(
            "CREATE TABLE IF NOT EXISTS user_credentials ("
            "user_id TEXT PRIMARY KEY, turso_db_url_enc TEXT, turso_auth_token_enc TEXT, momo_token_enc TEXT, mimo_api_key_enc TEXT, "
            "gemini_api_key_enc TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(user_id))"
        )

        with _backend.op_lock_for(hub_conn):
            hub_conn.commit()

        if get_active_backend().should_close(hub_conn):
            hub_conn.close()

        _mark_db_initialized("hub", hub_fp)
        _save_hub_init_state(
            {
                "hub_fp": hub_fp,
                "schema_version": _HUB_SCHEMA_VERSION,
                "last_success_at": time.time(),
                "last_checked_at": time.time(),
                "mode": "cloud" if os.getenv("TURSO_HUB_DB_URL") else "local",
            }
        )
        _debug_log("中央 Hub 数据库表初始化完成", module="database.schema")
        return True
    except Exception as e:
        _debug_log(f"初始化中央 Hub 表失败: {e}", level="WARNING", module="database.schema")
        return False


# Register schema callbacks for local-rebuild flows in connection.py
connection.register_schema_initializers(
    main_initializer=lambda conn: _create_tables(conn.cursor(), skip_migrations=False),
    hub_initializer=_init_hub_schema,
)
