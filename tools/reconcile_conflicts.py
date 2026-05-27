"""
tools/reconcile_conflicts.py: 诊断并修复 sync_status=2 (CONFLICT) 的假阳性记录。

Phase 1: 本地比较 — last_synced_content == basic_meanings → 自动修复为 sync_status=1
Phase 2: Maimemo API 比较 — 调用 list_interpretations 获取云端释义，相似度 >= 0.95 → 修复

用法:
    python -m tools.reconcile_conflicts --user <username> --dry-run
    python -m tools.reconcile_conflicts --user <username> --phase1-only
    python -m tools.reconcile_conflicts --user <username>
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="诊断并修复 sync_status=2 (CONFLICT) 的假阳性记录"
    )
    parser.add_argument("--user", required=True, help="目标用户名")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅显示会变更的记录，不实际写入",
    )
    parser.add_argument(
        "--phase1-only",
        action="store_true",
        help="仅执行 Phase 1（本地比较），跳过 Maimemo API",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    return parser.parse_args()


def resolve_db_path(username: str) -> str:
    """解析用户数据库路径，兼容 history-X.db 和 history_X.db 命名。"""
    data_dir = os.path.join(ROOT_DIR, "data")
    db_path = os.path.join(data_dir, f"history-{username.lower()}.db")
    if os.path.exists(db_path):
        return db_path
    # 兼容旧命名
    old_path = os.path.join(data_dir, f"history_{username}.db")
    if os.path.exists(old_path):
        return old_path
    old_lower = os.path.join(data_dir, f"history_{username.lower()}.db")
    if os.path.exists(old_lower):
        return old_lower
    print(f"ERROR: 数据库文件不存在: {db_path}")
    sys.exit(1)


def get_conflict_records(conn: "sqlite3.Connection") -> list[dict]:
    """查询所有 sync_status=2 的记录。"""
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT voc_id, spelling, basic_meanings, last_synced_content, "
        "content_origin, match_confidence, match_reason "
        "FROM ai_word_notes WHERE sync_status = 2"
    )
    return [dict(row) for row in cursor.fetchall()]


def _normalize(text: str) -> str:
    """标准化文本：去空白，用于比较。"""
    return "".join(str(text or "").split())


def run_phase1(
    conn: "sqlite3.Connection",
    conflicts: list[dict],
    *,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[int, list[dict]]:
    """Phase 1: 本地比较 last_synced_content vs basic_meanings。

    返回 (fixed_count, remaining_records)。
    """
    fixed = 0
    remaining = []

    for rec in conflicts:
        voc_id = rec["voc_id"]
        spelling = rec.get("spelling", "")
        last_synced = rec.get("last_synced_content") or ""
        basic = rec.get("basic_meanings") or ""

        if not last_synced:
            if verbose:
                print(f"  [SKIP]  voc_id={voc_id} \"{spelling}\" — last_synced_content 为空")
            remaining.append(rec)
            continue

        if _normalize(last_synced) == _normalize(basic):
            if dry_run:
                print(f"  [DRY]   voc_id={voc_id} \"{spelling}\" — 本地匹配，可修复为 sync_status=1")
            else:
                conn.execute(
                    "UPDATE ai_word_notes SET sync_status = 1, "
                    "match_confidence = 1.0, match_reason = 'local_match', "
                    "updated_at = datetime('now') WHERE voc_id = ?",
                    (voc_id,),
                )
                if verbose:
                    print(f"  [FIXED] voc_id={voc_id} \"{spelling}\" — last_synced_content 匹配 basic_meanings")
            fixed += 1
        else:
            if verbose:
                print(f"  [KEEP]  voc_id={voc_id} \"{spelling}\" — 内容不同，需 Phase 2")
            remaining.append(rec)

    return fixed, remaining


def main() -> int:
    args = parse_args()
    username = args.user
    db_path = resolve_db_path(username)

    print(f"=== Conflict Reconciliation ===")
    print(f"User: {username}")
    print(f"DB: {db_path}")
    print()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=5000;")
    try:
        conflicts = get_conflict_records(conn)
        print(f"--- Phase 1: 本地比较 ---")
        print(f"发现 {len(conflicts)} 条冲突记录")

        if not conflicts:
            print("无冲突记录，退出")
            return 0

        fixed_p1, remaining = run_phase1(
            conn, conflicts, dry_run=args.dry_run, verbose=args.verbose
        )
        if not args.dry_run:
            conn.commit()
        print(f"Phase 1 结果: {fixed_p1} 已修复, {len(remaining)} 需要 API 检查")
        print()

        if args.phase1_only:
            print("=== Summary (Phase 1 only) ===")
            print(f"Total conflicts: {len(conflicts)}")
            print(f"Fixed (Phase 1): {fixed_p1}")
            return 0

        print(f"--- Phase 2: Maimemo API 比较 ---")
        print("(Phase 2 尚未实现)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
