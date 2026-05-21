from __future__ import annotations
"""
database/momo_words.py: 兼容门面与少量杂项工具。

主体职责已按主题拆分到：
- notes_repo.py        AI 笔记/批次/迭代历史 CRUD 与同步标记
- progress_repo.py     processed_words / word_progress_history
- community_lookup.py  跨本地历史 + 当前库 + 云端副本批量查找
- sync_service.py      Embedded Replica 帧级同步管线

本文件保留：
1) 跨域工具：system_config KV、Prompt 文件归档、本地库初始化、测试日志/测试库写入。
2) 兼容 re-export：`from database.momo_words import X` 与 `from .momo_words import *`
   在重构后必须与拆分前完全等价。`database/legacy.py` 通过 `from .momo_words import *`
   依赖该承诺。
"""

import hashlib
import json
import os
import shutil
from typing import Any, Optional, Tuple

import config as _config
from config import DATA_DIR

from . import connection
from database.session import with_read_session, DBSession
from .schema import _create_tables
from ._repo_helpers import dispatch_write
from .utils import _debug_log, get_timestamp_with_tz

# Re-export 所有职责模块的公开 API（保持原 __all__ 完全一致）。
from .notes_repo import (  # noqa: F401
    NOTE_UPSERT_SQL,
    build_note_upsert_args,
    save_ai_word_note,
    save_ai_word_notes_batch,
    get_unsynced_notes,
    get_word_note,
    get_local_word_note,
    get_word_notes_in_batch,
    get_sync_status_in_batch,
    set_note_sync_status,
    mark_note_synced,
    mark_note_sync_conflict,
    update_sync_status_batch,
    save_ai_batch,
    save_ai_word_iteration,
    update_ai_word_note_iteration_state,
    atomic_save_iteration_and_update_note,
)
from .progress_repo import (  # noqa: F401
    get_processed_ids_in_batch,
    get_progress_tracked_ids_in_batch,
    is_processed,
    mark_processed,
    mark_processed_batch,
    log_progress_snapshots,
    get_latest_progress,
)
from .community_lookup import (  # noqa: F401
    find_words_in_community_batch,
    find_word_in_community,
)
from .sync_service import sync_databases, sync_hub_databases  # noqa: F401


# ---------------------------------------------------------------------------
# system_config KV（跨域工具，调用方既包括笔记也包括测试/启动）
# ---------------------------------------------------------------------------

def set_config(k: str, v: str, db: Optional[str] = None) -> bool:
    return dispatch_write(
        "INSERT OR REPLACE INTO system_config (key, value, updated_at) VALUES (?, ?, ?)",
        (k, v, get_timestamp_with_tz()),
        db_path=db,
        queue_full_log=lambda m: _debug_log(f"set_config {m}", level="WARNING", module="database.momo_words"),
    )


@with_read_session(default_return=None)
def _fetch_one_scalar(sql: str, params: Tuple = (), db_path: Optional[str] = None, session: DBSession = None) -> Any:
    row = session.fetchone(sql, params)
    if not row:
        return None
    return row[0]


def get_config(k: str, db: Optional[str] = None) -> Optional[str]:
    return _fetch_one_scalar("SELECT value FROM system_config WHERE key = ?", (k,), db_path=(db or _config.DB_PATH))


# ---------------------------------------------------------------------------
# Prompt 文件归档工具
# ---------------------------------------------------------------------------

def get_file_hash(file_path: str) -> str:
    if not os.path.exists(file_path):
        return "00000000"
    with open(file_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()[:8]


def archive_prompt_file(source_path: str, prompt_hash: str, prompt_type: str = "main") -> None:
    archive_dir = os.path.join(DATA_DIR, "prompts")
    os.makedirs(archive_dir, exist_ok=True)
    target_path = os.path.join(archive_dir, f"prompt_{prompt_type}_{prompt_hash}.md")
    if not os.path.exists(target_path):
        shutil.copy2(source_path, target_path)


# ---------------------------------------------------------------------------
# 本地库初始化
# ---------------------------------------------------------------------------

def initialize_local_database_file(db_path: str) -> bool:
    try:
        conn = connection._get_local_conn(db_path)
        cur = conn.cursor()
        _create_tables(cur)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        _debug_log(f"initialize_local_database_file 失败: {e}", level="WARNING", module="database.momo_words")
        return False


# ---------------------------------------------------------------------------
# 测试运行日志 + 测试库写入
# ---------------------------------------------------------------------------

def save_test_word_note(voc_id: str, payload):
    save_ai_word_note(voc_id, payload, db_path=_config.TEST_DB_PATH)


def log_test_run(
    t=None,
    s=None,
    w=None,
    a=None,
    sp=None,
    d=True,
    e="",
    res=None,
    **kwargs,
):
    """Persist test run logs, compatible with legacy positional/keyword style."""
    if t is None:
        t = kwargs.pop("total_count", None)
    if s is None:
        s = kwargs.pop("sample_count", None)
    if w is None:
        w = kwargs.pop("words_sampled", None)
    if a is None:
        a = kwargs.pop("ai_calls", None)
    if sp is None:
        sp = kwargs.pop("success_parsed", None)

    if "is_dry_run" in kwargs:
        d = kwargs.pop("is_dry_run")
    if "error_msg" in kwargs:
        e = kwargs.pop("error_msg")
    if "ai_results" in kwargs:
        res = kwargs.pop("ai_results")

    if t is None or s is None or w is None or a is None or sp is None:
        raise TypeError("log_test_run 缺少必要参数")

    words_sampled = ",".join(str(item) for item in w) if isinstance(w, (list, tuple)) else str(w)

    c = connection._get_conn(_config.TEST_DB_PATH)
    cur = c.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS test_run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_count INTEGER,
            sample_count INTEGER,
            sample_words TEXT,
            ai_calls INTEGER,
            success_parsed INTEGER,
            is_dry_run BOOLEAN,
            error_msg TEXT,
            ai_results_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    aj = json.dumps(res, ensure_ascii=False) if res else ""
    cur.execute(
        "INSERT INTO test_run_logs (total_count, sample_count, sample_words, ai_calls, success_parsed, is_dry_run, error_msg, ai_results_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (t, s, words_sampled, a, sp, d, e, aj),
    )
    c.commit()
    rid = cur.lastrowid
    from database.backends import get_active_backend
    if get_active_backend().should_close(c):
        c.close()
    return rid


__all__ = [
    "get_processed_ids_in_batch",
    "get_progress_tracked_ids_in_batch",
    "is_processed",
    "mark_processed",
    "mark_processed_batch",
    "log_progress_snapshots",
    "save_ai_word_note",
    "save_ai_word_notes_batch",
    "save_ai_word_iteration",
    "update_ai_word_note_iteration_state",
    "save_ai_batch",
    "get_unsynced_notes",
    "get_word_note",
    "get_local_word_note",
    "get_word_notes_in_batch",
    "set_note_sync_status",
    "mark_note_synced",
    "mark_note_sync_conflict",
    "update_sync_status_batch",
    "atomic_save_iteration_and_update_note",
    "find_words_in_community_batch",
    "find_word_in_community",
    "get_latest_progress",
    "set_config",
    "get_config",
    "initialize_local_database_file",
    "log_test_run",
    "get_file_hash",
    "archive_prompt_file",
    "save_test_word_note",
    "sync_databases",
    "sync_hub_databases",
]
