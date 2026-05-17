from __future__ import annotations
"""
database/word_repo.py: 单词数据统一访问层（替代散落的 3 套兜底判重）。

主要职责：
1. 统一的"单词状态"查询（5 态状态机）—— get_word_states_in_batch 用 LEFT JOIN
2. 便捷判重入口 —— filter_unprocessed
3. 按状态计数/列表查询 —— count_by_state / list_by_state
4. 薄弱词查询（聚合多维度评分）—— query_weak_words
5. 单词笔记分页查询 —— list_word_notes_paginated
6. 迭代历史与 memory_aid 编辑 —— get_word_iterations / update_memory_aid
7. 异步 backfill 占位 —— _enqueue_backfill_processed

与 Phase 7.1 WordState / derive_state 无缝对接。

日志 module 保留 "database.momo_words" 兼容性。
"""

import json
import sqlite3
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from database.session import with_read_session, DBSession
from database.word_state import WordState, derive_state, state_to_where_clause
from ._repo_helpers import (
    dispatch_batch_write,
    dispatch_write,
    row_to_dict,
    row_value,
    rows_to_dicts,
)
from .utils import _debug_log, _is_sqlite_data_corruption_error, get_timestamp_with_tz

_LOG_MOD = "database.momo_words"

# 分批上限
_BATCH_SIZE = 500


def _log_word_repo_failure(func_name: str, e: BaseException, *, level: str = "WARNING") -> None:
    """统一的 word_repo 读写失败日志。"""
    cat = (
        "integrity" if isinstance(e, sqlite3.IntegrityError)
        else "operational" if isinstance(e, sqlite3.OperationalError)
        else "db" if isinstance(e, sqlite3.DatabaseError)
        else "input" if isinstance(e, (TypeError, ValueError, KeyError))
        else "json" if isinstance(e, json.JSONDecodeError)
        else "unexpected"
    )
    prefix = f"{func_name} 失败 [{cat}/{type(e).__name__}]: {e}"
    if cat == "unexpected":
        _debug_log(f"{prefix}\n{traceback.format_exc()}", level=level, module=_LOG_MOD)
    else:
        _debug_log(prefix, level=level, module=_LOG_MOD)


# ============================================================================
# 公开 API
# ============================================================================


@with_read_session(default_return=None)
def get_word_states_in_batch(
    voc_ids: List[str],
    *,
    auto_backfill: bool = True,
    db_path: Optional[str] = None,
    session: DBSession = None,
) -> Optional[Dict[str, str]]:
    """批量获取单词的 5 态状态。

    返回:
    - dict: {voc_id: "not_started" | "local_ready" | "synced" | "conflict" | "failed"}；
            空 dict 表示所有词都是 NOT_STARTED（合法的全新词场景）。
    - None: DB 查询彻底失败（自愈也失败）。调用方必须区分空 dict 与 None，
            否则会把已处理词错判为 NOT_STARTED 触发 AI 重处理。

    机制:
    - 单条 LEFT JOIN: processed_words (p) / ai_word_notes (n)
    - 自动 500 分批，避免 SQL 过长
    - 若 auto_backfill=True 且发现历史漏标（processed=False 但 sync_status == 0），
      异步入队 backfill（O3 优化）

    实现细节:
    - LEFT JOIN 不依赖两边都存在，支持"只有笔记未标记"或"只有标记无笔记"的边界态
    """
    if not voc_ids:
        return {}

    result: Dict[str, str] = {}

    try:
        # 分批处理，避免 SQL 过长（IN 子句过多）
        for i in range(0, len(voc_ids), _BATCH_SIZE):
            batch_voc_ids = voc_ids[i : i + _BATCH_SIZE]
            _get_word_states_batch_internal(
                batch_voc_ids,
                result=result,
                auto_backfill=auto_backfill,
                session=session,
            )
        return result
    except Exception as e:
        # corruption 类异常必须透传给 @with_read_session 的 fallback_on_corruption，
        # 否则装饰器看不到异常，自愈链路不会触发；调用方拿到空 dict 会把所有词误判为
        # NOT_STARTED，让 partition_by_processability 把已处理过的词重新推送 AI（实测：
        # 唤醒后 Turso stream not found 一瞬抛 `database disk image is malformed`，
        # 120 词全部 conflict）。
        if _is_sqlite_data_corruption_error(e):
            raise
        _log_word_repo_failure("get_word_states_in_batch", e)
        return {}


