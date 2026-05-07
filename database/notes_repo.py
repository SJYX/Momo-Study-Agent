from __future__ import annotations
"""
database/notes_repo.py: ai_word_notes / ai_batches / ai_word_iterations 表的读写与同步状态。

边界：
- 仅处理 AI 笔记/批次/迭代历史相关表的 CRUD 与同步标记。
- 跨库查找在 community_lookup.py；进度表在 progress_repo.py；帧级同步在 sync_service.py。
- 日志 module 名保留 "database.momo_words"，避免破坏既有日志检索。
"""

import json
import sqlite3
import traceback
from typing import Any, Dict, List, Optional, Tuple

from database.session import with_read_session, DBSession
from ._repo_helpers import (
    dispatch_batch_write,
    dispatch_write,
    row_to_dict,
    row_value,
    rows_to_dicts,
)
from .dto import (
    AIBatchData,
    BatchNoteEntry,
    IterationPayload,
    NoteMetadata,
    NotePayload,
)
from .sql_constants import (
    AI_BATCH_INSERT_SQL,
    AI_WORD_ITERATION_INSERT_SQL,
    NOTE_UPSERT_SQL,
    UNSYNCED_NOTE_COLUMNS,
    UNSYNCED_NOTES_SELECT_SQL,
)
from .utils import (
    _debug_log,
    clean_for_maimemo,
    get_timestamp_with_tz,
)

_LOG_MOD = "database.momo_words"


def _classify_db_error(e: BaseException) -> str:
    """对常见数据库异常分类，返回结构化标签便于日志检索。"""
    if isinstance(e, sqlite3.IntegrityError):
        return "integrity"
    if isinstance(e, sqlite3.OperationalError):
        return "operational"
    if isinstance(e, sqlite3.DatabaseError):
        return "db"
    if isinstance(e, (TypeError, ValueError)):
        return "input"
    if isinstance(e, json.JSONDecodeError):
        return "json"
    return "unexpected"


def _log_repo_failure(func_name: str, e: BaseException, *, level: str = "WARNING") -> None:
    """统一的 repo 写入失败日志：带异常类型、分类标签，ERROR 级附 traceback。"""
    cat = _classify_db_error(e)
    prefix = f"{func_name} 失败 [{cat}/{type(e).__name__}]: {e}"
    if level == "ERROR" or cat == "unexpected":
        _debug_log(f"{prefix}\n{traceback.format_exc()}", level=level, module=_LOG_MOD)
    else:
        _debug_log(prefix, level=level, module=_LOG_MOD)


@with_read_session(default_return={})
def get_sync_status_in_batch(voc_ids: List[str], db_path: Optional[str] = None, session: DBSession = None) -> Dict[str, int]:
    """批量获取单词的同步状态 (0: 未同步, 1: 已同步)"""
    if not voc_ids:
        return {}

    vs = [str(v) for v in voc_ids]
    ph = ",".join(["?"] * len(vs))

    rows = session.fetchall(f"SELECT voc_id, sync_status FROM ai_word_notes WHERE voc_id IN ({ph})", vs)

    return {
        str(row_value(r, 0, "voc_id")): int(row_value(r, 1, "sync_status") or 0)
        for r in rows
    }


def _clean_payload_field(payload: Dict[str, Any], field: str) -> str:
    return clean_for_maimemo(payload.get(field, ""))


def build_note_upsert_args(
    voc_id: str,
    payload: NotePayload,
    metadata: Optional[NoteMetadata] = None,
    *,
    sync_status: Optional[int] = None,
) -> Tuple[Any, ...]:
    """Assemble args tuple for NOTE_UPSERT_SQL.

    sync_status=None → derive from content_origin (0 for ai_generated, 1 otherwise).
    """
    md: Dict[str, Any] = dict(metadata or {})
    raw_candidate = {k: v for k, v in payload.items() if k != "raw_full_text"}
    raw_full_text = payload.get("raw_full_text") or json.dumps(raw_candidate, ensure_ascii=False)
    m_ctx = json.dumps(md.get("maimemo_context", {}), ensure_ascii=False) if md.get("maimemo_context") else None
    original_meanings = md.get("original_meanings") or payload.get("original_meanings")
    content_origin = md.get("content_origin") or payload.get("content_origin") or "ai_generated"
    content_source_db = md.get("content_source_db") or payload.get("content_source_db")
    content_source_scope = md.get("content_source_scope") or payload.get("content_source_scope")

    if sync_status is None:
        sync_status = 0 if content_origin == "ai_generated" else 1

    return (
        str(voc_id),
        payload.get("spelling", ""),
        _clean_payload_field(payload, "basic_meanings"),
        _clean_payload_field(payload, "ielts_focus"),
        _clean_payload_field(payload, "collocations"),
        _clean_payload_field(payload, "traps"),
        _clean_payload_field(payload, "synonyms"),
        _clean_payload_field(payload, "discrimination"),
        _clean_payload_field(payload, "example_sentences"),
        _clean_payload_field(payload, "memory_aid"),
        _clean_payload_field(payload, "word_ratings"),
        raw_full_text,
        payload.get("prompt_tokens", 0),
        payload.get("completion_tokens", 0),
        payload.get("total_tokens", 0),
        md.get("batch_id"),
        original_meanings,
        m_ctx,
        content_origin,
        content_source_db,
        content_source_scope,
        int(sync_status),
        get_timestamp_with_tz(),
    )


