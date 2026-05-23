# Phase 1: libsql 残留注释刷新 + 死代码删除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 13 个文件里的 libsql / Embedded Replica 术语注释/docstring 替换为 pyturso 术语,删除 `HAS_LIBSQL` 兼容垫片 + 删除未被产线使用的 `_get_cloud_conn` 函数及其唯一测试。**纯文档与死代码,行为零变化**。

**Architecture:** 7 个独立提交,从 `feat/web-ui` 切出 `refactor/libsql-cleanup-phase1` 分支。每个提交一个逻辑文件组,提交粒度便于 PR review 与单独回滚。

**Tech Stack:** Python 3.12+, pytest, git。无新依赖。

**Reference:** [`docs/superpowers/specs/2026-05-23-libsql-residual-cleanup-design.md`](../specs/2026-05-23-libsql-residual-cleanup-design.md) Phase 1 section.

---

## Task 1: 分支准备

**Files:**
- 无文件修改, 仅 git 操作

- [ ] **Step 1: 切换到 feat/web-ui 并拉最新**

```bash
git checkout feat/web-ui
git pull --ff-only
```

Expected: `Already up to date.` 或 fast-forward 一些 commit。

- [ ] **Step 2: 切出 Phase 1 工作分支**

```bash
git checkout -b refactor/libsql-cleanup-phase1
```

Expected: `Switched to a new branch 'refactor/libsql-cleanup-phase1'`

- [ ] **Step 3: 验证起始状态干净**

```bash
git status
```

Expected: `nothing to commit, working tree clean` (除了无关的 untracked 工件如 `local_test.db-wal`, `temp_inspect.db-*`)

---

## Task 2: 刷新 `database/migrations/` 4 个文件的注释

**Files:**
- Modify: `database/migrations/__init__.py`
- Modify: `database/migrations/V001_initial.py:57`
- Modify: `database/migrations/V007_migrate_db_format.py:10, 173, 195`
- Modify: `database/migrations/runner.py` (8 处)

- [ ] **Step 1: 编辑 `database/migrations/__init__.py`**

把模块 docstring 第 2 行 "SQLite/libsql user_version 迁移框架" 改成 "pyturso (Turso DB) user_version 迁移框架"。

把第 11-12 行的"5. **Replica 策略**"段:
```
5. **Replica 策略**：仅在写连接（singleton）跑迁移；PRAGMA user_version 通过 libsql sync
   传播到本地副本与其他客户端。读连接绝不跑迁移。
```
改成:
```
5. **同步策略**：仅在写连接（singleton）跑迁移；schema_version 通过 pyturso push/pull
   传播到所有客户端。读连接绝不跑迁移。
```

- [ ] **Step 2: 编辑 `database/migrations/V001_initial.py:57`**

把行 57 注释:
```python
        # libsql 以 sequence/dict 返回都可能；统一取第二位 name
```
改成:
```python
        # pyturso 以 sequence/dict 返回都可能；统一取第二位 name
```

- [ ] **Step 3: 编辑 `database/migrations/V007_migrate_db_format.py`**

第 10 行(在 `Strategy:` 列表里):
```
  3. If libsql ER format → backup (rename) + delete → let pyturso bootstrap from remote
```
改成:
```
  3. If libsql ER format (legacy) → backup (rename) + delete → let pyturso bootstrap from remote
```

第 173 行(在 `Actions:` docstring 里):
```
        migrated  — was libsql ER format, backed up + deleted for pyturso bootstrap
```
改成:
```
        migrated  — was libsql ER format (legacy), backed up + deleted for pyturso bootstrap
```

第 195 行(在 `Scenario 3` 注释里):
```python
        # Scenario 3: Old libsql ER whose sidecar was deleted.
```
改成:
```python
        # Scenario 3: Old libsql ER (legacy) whose sidecar was deleted.
```

**注**:V007 是用来清理 libsql 遗留文件的迁移本身,完全去掉 "libsql ER" 字样会让上下文丢失。加 "(legacy)" 表明这是历史兼容,符合 spec 设计。

- [ ] **Step 4: 编辑 `database/migrations/runner.py` 8 处**

逐行替换:

