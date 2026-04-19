# -*- coding: utf-8 -*-
"""Main DB business logic for momo word notes/progress/sync wrappers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import DATA_DIR, DB_PATH, TEST_DB_PATH, TURSO_HUB_AUTH_TOKEN, TURSO_HUB_DB_URL

from . import connection
from .schema import _create_tables, _init_hub_schema
from .utils import (
    _backup_broken_database_file,
    _collect_cloud_lookup_targets,
    _debug_log,
    _debug_log_throttled,
    _get_cloud_lookup_replica_path,
    _hash_fingerprint,
    _is_sqlite_data_corruption_error,
    clean_for_maimemo,
    get_timestamp_with_tz,
)

try:
    import libsql
except Exception:
    libsql = None


def get_processed_ids_in_batch(voc_ids: list, db_path: str = None) -> set:
    if not voc_ids:
        return set()

    c = None
    try:
        started = time.time()
        c = connection._get_read_conn(db_path or DB_PATH)
        conn_lock = connection._get_singleton_conn_op_lock(c)
        vs = [str(v) for v in voc_ids]
        ph = ",".join(["?"] * len(vs))

        if conn_lock is not None:
            with conn_lock:
                cur = c.cursor()
                cur.execute(f"SELECT voc_id FROM processed_words WHERE voc_id IN ({ph})", vs)
                rows = cur.fetchall()
                c.commit()
        else:
            cur = c.cursor()
            cur.execute(f"SELECT voc_id FROM processed_words WHERE voc_id IN ({ph})", vs)
            rows = cur.fetchall()
            c.commit()

        result = {str(r[0] if isinstance(r, (tuple, list)) else r["voc_id"]) for r in rows}
        _debug_log(f"批量查询 ({len(voc_ids)} 词)", start_time=started, module="database.momo_words")
        return result
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "get_processed_ids_batch_corruption",
                f"get_processed_ids_in_batch 数据损坏异常: {e}",
                level="WARNING",
                module="database.momo_words",
            )
            return set()
        _debug_log(f"get_processed_ids_in_batch 异常: {e}", level="WARNING", module="database.momo_words")
        return set()
    finally:
        try:
            if c is not None and not connection._is_main_write_singleton_conn(c):
                c.close()
        except Exception:
            pass


def get_progress_tracked_ids_in_batch(voc_ids: list, db_path: str = None) -> set:
    if not voc_ids:
        return set()

    c = None
    try:
        c = connection._get_read_conn(db_path or DB_PATH)
        conn_lock = connection._get_singleton_conn_op_lock(c)
        vs = [str(v) for v in voc_ids]
        ph = ",".join(["?"] * len(vs))

        if conn_lock is not None:
            with conn_lock:
                cur = c.cursor()
                cur.execute(f"SELECT DISTINCT voc_id FROM word_progress_history WHERE voc_id IN ({ph})", vs)
                rows = cur.fetchall()
                c.commit()
        else:
            cur = c.cursor()
            cur.execute(f"SELECT DISTINCT voc_id FROM word_progress_history WHERE voc_id IN ({ph})", vs)
            rows = cur.fetchall()
            c.commit()

        return {str(r[0] if isinstance(r, (tuple, list)) else r["voc_id"]) for r in rows}
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "get_progress_tracked_ids_batch_corruption",
                f"get_progress_tracked_ids_in_batch 数据损坏异常: {e}",
                level="WARNING",
                module="database.momo_words",
            )
            return set()
        _debug_log(f"get_progress_tracked_ids_in_batch 异常: {e}", level="WARNING", module="database.momo_words")
        return set()
    finally:
        try:
            if c is not None and not connection._is_main_write_singleton_conn(c):
                c.close()
        except Exception:
            pass


def is_processed(voc_id: str, db_path: str = None) -> bool:
    c = None
    try:
        c = connection._get_read_conn(db_path or DB_PATH)
        conn_lock = connection._get_singleton_conn_op_lock(c)

        if conn_lock is not None:
            with conn_lock:
                cur = c.cursor()
                cur.execute("SELECT 1 FROM processed_words WHERE voc_id = ?", (str(voc_id),))
                res = cur.fetchone() is not None
                c.commit()
        else:
            cur = c.cursor()
            cur.execute("SELECT 1 FROM processed_words WHERE voc_id = ?", (str(voc_id),))
            res = cur.fetchone() is not None
            c.commit()

        return res
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "is_processed_corruption",
                f"is_processed 数据损坏异常: {e}",
                level="WARNING",
                module="database.momo_words",
            )
            return False
        _debug_log(f"is_processed 异常: {e}", level="WARNING", module="database.momo_words")
        return False
    finally:
        try:
            if c is not None and not connection._is_main_write_singleton_conn(c):
                c.close()
        except Exception:
            pass


def mark_processed(voc_id: str, spelling: str, db_path: str = None, conn: Any = None) -> bool:
    try:
        sql = "INSERT OR REPLACE INTO processed_words (voc_id, spelling, updated_at) VALUES (?, ?, ?)"
        args = (str(voc_id), spelling, get_timestamp_with_tz())
        if connection._should_use_local_only_connection(db_path, conn):
            connection._execute_write_sql_sync(sql, args, db_path=db_path, conn=conn)
            return True
        if not connection._queue_write_operation(sql, args, op_type="insert_or_replace"):
            _debug_log("mark_processed 入队失败: 写队列已满", level="WARNING", module="database.momo_words")
            return False
        return True
    except Exception as e:
        _debug_log(f"mark_processed 写入失败: {e}", level="WARNING", module="database.momo_words")
        return False


def mark_processed_batch(items: List[Tuple[str, str]], db_path: str = None) -> bool:
    if not items:
        return True

    try:
        sql = "INSERT OR REPLACE INTO processed_words (voc_id, spelling, updated_at) VALUES (?, ?, ?)"
        ts = get_timestamp_with_tz()
        args_list = [(str(voc_id), spelling, ts) for voc_id, spelling in items]
        if connection._should_use_local_only_connection(db_path):
            connection._execute_batch_write_sql_sync(sql, args_list, db_path=db_path)
            return True
        if not connection._queue_batch_write_operation(sql, args_list):
            _debug_log("mark_processed_batch 入队失败: 写队列已满", level="WARNING", module="database.momo_words")
            return False
        return True
    except Exception as e:
        _debug_log(f"mark_processed_batch 失败: {e}", level="WARNING", module="database.momo_words")
        return False


def log_progress_snapshots(words: List[dict], db_path: str = None) -> int:
    if not words:
        return 0

    started = time.time()
    c = None

    def _query_progress_data(c):
        vids = [str(w["voc_id"]) for w in words]
        ph = ",".join(["?"] * len(vids))
        cur = c.cursor()
        cur.execute(f"SELECT voc_id, it_level FROM ai_word_notes WHERE voc_id IN ({ph})", vids)
        itm = {str(r[0]): r[1] for r in cur.fetchall()}
        cur.execute(
            f"SELECT voc_id, familiarity_short, review_count FROM word_progress_history WHERE voc_id IN ({ph}) ORDER BY created_at DESC",
            vids,
        )
        lh = {}
        for r in cur.fetchall():
            v = str(r[0])
            if v not in lh:
                lh[v] = (r[1], r[2])
        return itm, lh, vids

    try:
        c = connection._get_read_conn(db_path or DB_PATH)
        conn_lock = connection._get_singleton_conn_op_lock(c)

        if conn_lock is not None:
            with conn_lock:
                itm, lh, vids = _query_progress_data(c)
                c.commit()
        else:
            itm, lh, vids = _query_progress_data(c)
            c.commit()
    except Exception as e:
        _debug_log(f"log_progress_snapshots 读取异常: {e}", level="WARNING", module="database.momo_words")
        return 0
    finally:
        try:
            if c is not None and not connection._is_main_write_singleton_conn(c):
                c.close()
        except Exception:
            pass

    ins = []
    for w in words:
        v = str(w["voc_id"])
        nf = w.get("short_term_familiarity", 0) or w.get("voc_familiarity", 0)
        nr = w.get("review_count", 0)
        l = lh.get(v)
        if not l or abs(l[0] - float(nf)) > 0.01 or l[1] != int(nr):
            ins.append((v, nf, w.get("long_term_familiarity", 0), nr, itm.get(v, 0)))

    if ins:
        sql = "INSERT INTO word_progress_history (voc_id, familiarity_short, familiarity_long, review_count, it_level) VALUES (?, ?, ?, ?, ?)"
        if connection._should_use_local_only_connection(db_path):
            connection._execute_batch_write_sql_sync(sql, ins, db_path=db_path)
            _debug_log(f"进度同步 ({len(ins)} 条)", start_time=started, module="database.momo_words")
            return len(ins)
        if not connection._queue_batch_write_operation(sql, ins):
            _debug_log("log_progress_snapshots 入队失败: 写队列已满", level="WARNING", module="database.momo_words")
            return 0

    _debug_log(f"进度同步 ({len(ins)} 条)", start_time=started, module="database.momo_words")
    return len(ins)


def _clean_payload_field(payload: Dict[str, Any], field: str) -> str:
    return clean_for_maimemo(payload.get(field, ""))


def save_ai_word_note(voc_id: str, payload: dict, db_path: str = None, metadata: dict = None, conn: Any = None) -> bool:
    s = payload.get("spelling", "")
    raw_candidate = {k: v for k, v in payload.items() if k != "raw_full_text"}
    t = payload.get("raw_full_text") or json.dumps(raw_candidate, ensure_ascii=False)
    m_ctx = json.dumps(metadata.get("maimemo_context", {}), ensure_ascii=False) if metadata and metadata.get("maimemo_context") else None
    original_meanings = metadata.get("original_meanings") if metadata else None
    if not original_meanings:
        original_meanings = payload.get("original_meanings")
    content_origin = (metadata.get("content_origin") if metadata else None) or payload.get("content_origin") or "ai_generated"
    content_source_db = (metadata.get("content_source_db") if metadata else None) or payload.get("content_source_db")
    content_source_scope = (metadata.get("content_source_scope") if metadata else None) or payload.get("content_source_scope")

    args = (
        str(voc_id),
        s,
        _clean_payload_field(payload, "basic_meanings"),
        _clean_payload_field(payload, "ielts_focus"),
        _clean_payload_field(payload, "collocations"),
        _clean_payload_field(payload, "traps"),
        _clean_payload_field(payload, "synonyms"),
        _clean_payload_field(payload, "discrimination"),
        _clean_payload_field(payload, "example_sentences"),
        _clean_payload_field(payload, "memory_aid"),
        _clean_payload_field(payload, "word_ratings"),
        t,
        payload.get("prompt_tokens", 0),
        payload.get("completion_tokens", 0),
        payload.get("total_tokens", 0),
        metadata.get("batch_id") if metadata else None,
        original_meanings,
        m_ctx,
        content_origin,
        content_source_db,
        content_source_scope,
        0,
        get_timestamp_with_tz(),
    )
    sql = (
        "INSERT OR REPLACE INTO ai_word_notes (voc_id, spelling, basic_meanings, ielts_focus, collocations, traps, synonyms, discrimination, "
        "example_sentences, memory_aid, word_ratings, raw_full_text, prompt_tokens, completion_tokens, total_tokens, batch_id, original_meanings, "
        "maimemo_context, content_origin, content_source_db, content_source_scope, sync_status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    try:
        if connection._should_use_local_only_connection(db_path, conn):
            connection._execute_write_sql_sync(sql, args, db_path=db_path, conn=conn)
            return True
        return connection._queue_write_operation(sql, args, op_type="insert_or_replace")
    except Exception as e:
        _debug_log(f"save_ai_word_note 入队失败: {e}", level="ERROR", module="database.momo_words")
        return False


def save_ai_word_notes_batch(notes_data: List[Dict[str, Any]], db_path: str = None, conn: Any = None) -> bool:
    if not notes_data:
        return True

    try:
        sql = (
            "INSERT OR REPLACE INTO ai_word_notes (voc_id, spelling, basic_meanings, ielts_focus, collocations, traps, synonyms, discrimination, "
            "example_sentences, memory_aid, word_ratings, raw_full_text, prompt_tokens, completion_tokens, total_tokens, batch_id, original_meanings, "
            "maimemo_context, content_origin, content_source_db, content_source_scope, sync_status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        batch_args = []
        for data in notes_data:
            voc_id = data.get("voc_id")
            payload = data.get("payload", {})
            metadata = data.get("metadata", {})

            s = payload.get("spelling", "")
            raw_candidate = {k: v for k, v in payload.items() if k != "raw_full_text"}
            t = payload.get("raw_full_text") or json.dumps(raw_candidate, ensure_ascii=False)
            m_ctx = json.dumps(metadata.get("maimemo_context", {}), ensure_ascii=False) if metadata and metadata.get("maimemo_context") else None

            original_meanings = metadata.get("original_meanings") if metadata else None
            if not original_meanings:
                original_meanings = payload.get("original_meanings")
            content_origin = (metadata.get("content_origin") if metadata else None) or payload.get("content_origin") or "ai_generated"
            content_source_db = (metadata.get("content_source_db") if metadata else None) or payload.get("content_source_db")
            content_source_scope = (metadata.get("content_source_scope") if metadata else None) or payload.get("content_source_scope")
            initial_sync_status = 0 if content_origin == "ai_generated" else 1

            args = (
                str(voc_id),
                s,
                _clean_payload_field(payload, "basic_meanings"),
                _clean_payload_field(payload, "ielts_focus"),
                _clean_payload_field(payload, "collocations"),
                _clean_payload_field(payload, "traps"),
                _clean_payload_field(payload, "synonyms"),
                _clean_payload_field(payload, "discrimination"),
                _clean_payload_field(payload, "example_sentences"),
                _clean_payload_field(payload, "memory_aid"),
                _clean_payload_field(payload, "word_ratings"),
                t,
                payload.get("prompt_tokens", 0),
                payload.get("completion_tokens", 0),
                payload.get("total_tokens", 0),
                metadata.get("batch_id") if metadata else None,
                original_meanings,
                m_ctx,
                content_origin,
                content_source_db,
                content_source_scope,
                initial_sync_status,
                get_timestamp_with_tz(),
            )
            batch_args.append(args)

        if connection._should_use_local_only_connection(db_path, conn):
            connection._execute_batch_write_sql_sync(sql, batch_args, db_path=db_path, conn=conn)
        else:
            if not connection._queue_batch_write_operation(sql, batch_args):
                _debug_log("批量保存 AI 笔记入队失败: 写队列已满", level="WARNING", module="database.momo_words")
                return False

        _debug_log(f"批量保存 AI 笔记完成：{len(notes_data)} 个单词（本地数据库）", module="database.momo_words")
        return True
    except Exception as e:
        _debug_log(f"批量保存 AI 笔记失败: {e}", level="WARNING", module="database.momo_words")
        return False


def get_unsynced_notes(db_path: str = None, _recovery_attempted: bool = False) -> list:
    unsynced_sql = (
        "SELECT voc_id, spelling, basic_meanings, ielts_focus, collocations, "
        "traps, synonyms, discrimination, example_sentences, memory_aid, "
        "word_ratings, raw_full_text, batch_id, original_meanings, "
        "maimemo_context, it_level, updated_at, content_origin "
        "FROM ai_word_notes "
        "WHERE sync_status = 0 "
        "AND (content_origin IS NULL OR content_origin = 'ai_generated') "
        "ORDER BY updated_at ASC"
    )

    c = None
    try:
        path = db_path or DB_PATH
        c = connection._get_read_conn(path)
        conn_lock = connection._get_singleton_conn_op_lock(c)

        if conn_lock is not None:
            with conn_lock:
                cur = c.cursor()
                cur.execute(unsynced_sql)
                rows = cur.fetchall()
                c.commit()
        else:
            cur = c.cursor()
            cur.execute(unsynced_sql)
            rows = cur.fetchall()
            c.commit()

        result = [connection._row_to_dict(cur, row) for row in rows]
        _debug_log(f"获取未同步笔记完成: {len(result)} 条 (仅 ai_generated)", module="database.momo_words")
        return result
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            path = db_path or DB_PATH

            if not _recovery_attempted:
                connection._release_db_file_handles_for_recovery(path)
                backup_path = _backup_broken_database_file(path, "检测到本地数据库损坏，已备份本地数据库")
                if not backup_path:
                    _debug_log("损坏库备份未完成（源文件可能被占用），继续尝试云端/本地重建", level="WARNING", module="database.momo_words")

                try:
                    ctx = connection._resolve_conn_context(path)
                    if connection.HAS_LIBSQL and ctx.get("url") and ctx.get("token"):
                        repair_conn = connection._get_conn(path, allow_local_fallback=False, do_sync=True)
                        try:
                            if not connection._is_main_write_singleton_conn(repair_conn):
                                repair_conn.close()
                        except Exception:
                            pass
                        return get_unsynced_notes(path, _recovery_attempted=True)

                    local_conn = connection._get_local_conn(path)
                    try:
                        _create_tables(local_conn.cursor())
                        local_conn.commit()
                    finally:
                        try:
                            local_conn.close()
                        except Exception:
                            pass
                    return get_unsynced_notes(path, _recovery_attempted=True)
                except Exception as recovery_error:
                    _debug_log(f"获取未同步笔记自动恢复失败: {recovery_error}", level="WARNING", module="database.momo_words")

            if _recovery_attempted:
                try:
                    ctx = connection._resolve_conn_context(path)
                    if connection.HAS_LIBSQL and ctx.get("url") and ctx.get("token") and libsql is not None:
                        recovery_dir = os.path.join(DATA_DIR, "profiles", ".recovery_replicas")
                        os.makedirs(recovery_dir, exist_ok=True)
                        recovery_fp = _hash_fingerprint((ctx.get("url") or "").strip())
                        recovery_path = os.path.join(recovery_dir, f"unsynced_{recovery_fp}_{int(time.time())}.db")
                        cloud_conn = libsql.connect(
                            recovery_path,
                            sync_url=str(ctx["url"]).replace("libsql://", "https://"),
                            auth_token=ctx["token"],
                        )
                        if hasattr(cloud_conn, "sync"):
                            cloud_conn.sync()
                        cloud_cur = cloud_conn.cursor()
                        cloud_cur.execute(unsynced_sql)
                        cloud_rows = cloud_cur.fetchall()
                        cloud_conn.close()
                        return [connection._row_to_dict(cloud_cur, row) for row in cloud_rows]
                except Exception as cloud_fallback_error:
                    _debug_log(f"独立云端副本兜底读取未同步队列失败: {cloud_fallback_error}", level="WARNING", module="database.momo_words")

            _debug_log_throttled(
                "get_unsynced_notes_corruption",
                f"获取未同步笔记失败（本地数据损坏）: {e}，返回空列表",
                level="WARNING",
                module="database.momo_words",
            )
            return []
        _debug_log(f"获取未同步笔记异常: {e}", level="WARNING", module="database.momo_words")
        return []
    finally:
        try:
            if c is not None and not connection._is_main_write_singleton_conn(c):
                c.close()
        except Exception:
            pass


def get_word_note(voc_id: str, db_path: str = None) -> Optional[dict]:
    target_path = db_path or DB_PATH

    c = None
    try:
        c = connection._get_read_conn(target_path)
        conn_lock = connection._get_singleton_conn_op_lock(c)

        if conn_lock is not None:
            with conn_lock:
                cur = c.cursor()
                cur.execute("SELECT * FROM ai_word_notes WHERE voc_id = ?", (str(voc_id),))
                r = cur.fetchone()
                c.commit()
        else:
            cur = c.cursor()
            cur.execute("SELECT * FROM ai_word_notes WHERE voc_id = ?", (str(voc_id),))
            r = cur.fetchone()
            c.commit()

        return connection._row_to_dict(cur, r) if r else None
    except Exception as read_error:
        if not _is_sqlite_data_corruption_error(read_error):
            raise
        _debug_log_throttled(
            key=f"word-note-read-corruption:{os.path.abspath(target_path)}",
            msg=f"检测到读路径数据异常，尝试云端主连接兜底读取: {read_error}",
            interval_seconds=15.0,
            level="WARNING",
            module="database.momo_words",
        )

        try:
            fc = connection._get_read_conn(target_path, allow_local_fallback=False)
            conn_lock = connection._get_singleton_conn_op_lock(fc)

            if conn_lock is not None:
                with conn_lock:
                    fallback_cur = fc.cursor()
                    fallback_cur.execute("SELECT * FROM ai_word_notes WHERE voc_id = ?", (str(voc_id),))
                    fallback_row = fallback_cur.fetchone()
                    fc.commit()
            else:
                fallback_cur = fc.cursor()
                fallback_cur.execute("SELECT * FROM ai_word_notes WHERE voc_id = ?", (str(voc_id),))
                fallback_row = fallback_cur.fetchone()
                fc.commit()

            return connection._row_to_dict(fallback_cur, fallback_row) if fallback_row else None
        except Exception as fallback_error:
            _debug_log_throttled(
                key=f"word-note-read-fallback-failed:{os.path.abspath(target_path)}",
                msg=f"云端主连接兜底读取失败: {fallback_error}",
                interval_seconds=15.0,
                level="WARNING",
                module="database.momo_words",
            )
            return None
    finally:
        try:
            if c is not None and not connection._is_main_write_singleton_conn(c):
                c.close()
        except Exception:
            pass


def _matches_ai_generation_context(note_row: Dict[str, Any], ai_provider: Optional[str] = None, prompt_version: Optional[str] = None) -> bool:
    current_provider = (ai_provider or "").strip().lower()
    current_prompt_version = (prompt_version or "").strip()

    batch_provider = str(note_row.get("batch_ai_provider") or note_row.get("ai_provider") or "").strip().lower()
    batch_prompt_version = str(note_row.get("batch_prompt_version") or note_row.get("prompt_version") or "").strip()

    if not current_provider:
        return True
    if current_provider and batch_provider != current_provider:
        return False
    if current_prompt_version and batch_prompt_version != current_prompt_version:
        return False
    return bool(batch_provider and batch_prompt_version)


def find_words_in_community_batch(
    voc_ids: List[str],
    skip_cloud: bool = False,
    ai_provider: str = None,
    prompt_version: str = None,
) -> Dict[str, Tuple[dict, str]]:
    if not voc_ids:
        return {}

    result: Dict[str, Tuple[dict, str]] = {}
    remaining_ids = [str(vid) for vid in voc_ids]

    if remaining_ids:
        cdb = os.path.basename(DB_PATH)
        dr = os.path.dirname(DB_PATH)
        dfs = sorted(
            [f for f in os.listdir(dr) if (f.startswith("history_") or f.startswith("history-")) and f.endswith(".db")],
            key=lambda x: os.path.getmtime(os.path.join(dr, x)),
            reverse=True,
        )

        for df in dfs:
            if df == cdb:
                continue
            try:
                c = connection._get_local_conn(os.path.join(dr, df))
                cur = c.cursor()
                placeholders = ",".join(["?"] * len(remaining_ids))
                cur.execute(
                    f"""
                    SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                    FROM ai_word_notes n
                    LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                    WHERE n.voc_id IN ({placeholders})
                    """,
                    remaining_ids,
                )
                rows = cur.fetchall()
                c.commit()
                c.close()

                if rows:
                    for row in rows:
                        note_dict = connection._row_to_dict(cur, row)
                        voc_id = note_dict.get("voc_id")
                        if voc_id and voc_id not in result and _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                            result[voc_id] = (note_dict, df)
                            if voc_id in remaining_ids:
                                remaining_ids.remove(voc_id)

                if not remaining_ids:
                    break
            except Exception:
                continue

    if remaining_ids:
        c = None
        try:
            c = connection._get_read_conn(DB_PATH)
            conn_lock = connection._get_singleton_conn_op_lock(c)
            placeholders = ",".join(["?"] * len(remaining_ids))

            if conn_lock is not None:
                with conn_lock:
                    cur = c.cursor()
                    cur.execute(
                        f"""
                        SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                        FROM ai_word_notes n
                        LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                        WHERE n.voc_id IN ({placeholders})
                        """,
                        remaining_ids,
                    )
                    rows = cur.fetchall()
                    c.commit()
            else:
                cur = c.cursor()
                cur.execute(
                    f"""
                    SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                    FROM ai_word_notes n
                    LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                    WHERE n.voc_id IN ({placeholders})
                    """,
                    remaining_ids,
                )
                rows = cur.fetchall()
                c.commit()

            if rows:
                for row in rows:
                    note_dict = connection._row_to_dict(cur, row)
                    voc_id = note_dict.get("voc_id")
                    if voc_id and voc_id not in result and _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                        result[voc_id] = (note_dict, "当前数据库")
                        if voc_id in remaining_ids:
                            remaining_ids.remove(voc_id)
        except Exception:
            pass
        finally:
            try:
                if c is not None and not connection._is_main_write_singleton_conn(c):
                    c.close()
            except Exception:
                pass

    if not skip_cloud and connection.HAS_LIBSQL and remaining_ids and libsql is not None:
        cloud_targets = _collect_cloud_lookup_targets()
        for cloud_url, _cloud_token, source_label in cloud_targets:
            if not remaining_ids:
                break
            cloud_conn = None
            try:
                lookup_path = _get_cloud_lookup_replica_path(cloud_url)
                if not os.path.exists(lookup_path):
                    continue

                cloud_conn = libsql.connect(lookup_path)
                cloud_cur = cloud_conn.cursor()
                placeholders = ",".join(["?"] * len(remaining_ids))
                cloud_cur.execute(
                    f"""
                    SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                    FROM ai_word_notes n
                    LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                    WHERE n.voc_id IN ({placeholders})
                    """,
                    remaining_ids,
                )
                rows = cloud_cur.fetchall()

                if rows:
                    columns = [col[0] for col in cloud_cur.description]
                    for row in rows:
                        note_dict = dict(zip(columns, row))
                        voc_id = note_dict.get("voc_id")
                        if voc_id and voc_id not in result and _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                            result[voc_id] = (note_dict, source_label)
                    remaining_ids = [vid for vid in remaining_ids if vid not in result]
            except Exception as e:
                _debug_log(f"{source_label} 批量查询失败: {e}", module="database.momo_words")
            finally:
                if cloud_conn:
                    try:
                        cloud_conn.close()
                    except Exception:
                        pass

    return result


def get_latest_progress(voc_id: str, db_path: str = None):
    c = None
    try:
        c = connection._get_read_conn(db_path or DB_PATH)
        conn_lock = connection._get_singleton_conn_op_lock(c)

        if conn_lock is not None:
            with conn_lock:
                cur = c.cursor()
                cur.execute("SELECT familiarity_short, review_count FROM word_progress_history WHERE voc_id = ? ORDER BY created_at DESC LIMIT 1", (str(voc_id),))
                r = cur.fetchone()
                c.commit()
        else:
            cur = c.cursor()
            cur.execute("SELECT familiarity_short, review_count FROM word_progress_history WHERE voc_id = ? ORDER BY created_at DESC LIMIT 1", (str(voc_id),))
            r = cur.fetchone()
            c.commit()

        return connection._row_to_dict(cur, r) if r else None
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "get_latest_progress_corruption",
                f"get_latest_progress 数据损坏异常: {e}",
                level="WARNING",
                module="database.momo_words",
            )
            return None
        _debug_log(f"get_latest_progress 异常: {e}", level="WARNING", module="database.momo_words")
        return None
    finally:
        try:
            if c is not None and not connection._is_main_write_singleton_conn(c):
                c.close()
        except Exception:
            pass


def set_config(k, v, db=None) -> bool:
    sql = "INSERT OR REPLACE INTO system_config (key, value, updated_at) VALUES (?, ?, ?)"
    args = (k, v, get_timestamp_with_tz())
    if connection._should_use_local_only_connection(db):
        connection._execute_write_sql_sync(sql, args, db_path=db)
        return True
    if not connection._queue_write_operation(sql, args, op_type="insert_or_replace"):
        _debug_log("set_config 入队失败: 写队列已满", level="WARNING", module="database.momo_words")
        return False
    return True


def _fetch_one_scalar(sql: str, params: tuple = (), db_path: str = None):
    c = None
    try:
        c = connection._get_read_conn(db_path or DB_PATH)
        conn_lock = connection._get_singleton_conn_op_lock(c)

        if conn_lock is not None:
            with conn_lock:
                cur = c.cursor()
                cur.execute(sql, params)
                row = cur.fetchone()
                c.commit()
        else:
            cur = c.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            c.commit()

        if not row:
            return None
        return row[0]
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "fetch_one_scalar_corruption",
                f"_fetch_one_scalar 数据损坏异常: {e}",
                level="WARNING",
                module="database.momo_words",
            )
            return None
        _debug_log(f"_fetch_one_scalar 异常: {e}", level="WARNING", module="database.momo_words")
        return None
    finally:
        try:
            if c is not None and not connection._is_main_write_singleton_conn(c):
                c.close()
        except Exception:
            pass


def get_config(k, db=None):
    return _fetch_one_scalar("SELECT value FROM system_config WHERE key = ?", (k,), db_path=(db or DB_PATH))


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


def save_test_word_note(voc_id: str, payload: dict) -> None:
    save_ai_word_note(voc_id, payload, db_path=TEST_DB_PATH)


def _emit_sync_progress(progress_callback, stage: str, current: int, total: int, message: str, **extra):
    if not progress_callback:
        return
    payload = {"stage": stage, "current": current, "total": total, "message": message}
    if extra:
        payload.update(extra)
    try:
        progress_callback(payload)
    except Exception:
        pass


def _is_cloud_connection_unavailable_error(error: Exception) -> bool:
    msg = str(error or "").lower()
    return (
        "强制云端模式已启用" in str(error or "")
        or "cannot connect to the cloud" in msg
        or "unable to connect" in msg
        or "failed to connect" in msg
        or ("cloud" in msg and "unavailable" in msg)
    )


def sync_databases(
    db_path: str = None,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    path = db_path or DB_PATH
    stats: Dict[str, Any] = {"upload": 0, "download": 0, "status": "ok", "reason": ""}

    if not os.getenv("TURSO_DB_URL") or not os.getenv("TURSO_AUTH_TOKEN") or not connection.HAS_LIBSQL:
        stats["status"] = "skipped"
        if not os.getenv("TURSO_DB_URL") or not os.getenv("TURSO_AUTH_TOKEN"):
            stats["reason"] = "missing-cloud-credentials"
        else:
            stats["reason"] = "libsql-unavailable"
        _emit_sync_progress(progress_callback, "skipped", 0, 0, f"跳过同步: {stats['reason']}", status="skipped", reason=stats["reason"])
        return stats

    sync_start = time.time()
    try:
        _emit_sync_progress(progress_callback, "connect", 1, 2, "连接 Embedded Replica 数据库")
        try:
            if connection._is_main_db_path(path):
                conn = connection._get_main_write_conn_singleton(do_sync=False)
            else:
                conn = connection._get_conn(path, do_sync=False)
        except Exception as conn_error:
            if _is_cloud_connection_unavailable_error(conn_error):
                stats["status"] = "skipped"
                stats["reason"] = "cloud-unavailable"
                _emit_sync_progress(progress_callback, "skipped", 0, 0, f"跳过同步: {conn_error}", status="skipped", reason=stats["reason"])
                return stats
            raise

        if not hasattr(conn, "sync"):
            stats["status"] = "skipped"
            stats["reason"] = "local-only-connection"
            _emit_sync_progress(progress_callback, "done", 1, 2, "本地模式，无需同步", status="skipped")
            return stats

        _emit_sync_progress(progress_callback, "sync", 1, 2, "执行帧级增量同步...")

        if not dry_run:
            with connection._main_write_conn_op_lock:
                sync_result = conn.sync()
            stats["frames_synced"] = getattr(sync_result, "frames_synced", 0) if sync_result else 0

        _emit_sync_progress(progress_callback, "done", 2, 2, "同步完成", upload=0, download=0)
        stats["duration_ms"] = int((time.time() - sync_start) * 1000)
        stats["status"] = "ok"
        return stats
    except Exception as e:
        _debug_log(f"数据库同步失败: {e}", level="WARNING", module="database.momo_words")
        stats["status"] = "error"
        stats["reason"] = str(e)
        _emit_sync_progress(progress_callback, "error", 0, 0, f"同步失败: {e}", status="error", reason=str(e))
        return stats


def sync_hub_databases(
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    stats: Dict[str, Any] = {"upload": 0, "download": 0, "status": "ok", "reason": ""}
    sync_start = time.time()

    if not TURSO_HUB_DB_URL or not TURSO_HUB_AUTH_TOKEN or not connection.HAS_LIBSQL:
        stats["status"] = "skipped"
        stats["reason"] = "missing-hub-cloud-credentials" if (not TURSO_HUB_DB_URL or not TURSO_HUB_AUTH_TOKEN) else "libsql-unavailable"
        _emit_sync_progress(progress_callback, "skipped", 0, 0, "跳过 Hub 同步: 云端凭据或 libsql 不可用", status="skipped")
        return stats

    try:
        _emit_sync_progress(progress_callback, "connect", 1, 2, "连接 Hub Embedded Replica 数据库")

        try:
            local_hub_conn = connection._get_hub_local_conn()
            _init_hub_schema(local_hub_conn)
            local_hub_conn.close()
        except Exception as e:
            _debug_log(f"Hub 本地表初始化警告（非致命）: {e}", module="database.momo_words")

        try:
            hub_conn = connection._get_hub_conn()
        except Exception as conn_error:
            if _is_cloud_connection_unavailable_error(conn_error):
                stats["status"] = "skipped"
                stats["reason"] = "cloud-unavailable"
                _emit_sync_progress(progress_callback, "skipped", 0, 0, f"跳过 Hub 同步: {conn_error}", status="skipped", reason=stats["reason"])
                return stats
            raise

        if not hasattr(hub_conn, "sync"):
            stats["status"] = "skipped"
            stats["reason"] = "local-only-hub-connection"
            _emit_sync_progress(progress_callback, "done", 1, 2, "Hub 本地模式，无需同步", status="skipped")
            return stats

        _emit_sync_progress(progress_callback, "sync", 1, 2, "执行 Hub 帧级增量同步...")

        if not dry_run:
            with connection._hub_write_conn_op_lock:
                sync_result = hub_conn.sync()
            stats["frames_synced"] = getattr(sync_result, "frames_synced", 0) if sync_result else 0

        _emit_sync_progress(progress_callback, "done", 2, 2, "Hub 同步完成", upload=0, download=0)
        stats["duration_ms"] = int((time.time() - sync_start) * 1000)
        stats["status"] = "ok"
        return stats
    except Exception as e:
        _debug_log(f"Hub 同步失败: {e}", level="WARNING", module="database.momo_words")
        stats["status"] = "error"
        stats["reason"] = str(e)
        _emit_sync_progress(progress_callback, "error", 0, 0, f"Hub 同步失败: {e}", status="error", reason=str(e))
        return stats


def get_local_word_note(voc_id: str, db_path: str = None) -> Optional[dict]:
    """Read word note from local/read path; fallback behavior handled by read layer."""
    return get_word_note(voc_id, db_path=db_path)


def set_note_sync_status(voc_id: str, sync_status: int, db_path: str = None) -> bool:
    try:
        sql = "UPDATE ai_word_notes SET sync_status = ?, updated_at = ? WHERE voc_id = ?"
        args = (int(sync_status), get_timestamp_with_tz(), str(voc_id))
        if connection._should_use_local_only_connection(db_path):
            connection._execute_write_sql_sync(sql, args, db_path=db_path)
            return True
        return connection._queue_write_operation(sql, args, op_type="insert_or_replace")
    except Exception as e:
        _debug_log(f"set_note_sync_status 失败: {e}", level="WARNING", module="database.momo_words")
        return False


def mark_note_synced(voc_id: str, db_path: str = None) -> bool:
    return set_note_sync_status(voc_id, 1, db_path=db_path)


def mark_note_sync_conflict(voc_id: str, db_path: str = None) -> bool:
    return set_note_sync_status(voc_id, 2, db_path=db_path)


def save_ai_batch(batch_data: dict, db_path: str = None) -> bool:
    sql = (
        "INSERT OR REPLACE INTO ai_batches (batch_id, request_id, ai_provider, model_name, prompt_version, "
        "batch_size, total_latency_ms, prompt_tokens, completion_tokens, total_tokens, finish_reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
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
    if connection._should_use_local_only_connection(db_path):
        connection._execute_write_sql_sync(sql, args, db_path=db_path)
        return True
    return connection._queue_write_operation(sql, args, op_type="insert_or_replace")


def save_ai_word_iteration(voc_id: str, payload: dict, db_path: str = None, metadata: dict = None, conn: Any = None) -> bool:
    if not voc_id:
        return False
    try:
        data = payload or {}
        meta = metadata or {}
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
        sql = (
            "INSERT INTO ai_word_iterations (voc_id, spelling, stage, it_level, score, justification, tags, "
            "refined_content, candidate_notes, raw_response, maimemo_context, batch_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )

        if connection._should_use_local_only_connection(db_path, conn):
            connection._execute_write_sql_sync(sql, args, db_path=db_path, conn=conn)
            return True
        return connection._queue_write_operation(sql, args, op_type="insert_or_replace")
    except Exception as e:
        _debug_log(f"保存迭代历史失败: {e}", level="WARNING", module="database.momo_words")
        return False


def update_ai_word_note_iteration_state(
    voc_id: str,
    level: int,
    it_history_json: str,
    memory_aid: Optional[str] = None,
    db_path: str = None,
) -> bool:
    try:
        if memory_aid is not None:
            sql = "UPDATE ai_word_notes SET it_level = ?, it_history = ?, memory_aid = ?, updated_at = ? WHERE voc_id = ?"
            args = (int(level), it_history_json, memory_aid, get_timestamp_with_tz(), str(voc_id))
        else:
            sql = "UPDATE ai_word_notes SET it_level = ?, it_history = ?, updated_at = ? WHERE voc_id = ?"
            args = (int(level), it_history_json, get_timestamp_with_tz(), str(voc_id))

        if connection._should_use_local_only_connection(db_path):
            connection._execute_write_sql_sync(sql, args, db_path=db_path)
            return True
        return connection._queue_write_operation(sql, args, op_type="insert_or_replace")
    except Exception as e:
        _debug_log(f"update_ai_word_note_iteration_state 失败: {e}", level="WARNING", module="database.momo_words")
        return False


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


def find_word_in_community(voc_id: str, ai_provider: str = None, prompt_version: str = None) -> Optional[Tuple[dict, str]]:
    result = find_words_in_community_batch([str(voc_id)], skip_cloud=False, ai_provider=ai_provider, prompt_version=prompt_version)
    return result.get(str(voc_id))


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

    c = connection._get_conn(TEST_DB_PATH)
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
    if not connection._is_main_write_singleton_conn(c):
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
    "set_note_sync_status",
    "mark_note_synced",
    "mark_note_sync_conflict",
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