def save_ai_word_note(
    voc_id: str,
    payload: NotePayload,
    db_path: Optional[str] = None,
    metadata: Optional[NoteMetadata] = None,
    conn: Any = None,
) -> bool:
    args = build_note_upsert_args(voc_id, payload, metadata, sync_status=0)
    try:
        return dispatch_write(NOTE_UPSERT_SQL, args, db_path=db_path, conn=conn)
    except (sqlite3.DatabaseError, OSError) as e:
        _log_repo_failure("save_ai_word_note", e, level="ERROR")
        return False
    except Exception as e:  # noqa: BLE001 - libsql/queue 抛出的非标准异常需兜底
        _log_repo_failure("save_ai_word_note", e, level="ERROR")
        return False


def save_ai_word_notes_batch(
    notes_data: List[BatchNoteEntry],
    db_path: Optional[str] = None,
    conn: Any = None,
) -> bool:
    if not notes_data:
        return True

    try:
        batch_args = [
            build_note_upsert_args(
                data.get("voc_id"),
                data.get("payload", {}) or {},
                data.get("metadata", {}) or {},
            )
            for data in notes_data
        ]
    except (TypeError, ValueError) as e:
        _log_repo_failure("save_ai_word_notes_batch[build]", e)
        return False

    try:
        if not dispatch_batch_write(
            NOTE_UPSERT_SQL,
            batch_args,
            db_path=db_path,
            conn=conn,
            queue_full_log=lambda m: _debug_log(f"批量保存 AI 笔记 {m}", level="WARNING", module=_LOG_MOD),
            queue_full_message="入队失败: 写队列已满",
        ):
            return False

        _debug_log(f"批量保存 AI 笔记完成：{len(notes_data)} 个单词（本地数据库）", module=_LOG_MOD)
        return True
    except (sqlite3.DatabaseError, OSError) as e:
        _log_repo_failure("save_ai_word_notes_batch", e)
        return False
    except Exception as e:  # noqa: BLE001 - 兜底未知 libsql/队列异常
        _log_repo_failure("save_ai_word_notes_batch", e)
        return False


@with_read_session(default_return=[])
def get_unsynced_notes(db_path: Optional[str] = None, session: DBSession = None) -> List[Dict[str, Any]]:
    rows = session.fetchall(UNSYNCED_NOTES_SELECT_SQL)
    result = rows_to_dicts(rows, fallback_columns=UNSYNCED_NOTE_COLUMNS)
    _debug_log(f"获取未同步笔记完成: {len(result)} 条 (仅 ai_generated)", module=_LOG_MOD)
    return result


@with_read_session(default_return=None)
def get_word_note(voc_id: str, db_path: Optional[str] = None, session: DBSession = None) -> Optional[Dict[str, Any]]:
    return row_to_dict(session.fetchone("SELECT * FROM ai_word_notes WHERE voc_id = ?", (str(voc_id),)))


