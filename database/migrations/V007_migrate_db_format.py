"""
V007_migrate_db_format.py: Migrate .db from libSQL format to pyturso-compatible format.

Strategy:
  1. Detect format (try turso.sync.connect)
  2. If compatible → no-op
  3. If not → export-import (iterdump with internal table filter + foreign key guard)
"""
from __future__ import annotations
import os
import shutil
import sqlite3
from typing import Any

# SQLite 内部表前缀，iterdump 时过滤
INTERNAL_PREFIXES = ("sqlite_sequence", "_litestream_", "sqlite_")


def _detect_format(db_path: str) -> str:
    """探测 .db 文件是否兼容 pyturso。"""
    try:
        import turso.sync
        db = turso.sync.connect(db_path)
        db.close()
        return "turso_sync"
    except Exception:
        return "libsql_embedded_replica"


def _migrate_libsql_to_turso(db_path: str) -> str:
    """将 libSQL 格式 .db 转换为 pyturso 兼容格式。

    Returns: backup_path
    """
    import turso.sync

    # 1. 备份
    backup_path = db_path + ".pre_pyturso.bak"
    shutil.copy2(db_path, backup_path)

    # 2. 用标准 sqlite3 导出，过滤内部表
    conn_old = sqlite3.connect(db_path)
    dump_path = db_path + ".dump.sql"
    with open(dump_path, "w") as f:
        for line in conn_old.iterdump():
            if any(f'"{p}"' in line or f" {p} " in line for p in INTERNAL_PREFIXES):
                continue
            f.write(line + "\n")
    conn_old.close()
    del conn_old  # 显式释放，防止 Windows 下 SQLite 文件句柄延迟释放

    # 3. 用 pyturso 创建新库并导入（关闭外键避免子表先于父表导入）
    import time
    for attempt in range(3):
        try:
            os.remove(db_path)
            break
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.5)  # Windows 句柄释放重试
    db_new = turso.sync.connect(db_path)
    db_new.execute("PRAGMA foreign_keys=OFF;")
    with open(dump_path, "r") as f:
        db_new.executescript(f.read())
    db_new.execute("PRAGMA foreign_keys=ON;")
    db_new.close()

    # 4. 清理临时文件
    os.remove(dump_path)
    return backup_path


def apply(cur: Any) -> None:
    """Run V007 migration. Detects format and migrates if needed."""
    # 获取 db_path 从 cursor 的 connection
    db_path = None
    try:
        row = cur.execute("PRAGMA database_list").fetchone()
        if row:
            db_path = row[2]  # file path
    except Exception:
        pass

    if not db_path or not os.path.exists(db_path):
        return

    fmt = _detect_format(db_path)
    if fmt == "turso_sync":
        return  # 已兼容，无需迁移

    backup = _migrate_libsql_to_turso(db_path)
    print(f"V007: Migrated {db_path} from libSQL to turso_sync format. Backup: {backup}")
