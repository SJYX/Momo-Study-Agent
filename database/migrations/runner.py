"""
database/migrations/runner.py: PRAGMA user_version 迁移 runner。

约定：
- 同目录下 `V<NNN>_<slug>.py` 文件视为迁移；NNN 决定顺序，应用后 user_version 设为 NNN。
- 每个迁移模块导出 `apply(cur) -> None`（cursor 由 runner 提供，事务由 runner 管）。
- runner 不读 .py 字节码、不动态 exec：通过 `importlib.import_module` 走正常 import 路径。
- 每个迁移文件**必须幂等**：runner 在 v=0 的存量库上也会跑 V001，所以 V001 必须能
  容忍"列已存在 / 数据已回填"的状态。新加迁移（V002+）也遵守此约定。
"""
from __future__ import annotations

import importlib
import os
import re
from typing import Any, Callable, List, Tuple

_MIGRATION_PATTERN = re.compile(r"^V(\d{3})_[a-zA-Z0-9_]+\.py$")


class MigrationError(RuntimeError):
    """迁移过程中的所有错误统一抛此类型，便于上层区分。"""


def _read_user_version(cur: Any) -> int:
    cur.execute("PRAGMA user_version")
    row = cur.fetchone()
    if row is None:
        return 0
    val = row[0] if not isinstance(row, dict) else row.get("user_version", 0)
    return int(val or 0)


def _write_user_version(cur: Any, version: int) -> None:
    # PRAGMA 不接受参数化绑定，必须字面量拼接；这里 version 来自代码常量 / 已校验过的 int，安全。
    cur.execute(f"PRAGMA user_version = {int(version)}")


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
    """返回 DB 当前 PRAGMA user_version。"""
    return _read_user_version(cur)


def apply_migrations(conn: Any, *, lock: Any = None) -> Tuple[int, int]:
    """从 current_version 推进到 target_version。

    返回 (start_version, end_version)。可在锁外调用——会自动 acquire 提供的 lock。
    若 conn 是 libsql 写单例，lock 应该是 `_main_write_conn_op_lock` 等连接级锁。

    存量库一律走完整迁移链：V001 是幂等的，对 v=0 但表已存在的旧库不会破坏现有数据。
    （之前考虑过 "v=0 且核心表存在 → 直接打标签 v=1 跳过 V001" 的快捷路径，
    但这样会漏掉 V001 中的 backfill UPDATE，所以放弃。）
    """
    cur = conn.cursor()

    def _do() -> Tuple[int, int]:
        start = _read_user_version(cur)
        target = target_version()
        if start >= target:
            return start, start

        migrations = [(v, m) for v, m in _discover_migrations() if v > start]

        for version, module_name in migrations:
            apply_fn = _load_apply(module_name)
            try:
                cur.execute("BEGIN IMMEDIATE")
                apply_fn(cur)
                _write_user_version(cur, version)
                conn.commit()
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise MigrationError(f"迁移 V{version:03d} ({module_name}) 失败: {e}") from e

        return start, target

    if lock is not None:
        with lock:
            return _do()
    return _do()