第 6 行:
```python
  此表通过 libsql sync 在所有客户端间同步，是跨设备的 SSoT。
```
→
```python
  此表通过 pyturso push/pull 在所有客户端间同步，是跨设备的 SSoT。
```

第 12 行:
```python
- DDL/DML 在主连接上执行（云端 libsql 支持 ALTER TABLE / UPDATE）。
```
→
```python
- DDL/DML 在主连接上执行（pyturso 远端支持 ALTER TABLE / UPDATE）。
```

第 13 行:
```python
- 版本号写入 system_config 表，通过 libsql sync 传播到所有客户端。
```
→
```python
- 版本号写入 system_config 表，通过 pyturso 同步传播到所有客户端。
```

第 50 行:
```python
    # 优先从 system_config 读取（通过 libsql 同步）
```
→
```python
    # 优先从 system_config 读取（通过 pyturso 同步）
```

第 93 行 (docstring 开头):
```python
    """检测 libsql 嵌入式副本在 commit 时的云端同步冲突。
```
→
```python
    """检测 pyturso 同步连接在 commit 时的云端同步冲突。
```

第 200 行 (函数参数 docstring):
```python
        conn: 主连接（云端 libsql 或本地 sqlite3）。DDL/DML 在此连接上执行。
```
→
```python
        conn: 主连接（pyturso 或本地 sqlite3）。DDL/DML 在此连接上执行。
```

第 204 行:
```python
    - 版本号存储在 system_config 表（libsql 同步），设备间共享状态。
```
→
```python
    - 版本号存储在 system_config 表（pyturso 同步），设备间共享状态。
```

第 278 行:
```python
            # Phase 2: 版本号写入 system_config（通过 libsql 同步到所有客户端）
```
→
```python
            # Phase 2: 版本号写入 system_config（通过 pyturso 同步到所有客户端）
```

- [ ] **Step 5: 验证没有把代码逻辑改坏**

```bash
python -m py_compile database/migrations/__init__.py database/migrations/V001_initial.py database/migrations/V007_migrate_db_format.py database/migrations/runner.py
```

Expected: no output (exit 0)

- [ ] **Step 6: 提交**

```bash
git add database/migrations/
git commit -m "chore(migrations): refresh libsql terminology in migration docs

13 处注释从 'libsql sync' / 'libsql ER format' 更新为 pyturso 术语;
V007 中保留 'libsql ER (legacy)' 标注以保持历史上下文。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 刷新 4 个 repo 文件的注释 (community_lookup, notes_repo, _repo_helpers, momo_words)

**Files:**
- Modify: `database/community_lookup.py:175`
- Modify: `database/notes_repo.py:195, 240`
- Modify: `database/_repo_helpers.py:14, 27`
- Modify: `database/momo_words.py:9`

- [ ] **Step 1: 编辑 `database/community_lookup.py:175`**

```python
    # 3) 云端副本（只查仍缺失项；使用 sqlite3 读取本地副本文件，兼容 libsql ER 和 pyturso 两种格式）
```
→
```python
    # 3) 云端副本（只查仍缺失项；使用 sqlite3 读取本地副本文件，兼容 pyturso 格式）
```

- [ ] **Step 2: 编辑 `database/notes_repo.py:195`**

```python
    except Exception as e:  # noqa: BLE001 - libsql/queue 抛出的非标准异常需兜底
```
→
```python
    except Exception as e:  # noqa: BLE001 - pyturso/queue 抛出的非标准异常需兜底
```

- [ ] **Step 3: 编辑 `database/notes_repo.py:240`**

```python
    except Exception as e:  # noqa: BLE001 - 兜底未知 libsql/队列异常
```
→
```python
    except Exception as e:  # noqa: BLE001 - 兜底未知 pyturso/队列异常
```

- [ ] **Step 4: 编辑 `database/_repo_helpers.py:14`**

```python
    """Extract a scalar from a DB row, supporting raw tuples and named-row objects (libsql/sqlite3)."""
```
→
```python
    """Extract a scalar from a DB row, supporting raw tuples and named-row objects (pyturso/sqlite3)."""