@with_read_session(default_return=set())
def filter_unprocessed(
    voc_ids: List[str],
    db_path: Optional[str] = None,
    session: DBSession = None,
) -> Set[str]:
    """快速判重：返回"未处理"的单词集合（NOT_STARTED 状态）。

    用途: 在推送新词前快速判断"这词是否已处理过"。

    返回: 非空集合表示可推送，空集合表示全部已处理。
    """
    if not voc_ids:
        return set()

    try:
        result: Set[str] = set()

        # 同样分批处理
        for i in range(0, len(voc_ids), _BATCH_SIZE):
            batch_voc_ids = voc_ids[i : i + _BATCH_SIZE]
            batch_unprocessed = _filter_unprocessed_batch_internal(batch_voc_ids, session=session)
            result.update(batch_unprocessed)

        return result
    except Exception as e:
        _log_word_repo_failure("filter_unprocessed", e)
        return set()


@with_read_session(default_return=0)
def count_by_state(
    state: WordState,
    db_path: Optional[str] = None,
    session: DBSession = None,
) -> int:
    """按状态计数。"""
    if not state:
        return 0

    try:
        where_sql, params = state_to_where_clause(state)
        sql = (
            "SELECT COUNT(*) FROM ai_word_notes n "
            "LEFT JOIN processed_words p ON p.voc_id = n.voc_id "
            f"WHERE {where_sql}"
        )
        row = session.fetchone(sql, params)
        return int(row_value(row, 0, "COUNT(*)") or 0)
    except Exception as e:
        _log_word_repo_failure("count_by_state", e)
        return 0


@with_read_session(default_return=[])
def list_by_state(
    state: WordState,
    *,
    limit: int = 20,
    offset: int = 0,
    db_path: Optional[str] = None,
    session: DBSession = None,
) -> List[Dict[str, Any]]:
    """按状态分页列表，返回完整单词记录。"""
    if not state or limit <= 0:
        return []

    try:
        where_sql, params = state_to_where_clause(state)
        sql = (
            "SELECT n.voc_id, n.spelling, n.basic_meanings, n.memory_aid, "
            "n.sync_status, n.it_level, n.updated_at, p.voc_id IS NOT NULL as is_processed "
            "FROM ai_word_notes n "
            "LEFT JOIN processed_words p ON p.voc_id = n.voc_id "
            f"WHERE {where_sql} "
            "ORDER BY n.updated_at DESC "
            "LIMIT ? OFFSET ?"
        )
        rows = session.fetchall(sql, params + (limit, offset))
        return rows_to_dicts(rows, fallback_columns=["voc_id", "spelling", "basic_meanings", "memory_aid", "sync_status", "it_level", "updated_at", "is_processed"])
    except Exception as e:
        _log_word_repo_failure("list_by_state", e)
        return []


