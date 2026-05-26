import argparse
import json
import sqlite3
from pathlib import Path


def resolve_db_path(root_dir: Path, user: str, explicit_db: str | None) -> Path:
    if explicit_db:
        p = Path(explicit_db)
        return p if p.is_absolute() else (root_dir / p)
    return root_dir / "data" / f"history-{user}.db"


def query_gap_rows(conn: sqlite3.Connection, spelling: str | None, limit: int) -> list[dict]:
    sql = (
        "SELECT p.voc_id, p.spelling, p.processed_at, p.updated_at "
        "FROM processed_words p "
        "LEFT JOIN ai_word_notes n ON n.voc_id = p.voc_id "
        "WHERE n.voc_id IS NULL "
    )
    params: list[object] = []

    if spelling:
        sql += "AND p.spelling = ? "
        params.append(spelling)

    sql += "ORDER BY p.updated_at DESC LIMIT ?"
    params.append(limit)

    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def repair_gap_rows(
    conn: sqlite3.Connection,
    rows: list[dict],
    *,
    target_status: int,
    reason: str,
) -> int:
    if not rows:
        return 0

    payload = [
        (
            row.get("voc_id"),
            row.get("spelling"),
            target_status,
            reason,
            "repair_gap",
        )
        for row in rows
    ]

    conn.executemany(
        "INSERT OR REPLACE INTO ai_word_notes "
        "(voc_id, spelling, sync_status, match_reason, content_origin, updated_at) "
        "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
        payload,
    )
    return len(payload)


def requeue_ai_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0

    voc_ids = [row.get("voc_id") for row in rows if row.get("voc_id")]
    if not voc_ids:
        return 0

    placeholders = ",".join(["?"] * len(voc_ids))
    conn.execute(f"DELETE FROM processed_words WHERE voc_id IN ({placeholders})", voc_ids)
    return len(voc_ids)


def main() -> int:
    root_dir = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(
        description="Diagnose words that are processed but missing ai_word_notes (cannot be warmup-synced)."
    )
    parser.add_argument("--user", default="asher", help="Target user profile name (default: asher)")
    parser.add_argument("--db", dest="db_path", help="Explicit DB path (optional)")
    parser.add_argument("--spelling", help="Filter a single spelling (optional)")
    parser.add_argument("--limit", type=int, default=100, help="Max rows to return (default: 100)")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Repair gap rows by inserting ai_word_notes with target sync_status.",
    )
    parser.add_argument(
        "--requeue-ai",
        action="store_true",
        help="Requeue gap rows into AI by deleting processed_words markers (become NOT_STARTED).",
    )
    parser.add_argument(
        "--target-status",
        type=int,
        default=1,
        choices=[1, 5],
        help="sync_status to write when --repair is enabled (default: 1).",
    )
    parser.add_argument(
        "--reason",
        default="repaired_missing_note",
        help="match_reason to write when --repair is enabled.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply DB writes. Without this flag, --repair runs as dry-run.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    if args.repair and args.requeue_ai:
        print("--repair and --requeue-ai cannot be used together.")
        return 1

    db_path = resolve_db_path(root_dir, args.user, args.db_path)
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        rows = query_gap_rows(conn, args.spelling, args.limit)
        repaired = 0
        requeued = 0
        dry_run = bool(args.repair and not args.apply)
        requeue_dry_run = bool(args.requeue_ai and not args.apply)
        if args.repair and args.apply:
            repaired = repair_gap_rows(
                conn,
                rows,
                target_status=args.target_status,
                reason=args.reason,
            )
            conn.commit()
        if args.requeue_ai and args.apply:
            requeued = requeue_ai_rows(conn, rows)
            conn.commit()
    finally:
        conn.close()

    result = {
        "db_path": str(db_path),
        "spelling_filter": args.spelling,
        "count": len(rows),
        "rows": rows,
        "repair_requested": bool(args.repair),
        "repair_applied": bool(args.repair and args.apply),
        "repair_dry_run": dry_run if args.repair else False,
        "target_status": args.target_status,
        "repaired_count": repaired if args.repair and args.apply else 0,
        "requeue_requested": bool(args.requeue_ai),
        "requeue_applied": bool(args.requeue_ai and args.apply),
        "requeue_dry_run": requeue_dry_run if args.requeue_ai else False,
        "requeued_count": requeued if args.requeue_ai and args.apply else 0,
    }

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("=" * 72)
    print("Sync Pending Gap Diagnostic")
    print("=" * 72)
    print(f"db: {result['db_path']}")
    print(f"filter: {result['spelling_filter'] or '(none)'}")
    print(f"count: {result['count']}")
    if result["repair_requested"]:
        mode = "apply" if result["repair_applied"] else "dry-run"
        print(
            f"repair: {mode} | target_status={result['target_status']} | repaired={result['repaired_count']}"
        )
    if result["requeue_requested"]:
        mode = "apply" if result["requeue_applied"] else "dry-run"
        print(f"requeue-ai: {mode} | requeued={result['requeued_count']}")
    print("-" * 72)

    if not rows:
        print("No gap rows found.")
        return 0

    for i, row in enumerate(rows, start=1):
        print(
            f"{i:>3}. {row.get('spelling', '')} | voc_id={row.get('voc_id', '')} | "
            f"processed_at={row.get('processed_at', '')} | updated_at={row.get('updated_at', '')}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