```

- [ ] **Step 5: 编辑 `database/_repo_helpers.py:27`**

```python
    """Convert a DB row to a dict; supports libsql Row, sqlite3.Row, raw tuple, asdict()-able rows."""
```
→
```python
    """Convert a DB row to a dict; supports pyturso Row, sqlite3.Row, raw tuple, asdict()-able rows."""
```

- [ ] **Step 6: 编辑 `database/momo_words.py:9`**

```python
- sync_service.py      Embedded Replica 帧级同步管线
```
→
```python
- sync_service.py      pyturso push/pull 同步管线
```

- [ ] **Step 7: 验证无语法错误**

```bash
python -m py_compile database/community_lookup.py database/notes_repo.py database/_repo_helpers.py database/momo_words.py
```

Expected: no output

- [ ] **Step 8: 提交**

```bash
git add database/community_lookup.py database/notes_repo.py database/_repo_helpers.py database/momo_words.py
git commit -m "chore(database): refresh libsql terminology in repo helpers

6 处注释从 'libsql' 更新为 'pyturso',包括:
- community_lookup 云端副本格式说明
- notes_repo 异常兜底注释
- _repo_helpers Row 类型 docstring
- momo_words 模块结构列表

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 刷新 sync_service / utils / execution_engine 的注释

**Files:**
- Modify: `database/sync_service.py:3, 168, 210, 211`
- Modify: `database/utils.py:77, 478-503, 561`
- Modify: `database/execution_engine.py:25`

- [ ] **Step 1: 编辑 `database/sync_service.py` 顶部 docstring (行 3)**

```python
database/sync_service.py: Embedded Replica 帧级同步管线（主库 + Hub 库）。
```
→
```python
database/sync_service.py: pyturso push/pull 同步管线（主库 + Hub 库）。
```

- [ ] **Step 2: 编辑 `database/sync_service.py:168`**

```python
            "connect": "连接 Embedded Replica 数据库",
```
→
```python
            "connect": "连接 pyturso 同步数据库",
```

- [ ] **Step 3: 编辑 `database/sync_service.py:210`**

```python
            "skip_creds_msg": "跳过 Hub 同步: 云端凭据或 libsql 不可用",
```
→
```python
            "skip_creds_msg": "跳过 Hub 同步: 云端凭据或 pyturso 不可用",
```

- [ ] **Step 4: 编辑 `database/sync_service.py:211`**

```python
            "connect": "连接 Hub Embedded Replica 数据库",
```
→
```python
            "connect": "连接 Hub pyturso 同步数据库",
```

- [ ] **Step 5: 编辑 `database/utils.py:77`**

```python
    """Normalize Turso endpoint to sync_url format expected by libsql."""
```
→
```python
    """Normalize Turso endpoint to libsql:// scheme expected by pyturso."""
```