@with_read_session(default_return=[])
def query_weak_words(
    *,
    min_score: float = 60.0,
    threshold: Optional[int] = None,
    category: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[str] = None,
    session: DBSession = None,
) -> List[Dict[str, Any]]:
    """查询薄弱词（多维度评分）。

    参数:
    - min_score: 评分阈值（0-100），越低越容易被选中（<=60 表示真薄弱）
    - threshold: 可选的 review_count 阈值（如 threshold=5 表示"复习 ≤5 次的词"）
    - category: 预留参数，暂不使用（未来支持分类过滤）
    - limit: 返回条数

    评分维度（见 core/weak_word_filter.py::calculate_weak_score）:
    1. 熟悉度 (0-40分)
    2. 复习次数 (0-20分)
    3. 时间因素 (0-10分)
    4. 迭代级别 (0-10分)

    返回: [{voc_id, spelling, score, review_count, familiarity_short, ...}]

    实现细节:
    - 计算分数通过 SQL CASE 表达式模拟评分算法
    - 过滤高分词（薄弱词）并按分数倒序排列
    """
    if limit <= 0:
        return []

    try:
        conditions = []
        params: List[Any] = []

        # 基础条件：优先筛选已处理词；测试库/旧库若没有 sync_status 列也能兼容
        conditions.append("p.voc_id IS NOT NULL")

        # 可选：复习次数阈值
        if threshold is not None and threshold > 0:
            conditions.append("COALESCE(h.review_count, 0) <= ?")
            params.append(threshold)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        sql = (
            "SELECT n.voc_id, n.spelling, n.basic_meanings, h.review_count, "
            "h.familiarity_short, n.it_level, n.updated_at "
            f"FROM ai_word_notes n "
            f"LEFT JOIN processed_words p ON p.voc_id = n.voc_id "
            f"LEFT JOIN word_progress_history h ON h.voc_id = n.voc_id "
            f"WHERE {where_clause} "
            f"ORDER BY n.updated_at DESC "
            f"LIMIT ?"
        )
        params.append(limit)

        rows = session.fetchall(sql, params)

        def _to_number(value: Any, default: float = 0.0) -> float:
            try:
                if value is None:
                    return default
                return float(value)
            except (TypeError, ValueError):
                return default

        scored_rows: List[Dict[str, Any]] = []
        for row in rows_to_dicts(rows, fallback_columns=["voc_id", "spelling", "basic_meanings", "review_count", "familiarity_short", "it_level", "updated_at"]):
            score = 0.0

            familiarity = _to_number(row.get("familiarity_short"), 0.0)
            if familiarity < 3.0:
                score += min(40.0, (3.0 - familiarity) * 13.33)

            review_count = int(_to_number(row.get("review_count"), 0))
            if review_count < 5:
                score += 20
            elif review_count < 10:
                score += 15
            elif review_count < 20:
                score += 10
            elif review_count < 30:
                score += 5

            created_at = str(row.get("updated_at") or row.get("created_at") or "")
            if created_at:
                try:
                    if created_at.endswith("Z"):
                        created_at = created_at.replace("Z", "+00:00")
                    created_date = datetime.fromisoformat(created_at)
                    days_since = (datetime.now() - created_date).days
                    if days_since > 30:
                        score += 10
                    elif days_since > 14:
                        score += 7
                    elif days_since > 7:
                        score += 4
                except Exception:
                    pass

            it_level = int(_to_number(row.get("it_level"), 0))
            score += min(it_level * 2, 10)

            if score >= min_score:
                item = dict(row)
                item["score"] = round(score, 2)
                item["weak_score"] = round(score, 2)
                if not item.get("created_at") and item.get("updated_at"):
                    item["created_at"] = item.get("updated_at")
                scored_rows.append(item)

        scored_rows.sort(key=lambda x: x.get("weak_score", 0.0), reverse=True)
        return scored_rows[:limit]
    except Exception as e:
        _log_word_repo_failure("query_weak_words", e)
        return []


@with_read_session(default_return=[])
def list_word_notes_paginated(
    *,
    search: Optional[str] = None,
    sync_status: Optional[int] = None,
    it_level: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    db_path: Optional[str] = None,
    session: DBSession = None,
) -> List[Dict[str, Any]]:
    """分页查询单词笔记（支持多条件过滤）。

    参数:
    - search: 关键词搜索（模糊匹配 spelling 或 basic_meanings）
    - sync_status: 同步状态过滤（0/1/2/3/4/5 之一，None 表示不过滤）
    - it_level: 迭代级别过滤（None 表示不过滤）
    - page: 页码（1-indexed）
    - page_size: 每页行数

    返回: 完整单词记录列表
    """
    if page < 1:
        page = 1
    if page_size <= 0:
        page_size = 20

    try:
        conditions = []
        params: List[Any] = []

        if search:
            conditions.append("(n.spelling LIKE ? OR n.basic_meanings LIKE ?)")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern])

        if sync_status is not None:
            conditions.append("n.sync_status = ?")
            params.append(sync_status)

        if it_level is not None:
            conditions.append("n.it_level = ?")
            params.append(it_level)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        offset = (page - 1) * page_size

        sql = (
            "SELECT n.voc_id, n.spelling, n.basic_meanings, n.memory_aid, "
            "n.sync_status, n.it_level, n.updated_at, p.voc_id IS NOT NULL as is_processed "
            "FROM ai_word_notes n "
            "LEFT JOIN processed_words p ON p.voc_id = n.voc_id "
            f"WHERE {where_clause} "
            "ORDER BY n.updated_at DESC "
            "LIMIT ? OFFSET ?"
        )
        params.extend([page_size, offset])

        rows = session.fetchall(sql, params)
        return rows_to_dicts(rows, fallback_columns=["voc_id", "spelling", "basic_meanings", "memory_aid", "sync_status", "it_level", "updated_at", "is_processed"])
    except Exception as e:
        _log_word_repo_failure("list_word_notes_paginated", e)
        return []


