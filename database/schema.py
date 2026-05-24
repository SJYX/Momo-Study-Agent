
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
from .utils import _debug_log, _hub_db_fingerprint

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


def _kick_async_pull(path: str) -> None:
    """Spawn a daemon thread that does a one-shot pyturso pull on `path`.

    Used by init_db to prime cross-device freshness without blocking the
    SyncGate critical path. With Fix D, init_db's foreground connection
    opens pyturso with do_sync=False, do_pull=False (fastest), so any
    remote changes since last sync would otherwise wait until
    ProfileSyncCoordinator's first idle-sync cycle (up to ~30s).

    This thread issues one explicit pull right after schema is ready,
    typically landing remote-side updates ~1-2s after SyncGate dismisses.
    Failures are non-fatal — coordinator will pull again on its own timer.
    """
    def _runner() -> None:
        pull_start = time.time()
        try:
            ctx_local = connection._resolve_conn_context(path)
            from database.backends import HAS_PYTURSO

            if not (HAS_PYTURSO and ctx_local.get("url") and ctx_local.get("token")):
                return
            from database.backends import get_active_backend

            # do_pull=True with do_sync=False fires Step 3 in pyturso backend
            # (db.pull()), no push. We capture `path` in closure to avoid
            # races with _config.DB_PATH being switched between profiles.
            conn = get_active_backend().connect(
                path,
                ctx_local["url"],
                ctx_local["token"],
                do_sync=False,
                do_pull=True,
            )
            try:
                conn.close()
            except Exception:
                pass
            _debug_log(
                "[init_db] 后台 pull 完成",
                start_time=pull_start,
                module="database.schema",
            )
        except Exception as e:
            _debug_log(
                f"[init_db] 后台 pull 失败(不影响 UI): {e}",
                start_time=pull_start,
                level="WARNING",
                module="database.schema",
            )

    threading.Thread(target=_runner, name="init-async-pull", daemon=True).start()


