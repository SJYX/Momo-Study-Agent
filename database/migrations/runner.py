"""
database/migrations/runner.py: 迁移 runner。

版本追踪策略（Phase 6.2 enhanced）：
- **主存储**：``system_config`` 表中 ``key='schema_version'`` 的行。
  此表通过 libsql sync 在所有客户端间同步，是跨设备的 SSoT。
- **兼容回退**：首次读取时若 system_config 无 schema_version 行，
  尝试读 ``PRAGMA user_version``（旧代码遗留值），写入 system_config 后废弃。
- ``PRAGMA user_version`` 不再用于版本追踪（Turso 云端禁止此语句）。

多客户端安全：
- DDL/DML 在主连接上执行（云端 libsql 支持 ALTER TABLE / UPDATE）。
- 版本号写入 system_config 表，通过 libsql sync 传播到所有客户端。
- 新设备启动时读到云端已有的 schema_version → 跳过已执行的迁移。
- 所有迁移文件幂等，多客户端重复执行安全。
"""
from __future__ import annotations

import importlib
import os
import re
import time
from typing import Any, Callable, List, Optional, Tuple

_MIGRATION_PATTERN = re.compile(r"^V(\d{3})_[a-zA-Z0-9_]+\.py$")
_VERSION_KEY = "schema_version"


class MigrationError(RuntimeError):
    """迁移过程中的所有错误统一抛此类型，便于上层区分。"""


# ── 版本读写（基于 system_config 表） ──────────────────────────────


def _read_schema_version(cur: Any) -> int:
    """从 system_config 表读取 schema_version。

    回退链：system_config → PRAGMA user_version（兼容旧库） → 0。
    """
    # 优先从 system_config 读取（通过 libsql 同步）
    try:
        cur.execute(
            f"SELECT value FROM system_config WHERE key = '{_VERSION_KEY}'"
        )
        row = cur.fetchone()
        if row is not None:
            val = row[0] if not isinstance(row, dict) else row.get("value", "0")
            return int(val or 0)
    except Exception:
        pass

    # 回退：尝试 PRAGMA user_version（旧代码遗留，本地文件才有意义）
    try:
        cur.execute("PRAGMA user_version")
        row = cur.fetchone()
        if row is not None:
            val = row[0] if not isinstance(row, dict) else row.get("user_version", 0)
            v = int(val or 0)
            if v > 0:
                return v
    except Exception:
        pass

    return 0


def _write_schema_version(cur: Any, conn: Any, version: int) -> None:
    """写入 schema_version 到 system_config 表（幂等 upsert）。"""
    cur.execute(
        f"INSERT OR REPLACE INTO system_config (key, value, updated_at) "
        f"VALUES ('{_VERSION_KEY}', '{version}', CURRENT_TIMESTAMP)"
    )
    conn.commit()


def _is_pragma_rejected(error: Exception) -> bool:
    """检测 Turso 等云端数据库拒绝 PRAGMA 写操作的错误。"""
    msg = str(error or "").lower()
    return "pragma" in msg and ("not allowed" in msg or "sql_parse_error" in msg)


def _is_wal_conflict(error: Exception) -> bool:
    """检测 libsql 嵌入式副本在 commit 时的云端同步冲突。

    WalConflict 表示 DDL/DML 已在本地成功应用，但同步到云端时遇到冲突。
    此时不应 rollback（会丢失本地变更），应继续写版本号。
    """
    msg = str(error or "").lower()
    return "walconflict" in msg or "wal frame insert conflict" in msg


# ── 迁移发现与加载 ─────────────────────────────────────────────


def _discover_migrations() -> List[Tuple[int, str]]:
    """扫描本包目录返回 [(version, module_name), ...]，按 version 升序。"""
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    out: List[Tuple[int, str]] = []
    for fname in os.listdir(pkg_dir):
        m = _MIGRATION_PATTERN.match(fname)
        if not m:
            continue
        version = int(m.group(1))
        module_name = fname[:-3]  # strip .py
        out.append((version, module_name))
    out.sort()
    return out


def _load_apply(module_name: str) -> Callable[[Any], None]:
    full = f"database.migrations.{module_name}"
    try:
        mod = importlib.import_module(full)
    except Exception as e:
        raise MigrationError(f"无法导入迁移模块 {full}: {e}") from e
    apply = getattr(mod, "apply", None)
    if not callable(apply):
        raise MigrationError(f"迁移模块 {full} 缺少 callable 'apply(cur)'")
    return apply


