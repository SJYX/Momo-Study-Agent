# V007 Corruption Fix + Format Detection Design

## Context

用户删除本地 db 后运行 `python scripts/start_web.py`，pyturso 自动从远端 pull 数据库，但拉下来的 .db 文件直接损坏。根因是 V007 migration 的 `_preinit_schema()` 在 pyturso bootstrap 之前创建了不一致的本地 schema，以及格式检测逻辑存在缺陷。

## Root Causes

### RC1: `_preinit_schema()` 在 pyturso bootstrap 前创建冲突 schema

V007 `_preinit_schema()` 用硬编码的表定义创建本地 .db，然后 pyturso.connect() 尝试从远端 bootstrap 到一个非空库。问题：

- `processed_words` 表使用 `spell` 列，而 `_create_tables()` 使用 `spelling`
- 表结构既不匹配远端 schema，也不匹配 V001-V005 迁移后的最终 schema
- pyturso 的 `bootstrap_if_empty=True` 可能因为本地已有数据而跳过 bootstrap，或在 bootstrap 时产生冲突

### RC2: 无 sidecar 时格式检测不可靠

`_detect_format()` 在 .db 存在但 sidecar 不存在时，只要文件是有效 SQLite 就返回 `"turso_sync"`。如果这是一个残留的/损坏的 libsql ER 文件，会被错误当作 pyturso 格式。

### RC3: PytursoBackend 缺少 sidecar 清理

`LibsqlBackend.connect()` 调用了 `_cleanup_stale_sidecars()`，但 `PytursoBackend.connect()` 没有。残留 sidecar 会导致格式检测误判。

### RC4: `_create_tables()` 和 `_preinit_schema()` schema 不一致

`_create_tables()` 包含 V002-V005 的列（`match_confidence`, `last_synced_content`, `is_customized` 等），直接写在 CREATE TABLE 里。V007 `_preinit_schema()` 的定义不同。

## Design

### Principle

**pyturso bootstrap 前不预建任何表。远端 schema 是 SSoT。** V001-V005 在 bootstrap 后运行，作为远端 schema 的补充。如果远端已是最新，它们全部是 no-op。

### Change 1: V007 `_detect_format()` — 修复无 sidecar 场景

```python
def _detect_format(db_path: str) -> str:
    if not os.path.exists(db_path):
        return "no_file"

    sidecar_path = db_path + "-info"
    has_sidecar = os.path.exists(sidecar_path)

    if has_sidecar:
        try:
            with open(sidecar_path, "rb") as f:
                sidecar_text = f.read(4096).decode("utf-8", errors="replace")
            if "turso-sync-py" in sidecar_text:
                return "turso_sync"
        except OSError:
            pass
        return "libsql_embedded_replica"

    # 无 sidecar → 无法确定格式，不应冒险当作 turso_sync
    return "unknown"
```

关键变化：删除原来 "valid SQLite → turso_sync" 的判断。无 sidecar 一律返回 `"unknown"`。

### Change 2: V007 `_migrate_libsql_to_turso()` — 删除 `_preinit_schema()`

```python
def _migrate_libsql_to_turso(db_path: str) -> str:
    """备份旧文件 + 删除所有 libsql ER 文件。让 pyturso 从远端 bootstrap。"""
    backup_path = db_path + ".pre_pyturso.bak"
    shutil.copy2(db_path, backup_path)

    for suffix in ("", "-info", "-wal", "-shm"):
        target = db_path + suffix
        if os.path.exists(target):
            try:
                os.remove(target)
            except OSError:
                pass

    return backup_path
    # 不再调用 _preinit_schema()
```

### Change 3: V007 `pre_connect_migrate()` — `"unknown"` 走重建路径

```python
def pre_connect_migrate(db_path: str) -> dict:
    fmt = _detect_format(db_path)

    if fmt == "no_file":
        return {"action": "no_file", "backup": None, "format": fmt}

    if fmt == "turso_sync":
        return {"action": "skipped", "backup": None, "format": fmt}

    # libsql_embedded_replica 或 unknown → 备份 + 删除，让 pyturso 从远端重新拉
    if fmt in ("libsql_embedded_replica", "unknown"):
        backup = _migrate_libsql_to_turso(db_path)
        return {"action": "migrated", "backup": backup, "format": fmt}

    return {"action": "skipped", "backup": None, "format": fmt}
```

### Change 4: `PytursoBackend.connect()` — 加 sidecar 清理

在 V007 之前加 `_cleanup_stale_sidecars()` 调用：

```python
def connect(self, db_path, url, token, *, do_sync=False):
    ...
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    # 清理残留 sidecar（.db 不存在时）
    if not os.path.exists(db_path):
        from database.utils import _cleanup_stale_sidecars
        _cleanup_stale_sidecars(os.path.abspath(db_path))

    # V007 格式迁移
    ...
```

### Change 5: 删除 `_preinit_schema()` 函数

整个 `_preinit_schema()` 函数从 V007_migrate_db_format.py 中移除。它是 corruption 的直接原因，删除后 schema 一致性问题自动消除。

### Change 6: 删除 V007 `apply()` 中的过时逻辑

V007 `apply()` 是 legacy 入口点，当前只打印警告。清理为简单的 no-op。

## Out of Scope

- V001-V005 保留不动（幂等，安全）
- Runner 框架保留不动
- Backend 选择逻辑不变（pyturso 优先）
- `_create_tables()` 保持不变（schema 正确）
- 不添加新的 libsql → pyturso 迁移逻辑（V007 的 pre_connect_migrate 已覆盖）

## Verification

1. 删除本地 db + sidecar → 启动 → pyturso 从远端 bootstrap → V001-V005 no-op → 正常运行
2. 残留 libsql ER sidecar 但无 .db → V007 清理 → pyturso 从远端 bootstrap
3. 残留损坏的 .db + sidecar → V007 备份 + 删除 → pyturso 从远端 bootstrap
4. 已有 pyturso 格式 .db → V007 跳过 → 正常连接
5. 运行 `python -m pytest tests/ -v --tb=short -m "not slow"` 通过
6. 运行 `python -m py_compile database/migrations/V007_migrate_db_format.py` 无语法错误