@with_read_session(default_return=0)
def count_word_notes(
    *,
    search: Optional[str] = None,
    sync_status: Optional[int] = None,
    it_level: Optional[int] = None,
    db_path: Optional[str] = None,
    session: DBSession = None,
) -> int:
    """统计单词笔记总数（与 list_word_notes_paginated 使用相同过滤条件）。"""
    try:
        conditions = []
        params: List[Any] = []

        if search:
            conditions.append("(n.spelling LIKE ? OR n.basic_meanings LIKE ?)")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern])

        if sync_status is not None:
            conditions.append("n.sync_status = ?")
            params.append(sync_status)

        if it_level is not None:
            conditions.append("n.it_level = ?")
            params.append(it_level)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT COUNT(*) FROM ai_word_notes n WHERE {where_clause}"
        row = session.fetchone(sql, params)
        return int(row_value(row, 0, "COUNT(*)") or 0)
    except Exception as e:
        _log_word_repo_failure("count_word_notes", e)
        return 0


@with_read_session(default_return=[])
def get_word_iterations(
    voc_id: str,
    db_path: Optional[str] = None,
    session: DBSession = None,
) -> List[Dict[str, Any]]:
    """查询单个单词的全部迭代历史。"""
    if not voc_id:
        return []

    try:
        sql = (
            "SELECT id, voc_id, spelling, stage, it_level, score, justification, tags, "
            "refined_content, candidate_notes, raw_response, created_at "
            "FROM ai_word_iterations "
            "WHERE voc_id = ? "
            "ORDER BY created_at DESC"
        )
        rows = session.fetchall(sql, (str(voc_id),))
        return rows_to_dicts(rows, fallback_columns=["id", "voc_id", "spelling", "stage", "it_level", "score", "justification", "tags", "refined_content", "candidate_notes", "raw_response", "created_at"])
    except Exception as e:
        _log_word_repo_failure("get_word_iterations", e)
        return []


def update_memory_aid(
    voc_id: str,
    memory_aid: str,
    db_path: Optional[str] = None,
    conn: Any = None,
) -> bool:
    """更新单词的 memory_aid（学习笔记）。

    写操作，走 dispatch_write → 队列或直接执行。
    """
    if not voc_id:
        return False

    try:
        sql = "UPDATE ai_word_notes SET memory_aid = ?, updated_at = ? WHERE voc_id = ?"
        args = (memory_aid, get_timestamp_with_tz(), str(voc_id))

        return dispatch_write(sql, args, db_path=db_path, conn=conn, op_type="update")
    except Exception as e:
        _log_word_repo_failure("update_memory_aid", e)
        return False


def _enqueue_backfill_processed(
    voc_ids: List[str],
    db_path: Optional[str] = None,
) -> bool:
    """异步入队：将历史漏标词加入到 processed_words（O3 优化）。

    调用方: get_word_states_in_batch，在发现"sync_status == 0 但 processed_words 无该词"时触发。

    实现: 入队一个 BATCH INSERT 任务到写队列，后台守护线程处理。

    返回: 入队成功返回 True，队列满返回 False。
    """
    if not voc_ids:
        return True

    try:
        from .sql_constants import PROCESSED_UPSERT_SQL

        timestamp = get_timestamp_with_tz()
        args_list = [(str(vid), "", timestamp) for vid in voc_ids]

        return dispatch_batch_write(
            PROCESSED_UPSERT_SQL,
            args_list,
            db_path=db_path,
            queue_full_message=f"backfill_processed 入队失败: 写队列已满 ({len(voc_ids)} 词)",
        )
    except Exception as e:
        _log_word_repo_failure("_enqueue_backfill_processed", e)
        return False


