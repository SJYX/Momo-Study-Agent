from __future__ import annotations
"""
database/community_lookup.py: 跨本地历史库 + 当前库 + 云端副本的批量笔记查找。

边界：
- 仅处理读多源/补查的查询逻辑（本地历史 → 当前库 → 云端只读副本）。
- 不写入数据库；写入路径在 notes_repo.py / progress_repo.py。
- 严格遵守游标释放与单例锁协议（database/README.md）。
- 日志 module 名保留 "database.momo_words"。
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

import config as _config

from . import connection
from .sql_constants import COMMUNITY_NOTE_LOOKUP_SQL_TEMPLATE
from .utils import (
    _collect_cloud_lookup_targets,
    _debug_log,
    _get_cloud_lookup_replica_path,
)

try:
    import libsql
except Exception:  # noqa: BLE001 - libsql 是可选依赖，缺失时跳过云端补查
    libsql = None

_LOG_MOD = "database.momo_words"


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


def _query_notes_from_cursor(cur, voc_ids: List[str], *, use_libsql_dict: bool = False) -> List[Dict[str, Any]]:
    """在已打开的游标上执行跨库 lookup SQL，并在游标关闭前完成行映射。"""
    placeholders = ",".join(["?"] * len(voc_ids))
    sql = COMMUNITY_NOTE_LOOKUP_SQL_TEMPLATE.format(placeholders=placeholders)
    cur.execute(sql, voc_ids)
    rows = cur.fetchall()
    if not rows:
        return []
    if use_libsql_dict:
        columns = [col[0] for col in cur.description]
        return [dict(zip(columns, row)) for row in rows]
    return [connection._row_to_dict(cur, row) for row in rows]


@contextmanager
def _safe_cursor(conn_obj, *, lock=None) -> Iterator[Any]:
    """游标 + 锁的上下文管理器：保证在 cur.close() 前完成 description 访问，并 commit 释放读事务锁。"""
    if lock is not None:
        with lock:
            cur = conn_obj.cursor()
            try:
                yield cur
            finally:
                cur.close()
            conn_obj.commit()
    else:
        cur = conn_obj.cursor()
        try:
            yield cur
        finally:
            cur.close()
        conn_obj.commit()


def _absorb_lookup_results(
    mapped_rows: List[Dict[str, Any]],
    *,
    source_label: str,
    result: Dict[str, Tuple[Dict[str, Any], str]],
    remaining_ids: List[str],
    ai_provider: Optional[str],
    prompt_version: Optional[str],
) -> int:
    """把一次查询的结果归并到 result 字典，并从 remaining_ids 中移除命中项。返回新命中数量。"""
    found = 0
    for note_dict in mapped_rows:
        voc_id = note_dict.get("voc_id")
        if voc_id and voc_id not in result and _matches_ai_generation_context(
            note_dict, ai_provider=ai_provider, prompt_version=prompt_version,
        ):
            result[voc_id] = (note_dict, source_label)
            if voc_id in remaining_ids:
                remaining_ids.remove(voc_id)
            found += 1
    return found


def _list_history_db_files() -> List[str]:
    """枚举与当前 DB 同目录下的历史库文件，按修改时间倒序。"""
    cdb = os.path.basename(_config.DB_PATH)
    dr = os.path.dirname(_config.DB_PATH)
    try:
        return sorted(
            [
                f for f in os.listdir(dr)
                if (f.startswith("history_") or f.startswith("history-"))
                and f.endswith(".db") and f != cdb
            ],
            key=lambda x: os.path.getmtime(os.path.join(dr, x)),
            reverse=True,
        )
    except OSError:
        return []


def find_words_in_community_batch(
    voc_ids: List[str],
    skip_cloud: bool = False,
    ai_provider: Optional[str] = None,
    prompt_version: Optional[str] = None,
) -> Dict[str, Tuple[Dict[str, Any], str]]:
    """批量在社区数据库中查找单词笔记（优先本地历史/当前库，云端只补查剩余项）"""
    if not voc_ids:
        return {}

    result: Dict[str, Tuple[Dict[str, Any], str]] = {}
    remaining_ids = [str(vid) for vid in voc_ids]

    # 1) 本地历史库（按 mtime 倒序逐个尝试，命中即继续下一个未命中的 voc）
    if remaining_ids:
        dr = os.path.dirname(_config.DB_PATH)
        for df in _list_history_db_files():
            if not remaining_ids:
                break
            try:
                c = connection._get_local_conn(os.path.join(dr, df))
                try:
                    with _safe_cursor(c) as cur:
                        mapped_rows = _query_notes_from_cursor(cur, remaining_ids)
                finally:
                    c.close()
            except Exception:  # noqa: BLE001 - 单个历史库不可读时跳过即可
                continue

            _absorb_lookup_results(
                mapped_rows,
                source_label=df,
                result=result,
                remaining_ids=remaining_ids,
                ai_provider=ai_provider,
                prompt_version=prompt_version,
            )

    # 2) 当前数据库（必须在游标关闭/commit 后才释放读事务锁）
    if remaining_ids:
        c = None
        try:
            c = connection._get_read_conn(_config.DB_PATH)
            conn_lock = connection._get_singleton_conn_op_lock(c)
            with _safe_cursor(c, lock=conn_lock) as cur:
                mapped_rows = _query_notes_from_cursor(cur, remaining_ids)
            _absorb_lookup_results(
                mapped_rows,
                source_label="当前数据库",
                result=result,
                remaining_ids=remaining_ids,
                ai_provider=ai_provider,
                prompt_version=prompt_version,
            )
        except Exception:  # noqa: BLE001 - 当前库读失败让位给云端补查
            pass
        finally:
            if c is not None and not connection._is_main_write_singleton_conn(c):
                try:
                    c.close()
                except Exception:  # noqa: BLE001
                    pass

    # 3) 云端副本（只查仍缺失项；使用 sqlite3 读取本地副本文件，兼容 libsql ER 和 pyturso 两种格式）
    if not skip_cloud and remaining_ids:
        for cloud_url, cloud_token, source_label in _collect_cloud_lookup_targets():
            if not remaining_ids:
                break
            cloud_conn = None
            try:
                lookup_path = _get_cloud_lookup_replica_path(cloud_url)
                if not os.path.exists(lookup_path):
                    _debug_log(f"{source_label} 本地副本不存在，跳过纯读补查: {lookup_path}", level="DEBUG")
                    continue

                cloud_conn = sqlite3.connect(lookup_path)
                cur = cloud_conn.cursor()
                try:
                    mapped_rows = _query_notes_from_cursor(cur, remaining_ids, use_libsql_dict=True)
                finally:
                    cur.close()

                _absorb_lookup_results(
                    mapped_rows,
                    source_label=source_label,
                    result=result,
                    remaining_ids=remaining_ids,
                    ai_provider=ai_provider,
                    prompt_version=prompt_version,
                )
                _debug_log(f"{source_label} 批量查询完成：累计找到 {len(result)} 个单词的笔记")
            except Exception as e:  # noqa: BLE001 - 云端瞬时故障/超时不应阻塞调用方
                _debug_log(f"{source_label} 批量查询失败 [{type(e).__name__}]: {e}")
            finally:
                if cloud_conn:
                    try:
                        cloud_conn.close()
                    except Exception:  # noqa: BLE001
                        pass

    return result


def find_word_in_community(voc_id: str, ai_provider: Optional[str] = None, prompt_version: Optional[str] = None) -> Optional[Tuple[Dict[str, Any], str]]:
    result = find_words_in_community_batch([str(voc_id)], skip_cloud=False, ai_provider=ai_provider, prompt_version=prompt_version)
    return result.get(str(voc_id))


__all__ = [
    "find_words_in_community_batch",
    "find_word_in_community",
]
