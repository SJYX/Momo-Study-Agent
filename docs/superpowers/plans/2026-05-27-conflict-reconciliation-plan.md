# Conflict Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a CLI diagnostic script that reconciles all `sync_status=2` (CONFLICT) records by comparing local vs cloud content and auto-fixing false positives.

**Architecture:** Two-phase approach — Phase 1 (local-only, zero API cost) fixes stuck conflicts where `last_synced_content == basic_meanings`. Phase 2 calls Maimemo API for remaining conflicts using existing `_classify_interpretation_list` similarity logic.

**Tech Stack:** Python 3.12, sqlite3 (direct connection), argparse, existing `core/maimemo_api.py::MaiMemoAPI`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `tools/reconcile_conflicts.py` | CREATE | Main script: CLI args, both phases, output |
| `tests/unit/tools/test_reconcile_conflicts.py` | CREATE | Unit tests for comparison helpers |

No production code changes — this is a standalone diagnostic tool.

---

## Task 1: Create the CLI skeleton and argument parsing

**Files:**
- Create: `tools/reconcile_conflicts.py`

- [ ] **Step 1: Write the file skeleton with argparse CLI**

```python
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
from typing import Any, Dict, List, Optional, Tuple

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


def main() -> int:
    args = parse_args()
    # TODO: implement phases
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify the script is importable and help works**

Run: `python -m tools.reconcile_conflicts --help`
Expected: Shows the help text with all three flags.

- [ ] **Step 3: Commit**

```bash
git add tools/reconcile_conflicts.py
git commit -m "feat(tools): add reconcile_conflicts CLI skeleton"
```

---

## Task 2: Implement DB connection helper and conflict query

**Files:**
- Modify: `tools/reconcile_conflicts.py`

- [ ] **Step 1: Add DB path resolution and conflict query functions**

Add these functions to the file after the imports:

```python
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


def get_conflict_records(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """查询所有 sync_status=2 的记录。"""
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT voc_id, spelling, basic_meanings, last_synced_content, "
        "content_origin, match_confidence, match_reason "
        "FROM ai_word_notes WHERE sync_status = 2"
    )
    return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 2: Test with a real DB (dry run)**

Run: `python -m tools.reconcile_conflicts --user <username> --dry-run`
Expected: Script connects to DB and prints "Found N conflict records" (or "0 conflict records" if none exist). No errors.

- [ ] **Step 3: Commit**

```bash
git add tools/reconcile_conflicts.py
git commit -m "feat(tools): add DB connection and conflict query helpers"
```

---

## Task 3: Implement Phase 1 — local comparison

**Files:**
- Modify: `tools/reconcile_conflicts.py`

- [ ] **Step 1: Add the normalization and comparison logic**

```python
def _normalize(text: str) -> str:
    """标准化文本：去空白，用于比较。"""
    return "".join(str(text or "").split())


def run_phase1(
    conn: sqlite3.Connection,
    conflicts: List[Dict[str, Any]],
    *,
    dry_run: bool = False,
    verbose: bool = False,
) -> Tuple[int, List[Dict[str, Any]]]:
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
```

- [ ] **Step 2: Wire Phase 1 into main()**

Update `main()` to:

```python
def main() -> int:
    args = parse_args()
    username = args.user
    db_path = resolve_db_path(username)

    print(f"=== Conflict Reconciliation ===")
    print(f"User: {username}")
    print(f"DB: {db_path}")
    print()

    conn = sqlite3.connect(db_path)
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

        # Phase 2 placeholder
        if args.phase1_only:
            print("=== Summary (Phase 1 only) ===")
            print(f"Total conflicts: {len(conflicts)}")
            print(f"Fixed (Phase 1): {fixed_p1}")
            return 0

        # TODO: Phase 2
        print(f"--- Phase 2: Maimemo API 比较 ---")
        print("(Phase 2 尚未实现)")
        return 0
    finally:
        conn.close()
```

- [ ] **Step 3: Test Phase 1 against a test database**

Create a quick test:

```bash
python -c "
import sqlite3, os
db = 'data/test-reconcile.db'
conn = sqlite3.connect(db)
conn.execute('''CREATE TABLE IF NOT EXISTS ai_word_notes (
    voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT,
    last_synced_content TEXT, sync_status INTEGER DEFAULT 0,
    match_confidence REAL, match_reason TEXT, updated_at TEXT
)''')
# Insert test data: one matching, one not matching, one missing last_synced
conn.execute(\"INSERT OR REPLACE INTO ai_word_notes VALUES ('v1', 'abandon', '放弃', '放弃', 2, NULL, NULL, NULL)\")
conn.execute(\"INSERT OR REPLACE INTO ai_word_notes VALUES ('v2', 'zeal', '热情', '热心', 2, NULL, NULL, NULL)\")
conn.execute(\"INSERT OR REPLACE INTO ai_word_notes VALUES ('v3', 'hello', '你好', NULL, 2, NULL, NULL, NULL)\")
conn.commit()
conn.close()
print('Test DB created')
"
```

