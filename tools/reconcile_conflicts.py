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