def target_version() -> int:
    """已知迁移中的最高版本号；空目录返回 0。"""
    migrations = _discover_migrations()
    return migrations[-1][0] if migrations else 0


def current_version(cur: Any) -> int:
    """返回 DB 当前 schema_version（优先 system_config，回退 PRAGMA）。"""
    return _read_schema_version(cur)


# ── 主入口 ─────────────────────────────────────────────────────


def apply_migrations(
    conn: Any,
    *,
    lock: Any = None,
    local_conn: Optional[Any] = None,
) -> Tuple[int, int]:
    """从 current_version 推进到 target_version。

    返回 (start_version, end_version)。可在锁外调用——会自动 acquire 提供的 lock。

    Args:
        conn: 主连接（云端 libsql 或本地 sqlite3）。DDL/DML 在此连接上执行。
        lock: 可选的并发锁（如 _main_write_conn_op_lock）。
        local_conn: 本地 sqlite3 连接（保留兼容，版本追踪已迁移到 system_config）。

    多客户端安全：
    - 版本号存储在 system_config 表（libsql 同步），设备间共享状态。
    - DDL/DML 在 conn 上执行（Turso 支持 ALTER TABLE / UPDATE）。
    - 每个迁移独立事务，DDL/DML 和版本更新分离。
    - 所有迁移文件幂等，多客户端重复执行安全。
    """
    from database.utils import _debug_log

    cur = conn.cursor()

    def _do() -> Tuple[int, int]:
        _t_all = time.time()

        _t_ver = time.time()
        start = _read_schema_version(cur)
        target = target_version()
        _debug_log(f"[迁移] 当前版本 v{start}，目标版本 v{target}", start_time=_t_ver, level="INFO", module="database.migrations")
        if start >= target:
            _debug_log(f"[迁移] v{start} 已是最新，跳过", module="database.migrations")
            return start, start

        migrations = [(v, m) for v, m in _discover_migrations() if v > start]
        total = len(migrations)
        _debug_log(f"[迁移] 需执行 {total} 个迁移: {[m for _, m in migrations]}", level="INFO", module="database.migrations")

        for i, (version, module_name) in enumerate(migrations, 1):
            _debug_log(f"[迁移] ({i}/{total}) V{version:03d} 开始…", level="INFO", module="database.migrations")
            apply_fn = _load_apply(module_name)

            # Phase 1: DDL/DML 在主连接上执行
            _t_ddl = time.time()
            try:
                cur.execute("BEGIN IMMEDIATE")
                apply_fn(cur)
                conn.commit()
                _debug_log(f"[迁移] ({i}/{total}) V{version:03d} DDL/DML 已提交", start_time=_t_ddl, module="database.migrations")
            except Exception as e:
                if _is_wal_conflict(e):
                    # WalConflict: DDL/DML 已在本地应用，仅云端同步遇到冲突。
                    # 不 rollback——保留本地变更；继续写版本号。
                    _debug_log(
                        f"[迁移] ({i}/{total}) V{version:03d} 云端同步冲突 (WalConflict)，"
                        f"本地 DDL/DML 已保留，跳过云端同步",
                        start_time=_t_ddl,
                        level="WARNING",
                        module="database.migrations",
                    )
                else:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise MigrationError(f"迁移 V{version:03d} ({module_name}) DDL/DML 失败: {e}") from e

            # Phase 2: 版本号写入 system_config（通过 libsql 同步到所有客户端）
            _t_verw = time.time()
            try:
                _write_schema_version(cur, conn, version)
                _debug_log(f"[迁移] ({i}/{total}) V{version:03d} 完成 ✓", start_time=_t_verw, level="INFO", module="database.migrations")
            except Exception as e:
                _debug_log(
                    f"[迁移] ({i}/{total}) V{version:03d} 版本写入失败: {e}，DDL/DML 已提交",
                    start_time=_t_verw,
                    level="WARNING",
                    module="database.migrations",
                )

        _debug_log(f"[迁移] 全部完成: v{start} → v{target}", start_time=_t_all, level="INFO", module="database.migrations")
        return start, target

    if lock is not None:
        with lock:
            return _do()
    return _do()