Run: `python -m tools.reconcile_conflicts --user reconcile --dry-run -v`
Expected output:
```
=== Conflict Reconciliation ===
User: reconcile
DB: data/history-reconcile.db

--- Phase 1: 本地比较 ---
发现 3 条冲突记录
  [DRY]   voc_id=v1 "abandon" — 本地匹配，可修复为 sync_status=1
  [KEEP]  voc_id=v2 "zeal" — 内容不同，需 Phase 2
  [SKIP]  voc_id=v3 "hello" — last_synced_content 为空
Phase 1 结果: 1 已修复, 2 需要 API 检查
```

- [ ] **Step 4: Commit**

```bash
git add tools/reconcile_conflicts.py
git commit -m "feat(tools): implement Phase 1 local comparison for conflict reconciliation"
```

---

## Task 4: Implement Phase 2 — Maimemo API comparison

**Files:**
- Modify: `tools/reconcile_conflicts.py`

- [ ] **Step 1: Add the Maimemo client initialization helper**

```python
def init_maimemo_client() -> Optional[Any]:
    """从 profile env 加载 MOMO_TOKEN 并初始化 MaiMemoAPI 客户端。"""
    from core.maimemo_api import MaiMemoAPI

    token = os.getenv("MOMO_TOKEN")
    if not token:
        print("WARNING: MOMO_TOKEN 未设置，跳过 Phase 2（Maimemo API 比较）")
        return None
    return MaiMemoAPI(token)
```

- [ ] **Step 2: Add Phase 2 implementation**

```python
def run_phase2(
    conn: sqlite3.Connection,
    client: Any,
    remaining: List[Dict[str, Any]],
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
                print(f"  [SKIP]  voc_id={voc_id} \"{spelling}\" — basic_meanings 为空")
            continue

        # 进度输出（每 50 条）
        if (i + 1) % 50 == 0 or verbose:
            print(f"  进度: {i + 1}/{total}")

        try:
            res = client.list_interpretations(voc_id)
        except Exception as e:
            if verbose:
                print(f"  [ERROR] voc_id={voc_id} \"{spelling}\" — API 调用失败: {e}")
            continue

        # 用 MaiMemoAPI 内部方法比较
        info = client._classify_interpretation_list(res, expected_text=basic)
        cloud_status = info.get("sync_status", 0)
        confidence = info.get("match_confidence")
        reason = info.get("reason", "")

        if cloud_status == 1:
            # 匹配成功
            if dry_run:
                print(f"  [DRY]   voc_id={voc_id} \"{spelling}\" — 云端匹配 (confidence={confidence})")
            else:
                conn.execute(
                    "UPDATE ai_word_notes SET sync_status = 1, "
                    "match_confidence = ?, match_reason = ?, "
                    "updated_at = datetime('now') WHERE voc_id = ?",
                    (confidence, f"api_{reason}", voc_id),
                )
                if verbose:
                    print(f"  [SYNCED] voc_id={voc_id} \"{spelling}\" — 云端匹配 (confidence={confidence})")
            fixed += 1
        else:
            if verbose:
                print(f"  [CONFLICT] voc_id={voc_id} \"{spelling}\" — 云端不同 (confidence={confidence})")

        # 频控：每次 API 调用后等待 0.3s
        time.sleep(0.3)

    return fixed
```

- [ ] **Step 3: Wire Phase 2 into main()**

Replace the Phase 2 placeholder in `main()` with:

```python
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
```

- [ ] **Step 4: Test with --dry-run against real DB**

Run: `python -m tools.reconcile_conflicts --user <username> --dry-run -v`
Expected: Phase 1 runs instantly. Phase 2 calls Maimemo API for each remaining conflict, prints [DRY]/[CONFLICT] for each.

- [ ] **Step 5: Commit**

```bash
git add tools/reconcile_conflicts.py
git commit -m "feat(tools): implement Phase 2 Maimemo API comparison for conflict reconciliation"
```

---

## Task 5: Add unit tests for comparison helpers

**Files:**
- Create: `tests/unit/tools/test_reconcile_conflicts.py`

- [ ] **Step 1: Write unit tests**

```python
"""tests: reconcile_conflicts comparison helpers."""
import pytest
from tools.reconcile_conflicts import _normalize


class TestNormalize:
    def test_empty_string(self):
        assert _normalize("") == ""

    def test_none_input(self):
        assert _normalize(None) == ""

    def test_whitespace_collapsed(self):
        assert _normalize("hello  world\t\nfoo") == "helloworldfoo"

    def test_identical_after_normalization(self):
        assert _normalize("放弃") == _normalize(" 放  弃 ")

    def test_different_content(self):
        assert _normalize("热情") != _normalize("热心")
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/unit/tools/test_reconcile_conflicts.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/tools/test_reconcile_conflicts.py
git commit -m "test(tools): add unit tests for reconcile_conflicts helpers"
```

---

## Verification

After all tasks complete:

1. `python -m py_compile tools/reconcile_conflicts.py` — syntax check passes
2. `pytest tests/unit/tools/test_reconcile_conflicts.py -v` — all unit tests pass
3. `python -m tools.reconcile_conflicts --help` — shows correct CLI help
4. `python -m tools.reconcile_conflicts --user <test_user> --dry-run -v` — runs both phases without errors