(注:函数本身名为 `_normalize_turso_url`,返回 `libsql://...` URL,因为 `turso.sync.connect` 接收 libsql:// scheme 后内部自己转 https,所以保留行 81 的 `startswith("libsql://")` 检测和行 83 的 prefix 拼接逻辑不变。)

- [ ] **Step 6: 编辑 `database/utils.py:478`**

```python
    """Remove libsql sidecar files (.db-info, .db-wal, .db-shm) for a missing/broken db.
```
→
```python
    """Remove pyturso sidecar files (.db-info, .db-wal, .db-shm) for a missing/broken db.
```

- [ ] **Step 7: 编辑 `database/utils.py:480-483` (docstring 内连续多行)**

把:
```python
    After the .db file is moved away, stale sidecar files cause libsql to
    believe the local replica is already at the correct version, skipping the
    initial cloud pull and leaving an empty database.  Removing them lets
    libsql re-initialise metadata on next connect.
```
改成:
```python
    After the .db file is moved away, stale sidecar files cause pyturso to
    believe the local DB is already at the correct version, skipping the
    initial cloud bootstrap and leaving an empty database.  Removing them lets
    pyturso re-initialise metadata on next connect.
```

- [ ] **Step 8: 编辑 `database/utils.py:485`**

```python
    # include pyturso/libsql sidecars and both dashed and dotted legacy forms
```
→
```python
    # include pyturso sidecars and both dashed and dotted legacy forms (libsql historic)
```

- [ ] **Step 9: 编辑 `database/utils.py:502-504` (在 `_backup_broken_database_file` docstring 里)**

把:
```python
    Sidecar files (.db-info, .db-wal, .db-shm) must be removed together with
    the .db file; otherwise libsql reads the old version metadata, skips the
    cloud pull, and leaves an empty local database.
```
改成:
```python
    Sidecar files (.db-info, .db-wal, .db-shm) must be removed together with
    the .db file; otherwise pyturso reads the old version metadata, skips the
    cloud bootstrap, and leaves an empty local database.
```

- [ ] **Step 10: 编辑 `database/utils.py:561`**

```python
        # .db 已移走，必须同时清理 sidecar——否则 pyturso/libsql 读到旧元数据
```
→
```python
        # .db 已移走，必须同时清理 sidecar——否则 pyturso 读到旧元数据
```

- [ ] **Step 11: 编辑 `database/execution_engine.py:25`**

```python
# DB 级别的 Embedded Replica 同步状态（供前端展示）
```
→
```python
# DB 级别的同步状态（pyturso push/pull 进行中标志,供前端展示）
```

- [ ] **Step 12: 验证**

```bash
python -m py_compile database/sync_service.py database/utils.py database/execution_engine.py
```

Expected: no output

- [ ] **Step 13: 提交**

```bash
git add database/sync_service.py database/utils.py database/execution_engine.py
git commit -m "chore(database): refresh libsql terminology in sync/utils/exec layer

- sync_service.py: 'Embedded Replica 帧级同步管线' → 'pyturso push/pull 同步管线'
- utils.py: _normalize_turso_url / _cleanup_stale_sidecars / _backup_broken_database_file 7 处 libsql → pyturso
- execution_engine.py: _db_syncing 注释去 'Embedded Replica' 字样

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 刷新 connection.py 顶部 docstring + user_context.py 注释

**Files:**
- Modify: `database/connection.py:1-16` (顶部模块 docstring)
- Modify: `web/backend/user_context.py:291`

- [ ] **Step 1: 编辑 `database/connection.py:7-16`**

把当前的顶部第二个 docstring(行 7-16)替换。当前内容:
```python
"""Database connection infrastructure.

This module centralizes connection lifecycle, background writer/sync daemons,
and Embedded Replica connection rules.

Critical WalConflict rule:
- In Embedded Replica mode, NEVER open extra local read connections via the backend.
- All reads/writes must be funneled through a single process-level singleton
    connection per database file.
"""
```
→
```python
"""Database connection infrastructure.

This module centralizes connection lifecycle, background writer/sync daemons,
and pyturso connection management.

Notes on pyturso semantics:
- pyturso uses MVCC, so multiple read connections to the same DB file are safe.
- The write singleton (`_main_write_conn_singleton`) is retained only for the
  do_sync=True path (init_db + explicit do_sync_on); other write paths open
  a fresh local connection each time via `_get_local_conn`.
"""
```

- [ ] **Step 2: 编辑 `web/backend/user_context.py:291`**

当前(在 `_warmup_sync` 函数末尾):
```python
        # pyturso 不需要 libsql 的 "重建连接" workaround。
```

整行**删除** — 这是 libsql 时代的安抚性注释,删掉后该函数末尾紧跟 `init_concurrent_system()` 调用,语义清晰。

- [ ] **Step 3: 验证**

```bash
python -m py_compile database/connection.py web/backend/user_context.py
```

Expected: no output

- [ ] **Step 4: 提交**

```bash
git add database/connection.py web/backend/user_context.py
git commit -m "chore(database,web): refresh connection.py header + drop stale libsql workaround note

- connection.py: 顶部 docstring 去 'Embedded Replica' / 'WalConflict rule',
  改为 pyturso MVCC 语义的简要说明
- user_context.py: 删除 _warmup_sync 末尾 'pyturso 不需要 libsql workaround' 安抚性注释

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 删除 `HAS_LIBSQL` 兼容垫片

**Files:**
- Modify: `database/backends/__init__.py:10-11`

- [ ] **Step 1: 先确认 0 处 import**

```bash
python -c "import subprocess; r = subprocess.run(['git', 'grep', '-l', 'HAS_LIBSQL'], capture_output=True, text=True); print(r.stdout); exit(0 if 'database/backends/__init__.py' == r.stdout.strip() else 1)"
```

或者直接:

```bash
git grep -l "HAS_LIBSQL"
```

Expected output (and ONLY output):
```
database/backends/__init__.py
```

如果出现其他文件 → STOP,先评估这些文件再继续。

- [ ] **Step 2: 编辑 `database/backends/__init__.py`**

把行 10-11:
```python
# libsql backend removed — kept as False for compatibility during cleanup (Phase 2)
HAS_LIBSQL = False
```

**完全删除** (这两行)。

同时把行 7 上方注释从:
```python
# ── 集中探针：唯一的 HAS_PYTURSO 来源 ──
```
保持不变(还相关)。但下方紧跟着第 10-11 行被删后,可以在 try/except 后面加一行说明:

在原 `HAS_LIBSQL = False` 位置(现在变成空白)放一句:
```python
# libsql backend permanently removed in commit 8d74bb6; pyturso is the only supported backend
```

修改后 `database/backends/__init__.py` 前 13 行应该长这样:
```python
from ._protocol import TursoBackend

# ── 集中探针：唯一的 HAS_PYTURSO 来源 ──
try:
    import turso.sync  # noqa: F401
    HAS_PYTURSO = True
except ImportError:
    HAS_PYTURSO = False

# libsql backend permanently removed in commit 8d74bb6; pyturso is the only supported backend


_backend_singleton: TursoBackend | None = None
```

- [ ] **Step 3: 跑测试套件确认无回归**

```bash
python -m py_compile database/backends/__init__.py
python -m pytest tests/unit/database/ -m "not slow" -q --tb=short 2>&1 | Select-Object -Last 5
```

Expected: all tests pass(预期 161 passed, 6 deselected,或类似)

- [ ] **Step 4: 提交**

```bash
git add database/backends/__init__.py
git commit -m "chore(database): drop unused HAS_LIBSQL = False compat shim

zero importers across the codebase (verified via git grep). Replaced with
a comment explaining libsql backend was permanently removed in 8d74bb6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: 删除 `_get_cloud_conn` 函数及其唯一测试

**Files:**
- Modify: `database/connection.py:559-581` (delete `_get_cloud_conn` function)
- Modify: `tests/integration/database/test_robustness.py:5, 69-89` (delete test + import)

- [ ] **Step 1: 确认产线 0 调用**

```bash
git grep -l "_get_cloud_conn"
```

Expected output:
```
database/connection.py
tests/integration/database/test_robustness.py
```

如果还有第三个文件 → STOP, 重新评估。

- [ ] **Step 2: 删除 `database/connection.py` 中 `_get_cloud_conn` 函数**

定位 `def _get_cloud_conn(url: str, token: str, db_path: str = None, max_retries: int = 3):`(约行 559),把它和它的函数体完整删除,直到下一个 `def` 或顶层定义开始。删除范围大约 23 行。

删除后,该位置上一个定义是 `_get_conn`(从 541 行开始),下一个定义是 `is_hub_configured`(原行 583 附近)。

- [ ] **Step 3: 删除 `tests/integration/database/test_robustness.py` 里的 import 行 5**

```python
from database.connection import _get_cloud_conn
```

**整行删除**。

- [ ] **Step 4: 删除 `tests/integration/database/test_robustness.py:69-89` 里的测试函数**

完整删除从 `def test_db_manager_get_cloud_conn_self_healing_regression(tmp_path, monkeypatch):` 开始的整个测试函数,直到下一个 `def test_` 或 `if __name__` 之前。约 21 行。

删除后该文件末尾应该是:
```python
    assert results[0]["spelling"] == "cherry"
    assert results[1]["spelling"] == "date"

if __name__ == "__main__":
    pytest.main([__file__])
```

- [ ] **Step 5: 验证语法 + 跑测试**

```bash
python -m py_compile database/connection.py tests/integration/database/test_robustness.py
python -m pytest tests/unit/database/ tests/integration/database/test_robustness.py -m "not slow" -q --tb=short 2>&1 | Select-Object -Last 10
```

Expected: all pass; `test_robustness.py` 应该少一个测试用例但其余通过。

- [ ] **Step 6: 提交**

```bash
git add database/connection.py tests/integration/database/test_robustness.py
git commit -m "chore(database): drop unused _get_cloud_conn + its only test

_get_cloud_conn was a libsql-era 'Embedded Replica connection' compat
helper. Zero production callers (verified via git grep). The single
integration test (test_db_manager_get_cloud_conn_self_healing_regression)
tested libsql self-healing semantics that don't exist in pyturso.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: 最终验证 + 推送 + 开 PR

**Files:**
- 无文件修改

- [ ] **Step 1: 跑完整测试套件 (允许 slow tests 被跳过)**

```bash
python -m pytest tests/ -m "not slow" -q --tb=short 2>&1 | Select-Object -Last 15
```

Expected: all pass (或者只剩与 libsql 无关的预存在 flaky)

- [ ] **Step 2: grep 审计 — 期望剩余命中只在 V007 + scripts/archived + 测试 URL 字面量**

```bash
git grep -l -i "libsql\|embedded replica" -- "*.py" | Where-Object { $_ }
```

允许命中的文件:
- `database/migrations/V007_migrate_db_format.py` (legacy 标注)
- `scripts/archived/migrate_turso_cloud_db.py` (归档脚本)
- `scripts/migrate_turso_db_group.py` (DB 组迁移脚本,libsql:// URL scheme)
- `scripts/setup_test_databases.py` (libsql:// URL scheme)
- `scripts/validate_pyturso_compat.py` (兼容性验证,引用 libsql 作为对比)
- `database/utils.py:81-83` (`_normalize_turso_url` 检测 libsql:// scheme — 必须保留)
- 测试文件中字面 `libsql://fake.turso.io` URL 示例

如果发现任何**业务代码**(`database/`/`web/`/`core/` 顶层)里还有 "libsql" 或 "embedded replica" 字样 → 那就是漏了,补一个 commit。

- [ ] **Step 3: 总览看 commit 历史**

```bash
git log --oneline feat/web-ui..HEAD
```

Expected: 6 个 commits(Task 2-7 各一个),从 Task 2 的 migrations 到 Task 7 的 _get_cloud_conn 删除。

- [ ] **Step 4: 推送分支**

```bash
git push -u origin refactor/libsql-cleanup-phase1
```

- [ ] **Step 5: 开 PR**

```bash
gh pr create --title "chore(database): refresh libsql residual comments + drop dead compat shims (Phase 1)" --body "$(cat <<'EOF'
## Summary

Phase 1 of libsql residual cleanup. See [design spec](docs/superpowers/specs/2026-05-23-libsql-residual-cleanup-design.md) for full context.

- 13 个文件的注释/docstring 把 `libsql` / `Embedded Replica` 术语更新为 pyturso
- 删除 `HAS_LIBSQL = False` 兼容垫片(0 importers)
- 删除 `_get_cloud_conn` 函数(产线 0 调用) + 它唯一的集成测试

**纯文档与死代码,行为零变化。**

## Test plan

- [x] `pytest tests/unit/database/` 161 通过
- [x] `pytest tests/` 全套通过(除预存在的无关 flaky)
- [x] `git grep -i "libsql\|embedded replica" -- '*.py'` 剩余命中仅在 V007/archived/scripts/URL-scheme 检测,业务代码 0 命中

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL 输出。

---

## Phase 1 完成检查清单

- [ ] 所有 6 个 task 提交都在 `refactor/libsql-cleanup-phase1` 分支上
- [ ] `pytest tests/` 全套通过
- [ ] `git grep -i "libsql\|embedded replica" -- "*.py"` 业务代码命中数为 0
- [ ] PR 已开,review 通过后 squash-merge 回 `feat/web-ui`

Phase 1 落地后即可开始 Phase 2(plan 在 `docs/superpowers/plans/2026-05-23-libsql-cleanup-phase2.md`)。
