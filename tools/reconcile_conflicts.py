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
import time

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


def init_maimemo_client():
    """从 profile env 加载 MOMO_TOKEN 并初始化 MaiMemoAPI 客户端。"""
    from core.maimemo_api import MaiMemoAPI

    token = os.getenv("MOMO_TOKEN")
    if not token:
        print("WARNING: MOMO_TOKEN 未设置，跳过 Phase 2（Maimemo API 比较）")
        return None
    return MaiMemoAPI(token)


def run_phase2(
    conn,
    client,
    remaining: list,
    *,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """Phase 2: 调用 Maimemo API 比较云端释义 vs 本地 basic_meanings。

    返回 fixed_count。
    """
    fixed = 0
    total = len(remaining)

    for i, rec in enumerate(remaining):
        voc_id = rec["voc_id"]
        spelling = rec.get("spelling", "")
        basic = rec.get("basic_meanings") or ""

        if not basic:
            if verbose:
                print(f'  [SKIP]  voc_id={voc_id} "{spelling}" — basic_meanings 为空')
            continue

        # 进度输出（每 50 条）
        if (i + 1) % 50 == 0 or verbose:
            print(f"  进度: {i + 1}/{total}")

        try:
            res = client.list_interpretations(voc_id)
        except Exception as e:
            if verbose:
                print(f'  [ERROR] voc_id={voc_id} "{spelling}" — API 调用失败: {e}')
            continue

        # 用 MaiMemoAPI 内部方法比较
        info = client._classify_interpretation_list(res, expected_text=basic)
        cloud_status = info.get("sync_status", 0)
        confidence = info.get("match_confidence")
        reason = info.get("reason", "")

        cloud_text = info.get("first_text", "")

        if cloud_status == 1:
            # 匹配成功：sync_status=1, last_synced_content=本地内容
            if dry_run:
                print(f'  [DRY]   voc_id={voc_id} "{spelling}" — 云端匹配 (confidence={confidence})')
            else:
                conn.execute(
                    "UPDATE ai_word_notes SET sync_status = 1, "
                    "match_confidence = ?, match_reason = ?, "
                    "last_synced_content = basic_meanings, "
                    "updated_at = datetime('now') WHERE voc_id = ?",
                    (confidence, f"api_{reason}", voc_id),
                )
                if verbose:
                    print(f'  [SYNCED] voc_id={voc_id} "{spelling}" — 云端匹配 (confidence={confidence})')
            fixed += 1
        else:
            # 匹配失败：保持 sync_status=2，写入云端文本供未来参考
            if not dry_run and cloud_text:
                conn.execute(
                    "UPDATE ai_word_notes SET last_synced_content = ?, "
                    "updated_at = datetime('now') WHERE voc_id = ?",
                    (cloud_text, voc_id),
                )
            if verbose:
                print(f'  [CONFLICT] voc_id={voc_id} "{spelling}" — 云端不同 (confidence={confidence})')

        # 频控：每次 API 调用后等待 0.3s
        time.sleep(0.3)

    return fixed


def _load_profile_env(username: str) -> None:
    """加载用户 profile 的 .env 文件（dotenv）。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("WARNING: python-dotenv 未安装，无法加载 profile env")
        return

    profiles_dir = os.path.join(ROOT_DIR, "data", "profiles")
    env_path = os.path.join(profiles_dir, f"{username.lower()}.env")
    if not os.path.exists(env_path):
        # 兼容大小写
        for entry in os.listdir(profiles_dir) if os.path.isdir(profiles_dir) else []:
            if entry.lower() == f"{username.lower()}.env":
                env_path = os.path.join(profiles_dir, entry)
                break
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)


def main() -> int:
    args = parse_args()
    username = args.user
    _load_profile_env(username)
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
        client = init_maimemo_client()
        if client is None or not remaining:
            print("跳过 Phase 2")
            print()
            print("=== Summary ===")
            print(f"Total conflicts: {len(conflicts)}")
            print(f"Fixed (Phase 1): {fixed_p1}")
            print(f"Fixed (Phase 2): 0")
            print(f"Still conflicting: {len(remaining)}")
            return 0

        fixed_p2 = run_phase2(
            conn, client, remaining, dry_run=args.dry_run, verbose=args.verbose
        )
        if not args.dry_run:
            conn.commit()
        print(f"Phase 2 结果: {fixed_p2} 已修复, {len(remaining) - fixed_p2} 仍冲突")
        print()

        print("=== Summary ===")
        print(f"Total conflicts: {len(conflicts)}")
        print(f"Fixed (Phase 1): {fixed_p1}")
        print(f"Fixed (Phase 2): {fixed_p2}")
        print(f"Still conflicting: {len(remaining) - fixed_p2}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