def get_local_word_note(voc_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Read word note from local/read path; fallback behavior handled by read layer."""
    return get_word_note(voc_id, db_path=db_path)


def set_note_sync_status(voc_id: str, sync_status: int, db_path: Optional[str] = None) -> bool:
    try:
        return dispatch_write(
            "UPDATE ai_word_notes SET sync_status = ?, updated_at = ? WHERE voc_id = ?",
            (int(sync_status), get_timestamp_with_tz(), str(voc_id)),
            db_path=db_path,
        )
    except (sqlite3.DatabaseError, OSError, ValueError) as e:
        _log_repo_failure("set_note_sync_status", e)
        return False
    except Exception as e:  # noqa: BLE001
        _log_repo_failure("set_note_sync_status", e)
        return False


def mark_note_synced(voc_id: str, db_path: Optional[str] = None) -> bool:
    return set_note_sync_status(voc_id, 1, db_path=db_path)


def mark_note_sync_conflict(voc_id: str, db_path: Optional[str] = None) -> bool:
    return set_note_sync_status(voc_id, 2, db_path=db_path)


def save_ai_batch(batch_data: AIBatchData, db_path: Optional[str] = None) -> bool:
    args = (
        batch_data.get("batch_id"),
        batch_data.get("request_id"),
        batch_data.get("ai_provider"),
        batch_data.get("model_name"),
        batch_data.get("prompt_version"),
        batch_data.get("batch_size", 1),
        batch_data.get("total_latency_ms", 0),
        batch_data.get("prompt_tokens", 0),
        batch_data.get("completion_tokens", 0),
        batch_data.get("total_tokens", 0),
        batch_data.get("finish_reason"),
        get_timestamp_with_tz(),
    )
    return dispatch_write(AI_BATCH_INSERT_SQL, args, db_path=db_path)


def save_ai_word_iteration(
    voc_id: str,
    payload: IterationPayload,
    db_path: Optional[str] = None,
    metadata: Optional[NoteMetadata] = None,
    conn: Any = None,
) -> bool:
    if not voc_id:
        return False
    try:
        data: Dict[str, Any] = dict(payload or {})
        meta: Dict[str, Any] = dict(metadata or {})
        batch_id = meta.get("batch_id")
        m_ctx = json.dumps(meta.get("maimemo_context", {}), ensure_ascii=False) if meta.get("maimemo_context") else None
        tags = data.get("tags")
        tags_json = json.dumps(tags, ensure_ascii=False) if tags is not None else None
        raw_response = data.get("raw_response") or data.get("raw_full_text") or json.dumps(data, ensure_ascii=False)

        args = (
            str(voc_id),
            data.get("spelling"),
            data.get("stage"),
            data.get("it_level"),
            data.get("score"),
            data.get("justification"),
            tags_json,
            data.get("refined_content"),
            data.get("candidate_notes"),
            raw_response,
            m_ctx,
            batch_id,
        )
        return dispatch_write(AI_WORD_ITERATION_INSERT_SQL, args, db_path=db_path, conn=conn)
    except (sqlite3.DatabaseError, OSError) as e:
        _log_repo_failure("save_ai_word_iteration", e)
        return False
    except (TypeError, ValueError) as e:
        _log_repo_failure("save_ai_word_iteration[input]", e)
        return False
    except Exception as e:  # noqa: BLE001
        _log_repo_failure("save_ai_word_iteration", e)
        return False


def update_ai_word_note_iteration_state(
    voc_id: str,
    level: int,
    it_history_json: str,
    memory_aid: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    try:
        if memory_aid is not None:
            sql = "UPDATE ai_word_notes SET it_level = ?, it_history = ?, memory_aid = ?, updated_at = ? WHERE voc_id = ?"
            args = (int(level), it_history_json, memory_aid, get_timestamp_with_tz(), str(voc_id))
        else:
            sql = "UPDATE ai_word_notes SET it_level = ?, it_history = ?, updated_at = ? WHERE voc_id = ?"
            args = (int(level), it_history_json, get_timestamp_with_tz(), str(voc_id))

        return dispatch_write(sql, args, db_path=db_path)
    except (sqlite3.DatabaseError, OSError, ValueError) as e:
        _log_repo_failure("update_ai_word_note_iteration_state", e)
        return False
    except Exception as e:  # noqa: BLE001
        _log_repo_failure("update_ai_word_note_iteration_state", e)
        return False


__all__ = [
    "NOTE_UPSERT_SQL",
    "build_note_upsert_args",
    "save_ai_word_note",
    "save_ai_word_notes_batch",
    "get_unsynced_notes",
    "get_word_note",
    "get_local_word_note",
    "get_sync_status_in_batch",
    "set_note_sync_status",
    "mark_note_synced",
    "mark_note_sync_conflict",
    "save_ai_batch",
    "save_ai_word_iteration",
    "update_ai_word_note_iteration_state",
]
