"""
database/migrations/: SQLite/libsql user_version 迁移框架。

设计原则：
1. **每个版本一个文件**：`V001_xxx.py` / `V002_xxx.py`，文件名前缀决定顺序。
2. **每个版本只暴露 `apply(cursor)` 函数**：runner 在事务中调用，失败回滚。
3. **目标版本号 = 最大已知 V 文件号**：runner 自动发现，不需要中央注册表。
4. **存量 DB 标签**：runner 启动若发现 `user_version=0` 且核心表已存在
   （历史上靠 `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE` 维护的库），
   直接 `PRAGMA user_version=1`，**不重跑** V001（避免 ALTER 重复）。
5. **Replica 策略**：仅在写连接（singleton）跑迁移；PRAGMA user_version 通过 libsql sync
   传播到本地副本与其他客户端。读连接绝不跑迁移。
"""
from __future__ import annotations

from .runner import (
    MigrationError,
    _NeedCloudMigrations,
    apply_migrations,
    current_version,
    target_version,
)

__all__ = [
    "MigrationError",
    "_NeedCloudMigrations",
    "apply_migrations",
    "current_version",
    "target_version",
]