# ============================================================================
# 内部辅助函数
# ============================================================================


def _get_word_states_batch_internal(
    voc_ids: List[str],
    *,
    result: Dict[str, str],
    auto_backfill: bool = True,
    session: Optional[DBSession] = None,
) -> None:
    """单批次 LEFT JOIN 查询（不递归分批）。

    机制:
    - LEFT JOIN processed_words (p) / ai_word_notes (n)
    - 对每行调用 derive_state，存入 result
    - 若 auto_backfill=True 且发现历史漏标，积累 to_backfill 并入队
    """
    if not voc_ids or session is None:
        return

    vs = [str(v) for v in voc_ids]
    ph = ",".join(["?"] * len(vs))

    # SQLite 无 FULL OUTER JOIN，用两段 LEFT JOIN + UNION 覆盖
    # "只在 processed_words" / "只在 ai_word_notes" / "两侧都有" 三类行。
    sql = (
        f"SELECT p.voc_id, n.voc_id as n_voc_id, n.sync_status "
        f"FROM processed_words p "
        f"LEFT JOIN ai_word_notes n ON n.voc_id = p.voc_id "
        f"WHERE p.voc_id IN ({ph}) "
        f"UNION "
        f"SELECT p.voc_id, n.voc_id as n_voc_id, n.sync_status "
        f"FROM ai_word_notes n "
        f"LEFT JOIN processed_words p ON p.voc_id = n.voc_id "
        f"WHERE n.voc_id IN ({ph})"
    )

    t_sql_start = time.time()

    rows = session.fetchall(sql, vs + vs)
    t_sql_end = time.time()
    sql_duration = int((t_sql_end - t_sql_start) * 1000)
    if sql_duration > 100:
        _debug_log(f"[Profiling] {len(voc_ids)} 词状态查询 SQL 耗时: {sql_duration}ms", level="INFO", module=_LOG_MOD)

    to_backfill: List[str] = []

    # UNION 查询返回的列名，用于裸 tuple 回退映射（singleton 连接无 row_factory）
    _row_columns = ["voc_id", "n_voc_id", "sync_status"]

    for row in rows:
        row_dict = row_to_dict(row, fallback_columns=_row_columns)
        if not row_dict:
            continue

        # 取 UNION 中非空的 voc_id
        voc_id = row_dict.get("n_voc_id") or row_dict.get("voc_id")
        if not voc_id:
            continue

        processed = row_dict.get("voc_id") is not None  # 来自 processed_words？
        sync_status = row_dict.get("sync_status")

        state = derive_state(processed, sync_status)
        result[voc_id] = state.value

        # 历史漏标检测：processed=False 但 sync_status == 0
        if auto_backfill and not processed and sync_status == 0:
            to_backfill.append(voc_id)

    # 入队 backfill 任务（异步，不阻塞当前查询）
    if to_backfill:
        _enqueue_backfill_processed(to_backfill)


def _filter_unprocessed_batch_internal(
    voc_ids: List[str],
    session: Optional[DBSession] = None,
) -> Set[str]:
    """单批次判重查询（返回 NOT_STARTED 状态的 voc_id）。"""
    if not voc_ids or session is None:
        return set()

    vs = [str(v) for v in voc_ids]
    ph = ",".join(["?"] * len(vs))

    # NOT_STARTED = processed_words 无该 voc_id 且 ai_word_notes 也无该 voc_id。
    # 直接查两张表的命中集合，Python 侧做集合差。
    processed_rows = session.fetchall(
        f"SELECT voc_id FROM processed_words WHERE voc_id IN ({ph})", vs
    )
    processed_ids = {str(row_value(r, 0, "voc_id")) for r in processed_rows}

    notes_rows = session.fetchall(
        f"SELECT DISTINCT voc_id FROM ai_word_notes WHERE voc_id IN ({ph})", vs
    )
    notes_ids = {str(row_value(r, 0, "voc_id")) for r in notes_rows}

    return set(vs) - processed_ids - notes_ids


__all__ = [
    "get_word_states_in_batch",
    "filter_unprocessed",
    "count_by_state",
    "list_by_state",
    "query_weak_words",
    "count_word_notes",
    "list_word_notes_paginated",
    "get_word_iterations",
    "update_memory_aid",
]