def _init_db_impl(db_path: Optional[str] = None) -> None:
    from database.migrations import apply_migrations, _NeedCloudMigrations

    import config as _cfg
    path = db_path or _cfg.DB_PATH
    start_time = time.time()
    is_cloud = False  # defined here so it survives an early except below

    try:
        from database.connection import _resolve_conn_context
        ctx = _resolve_conn_context(path)
        is_cloud = bool(ctx.get("url") and ctx.get("token"))

        # Fix D: 在 pyturso 架构下,本地副本就是真实可用的数据库。init_db 只负责
        # 让 schema 在位,远端 push/pull 全部交给 ProfileSyncCoordinator(它有
        # max_delay + shutdown flush,不会积压)。do_sync=True 是 libsql 时代的
        # 残留 —— 在那里 sync 是离散事件,必须每次启动对齐;pyturso 不需要。
        if is_cloud:
            _debug_log("[init_db] 检测到云端配置,使用本地副本(后台 pull 异步触发)...", module="database.schema")
        else:
            _debug_log("[init_db] 获取本地连接...", module="database.schema")
        lc = connection._get_local_conn(path)

        # CREATE TABLE IF NOT EXISTS 是幂等的，直接执行。
        lcur = lc.cursor()
        _t_create = time.time()
        _debug_log("[init_db] 开始建表...", module="database.schema")
        _create_tables(lcur)
        lc.commit()
        lcur.close()
        _debug_log("[init_db] 建表完成", start_time=_t_create, level="INFO", module="database.schema")

        _debug_log("[init_db] 开始应用迁移...", module="database.schema")
        try:
            start_v, end_v = apply_migrations(lc, local_only=True)
        except _NeedCloudMigrations as e:
            # 有新迁移需要执行，需要连云
            _debug_log(f"[init_db] 检测到新迁移 v{e.current}→v{e.target}，使用云端连接...", module="database.schema")
            from database.backends import get_active_backend
            if ctx.get("url") and ctx.get("token"):
                cc = get_active_backend().connect(path, ctx["url"], ctx["token"], do_sync=False)
                try:
                    start_v, end_v = apply_migrations(cc)
                finally:
                    cc.close()
            else:
                _debug_log("[init_db] 无云端连接配置，跳过迁移", level="WARNING", module="database.schema")
                start_v = end_v = e.current
        if start_v != end_v:
            _debug_log(
                f"数据库迁移完成 v{start_v} → v{end_v}",
                module="database.schema",
            )
        else:
            _debug_log(f"[init_db] 迁移无需执行 (v{start_v})", module="database.schema")

        # 之前这里再调一次 get_active_backend().do_sync_on(lc) 做 push+pull+checkpoint,
        # 但上面 _get_conn(path, do_sync=True) 内部已经 push+pull 过(见
        # database/backends/_pyturso.py 的 Step 4)。中间只插了 CREATE TABLE IF NOT
        # EXISTS 与 apply_migrations(local_only=True) —— 暖库上都不产生新 WAL 帧。
        # 实测这一行多花 ~3s 纯 RTT 浪费,checkpoint 留给 wal_autocheckpoint=1000 PRAGMA
        # 与 ProfileSyncCoordinator 处理。

        # 如果是本地连接，我们关闭它；如果是单例写连接，则不关闭
        # 注意:_main_write_conn_singleton 是可变 module-level global,Phase 3 拆分后
        # 必须从 database.connection.singleton 子模块直读,不能走 __init__.py(快照行为)。
        from database.connection import singleton as conn_singleton
        if lc is not conn_singleton._main_write_conn_singleton:
            try:
                lc.close()
            except Exception:
                pass
        _debug_log("数据库初始化完成", start_time=start_time, module="database.schema")
    except Exception as e:
        _debug_log(f"数据库初始化失败: {e}", start_time=start_time, level="WARNING", module="database.schema")

    # Fix D: 启动后台 pull,把跨设备远端写在 ~1-2s 内拉到本地。SyncGate 不等。
    if is_cloud:
        _kick_async_pull(path)

    _debug_log("[init_db] 主库初始化完毕，开始 Hub 初始化...", module="database.schema")

    # Hub 初始化与主库 schema/数据完全独立(不同 DB 文件、不同连接、不同凭据),
    # 而且唯一消费者 /api/users/* 在 _DB_READY_EXEMPT_PREFIXES 白名单里,不受
    # SyncGate 控制。所以让 Hub 在后台 daemon 线程跑 —— init_db 直接返回,
    # _warmup_sync 早 ~1.5s 把 state 推到 db_init_done,SyncGate 早消失。
    # 如果第一个 /api/users/* 请求来时 Hub 还没建好,_get_hub_conn 内部有锁
    # 会自动等待 —— 走的不是 SyncGate 关键路径。
    def _hub_init_async() -> None:
        hub_start = time.time()
        try:
            hub_ok = init_users_hub_tables()
        except Exception as e:
            _debug_log(
                f"Hub 数据库初始化异常: {e}",
                start_time=hub_start,
                level="WARNING",
                module="database.schema",
            )
            return
        if hub_ok:
            _debug_log("Hub 数据库初始化完成", start_time=hub_start, module="database.schema")
        else:
            _debug_log(
                "Hub 数据库初始化失败（已记录原因）",
                start_time=hub_start,
                level="WARNING",
                module="database.schema",
            )

    threading.Thread(target=_hub_init_async, name="hub-init", daemon=True).start()


def init_users_hub_tables() -> bool:
    """Initialize central hub schema and perform idempotent upgrade checks."""
    try:
        hub_fp = _hub_db_fingerprint()
        if _hub_init_state_is_fresh(hub_fp):
            _debug_log("Hub 数据库已在有效缓存窗口内初始化，跳过重复 schema 校验", module="database.schema")
            return True

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
            _save_hub_init_state(
                {
                    "hub_fp": hub_fp,
                    "schema_version": _HUB_SCHEMA_VERSION,
                    "last_success_at": time.time(),
                    "last_checked_at": time.time(),
                }
            )
            hub_conn.commit()
            hub_conn.close()
            return True

        table_exists = _check_table_exists(cur, "users", "hub", cache_scope=hub_fp)
        if table_exists:
            _debug_log("中央 Hub users 表已存在，将执行增量 schema 校验", module="database.schema")

        _backend = get_active_backend()

        def _exec(sql: str, args: Optional[tuple] = None) -> None:
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

        hub_conn.commit()

        hub_conn.close()

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
