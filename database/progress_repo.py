from __future__ import annotations
"""
database/progress_repo.py: processed_words / word_progress_history 表的读写。

边界：
- 仅处理"已处理单词"标记与"短期/长期熟悉度历史快照"两张表。
- 笔记/批次相关在 notes_repo.py；跨库查找在 community_lookup.py；同步在 sync_service.py。
- 日志 module 名保留 "database.momo_words"。
"""

import sqlite3
import time
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple

from database.session import with_read_session, DBSession
from ._repo_helpers import (
    dispatch_batch_write,
    dispatch_write,
    row_to_dict,
    row_value,
)
from .dto import ProgressSnapshot
from .sql_constants import PROCESSED_UPSERT_SQL, PROGRESS_INSERT_SQL
from .utils import _debug_log, get_timestamp_with_tz

_LOG_MOD = "database.momo_words"


def _log_progress_failure(func_name: str, e: BaseException, *, level: str = "WARNING") -> None:
    cat = (
        "integrity" if isinstance(e, sqlite3.IntegrityError)
        else "operational" if isinstance(e, sqlite3.OperationalError)
        else "db" if isinstance(e, sqlite3.DatabaseError)
        else "input" if isinstance(e, (TypeError, ValueError, KeyError))
        else "unexpected"
    )
    prefix = f"{func_name} 失败 [{cat}/{type(e).__name__}]: {e}"
    if cat == "unexpected":
        _debug_log(f"{prefix}\n{traceback.format_exc()}", level=level, module=_LOG_MOD)
    else:
        _debug_log(prefix, level=level, module=_LOG_MOD)


@with_read_session(default_return=set())
def get_processed_ids_in_batch(voc_ids: List[str], db_path: Optional[str] = None, session: DBSession = None) -> Set[str]:
    if not voc_ids:
        return set()

    started = time.time()
    vs = [str(v) for v in voc_ids]
    ph = ",".join(["?"] * len(vs))

    rows = session.fetchall(f"SELECT voc_id FROM processed_words WHERE voc_id IN ({ph})", vs)

    result = {str(row_value(r, 0, "voc_id")) for r in rows}
    _debug_log(f"批量查询 ({len(voc_ids)} 词)", start_time=started, module=_LOG_MOD)
    return result


@with_read_session(default_return=set())
def get_progress_tracked_ids_in_batch(voc_ids: List[str], db_path: Optional[str] = None, session: DBSession = None) -> Set[str]:
    if not voc_ids:
        return set()

    vs = [str(v) for v in voc_ids]
    ph = ",".join(["?"] * len(vs))

    rows = session.fetchall(f"SELECT DISTINCT voc_id FROM word_progress_history WHERE voc_id IN ({ph})", vs)

    return {str(row_value(r, 0, "voc_id")) for r in rows}


@with_read_session(default_return=False)
def is_processed(voc_id: str, db_path: Optional[str] = None, session: DBSession = None) -> bool:
    res = session.fetchone("SELECT 1 FROM processed_words WHERE voc_id = ?", (str(voc_id),))
    return res is not None


def mark_processed(voc_id: str, spelling: str, db_path: Optional[str] = None, conn: Any = None) -> bool:
    try:
        return dispatch_write(
            PROCESSED_UPSERT_SQL,
            (str(voc_id), spelling, get_timestamp_with_tz()),
            db_path=db_path,
            conn=conn,
            queue_full_log=lambda m: _debug_log(f"mark_processed {m}", level="WARNING", module=_LOG_MOD),
        )
    except (sqlite3.DatabaseError, OSError) as e:
        _log_progress_failure("mark_processed", e)
        return False
    except Exception as e:  # noqa: BLE001
        _log_progress_failure("mark_processed", e)
        return False


def mark_processed_batch(items: List[Tuple[str, str]], db_path: Optional[str] = None) -> bool:
    if not items:
        return True

    try:
        ts = get_timestamp_with_tz()
        args_list = [(str(voc_id), spelling, ts) for voc_id, spelling in items]
        return dispatch_batch_write(
            PROCESSED_UPSERT_SQL,
            args_list,
            db_path=db_path,
            queue_full_log=lambda m: _debug_log(f"mark_processed_batch {m}", level="WARNING", module=_LOG_MOD),
        )
    except (sqlite3.DatabaseError, OSError) as e:
        _log_progress_failure("mark_processed_batch", e)
        return False
    except (TypeError, ValueError) as e:
        _log_progress_failure("mark_processed_batch[input]", e)
        return False
    except Exception as e:  # noqa: BLE001
        _log_progress_failure("mark_processed_batch", e)
        return False


@with_read_session(default_return=0)
def log_progress_snapshots(
    words: List[Any],
    db_path: Optional[str] = None,
    session: DBSession = None,
) -> int:
    """记录单词进度快照。兼容 WordItem 对象与字典。"""
    if not words:
        return 0

    def _get(obj, key, default=0):
        if hasattr(obj, key):
            return getattr(obj, key)
        if isinstance(obj, dict):
            return obj.get(key, default)
        return default

    started = time.time()
    vids = [str(_get(w, "voc_id")) for w in words]
    ph = ",".join(["?"] * len(vids))

    itm_rows = session.fetchall(f"SELECT voc_id, it_level FROM ai_word_notes WHERE voc_id IN ({ph})", vids)
    itm = {str(row_value(r, 0, "voc_id")): row_value(r, 1, "it_level") for r in itm_rows}

    lh_rows = session.fetchall(
        f"SELECT voc_id, familiarity_short, review_count FROM word_progress_history WHERE voc_id IN ({ph}) ORDER BY created_at DESC",
        vids,
    )
    lh: Dict[str, Tuple[Any, Any]] = {}
    for r in lh_rows:
        v = str(row_value(r, 0, "voc_id"))
        if v not in lh:
            lh[v] = (row_value(r, 1, "familiarity_short"), row_value(r, 2, "review_count"))

    ins: List[Tuple[Any, ...]] = []
    for w in words:
        v = str(_get(w, "voc_id"))
        nf = _get(w, "short_term_familiarity", 0) or _get(w, "voc_familiarity", 0)
        nr = _get(w, "review_count", 0)
        l = lh.get(v)
        if not l or abs(l[0] - float(nf)) > 0.01 or l[1] != int(nr):
            ins.append((v, nf, _get(w, "long_term_familiarity", 0), nr, itm.get(v, 0)))

    if ins:
        ok = dispatch_batch_write(
            PROGRESS_INSERT_SQL,
            ins,
            db_path=db_path,
            queue_full_log=lambda m: _debug_log(f"log_progress_snapshots {m}", level="WARNING", module=_LOG_MOD),
        )
        if not ok:
            return 0

    _debug_log(f"进度同步 ({len(ins)} 条)", start_time=started, module=_LOG_MOD)
    return len(ins)


@with_read_session(default_return=None)
def get_latest_progress(voc_id: str, db_path: Optional[str] = None, session: DBSession = None) -> Optional[Dict[str, Any]]:
    row = session.fetchone(
        "SELECT familiarity_short, review_count FROM word_progress_history WHERE voc_id = ? ORDER BY created_at DESC LIMIT 1",
        (str(voc_id),),
    )
    return row_to_dict(row, fallback_columns=["familiarity_short", "review_count"])


__all__ = [
    "get_processed_ids_in_batch",
    "get_progress_tracked_ids_in_batch",
    "is_processed",
    "mark_processed",
    "mark_processed_batch",
    "log_progress_snapshots",
    "get_latest_progress",
]
