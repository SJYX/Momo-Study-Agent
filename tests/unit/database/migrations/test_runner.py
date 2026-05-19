"""tests/unit/database/migrations/test_runner.py: system_config 版本追踪测试。"""
from __future__ import annotations

import sqlite3

import pytest

from database.migrations import apply_migrations, current_version, target_version
from database.migrations.runner import MigrationError


def _fresh_db():
    """In-memory SQLite, 建好 system_config 表模拟真实环境。"""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE system_config ("
        "key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP)"
    )
    conn.commit()
    return conn


def _schema_version(conn) -> int:
    """从 system_config 读取 schema_version，与 runner 内部逻辑一致。"""
    cur = conn.cursor()
    cur.execute("SELECT value FROM system_config WHERE key = 'schema_version'")
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row[0] or 0)


def _setup_skeleton(conn):
    """建好 V001 迁移依赖的核心骨架表。"""
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT)"
    )
    cur.execute(
        "CREATE TABLE ai_word_notes ("
        "voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, batch_id TEXT, "
        "it_level INTEGER DEFAULT 0, it_history TEXT, prompt_tokens INTEGER DEFAULT 0, "
        "completion_tokens INTEGER DEFAULT 0, total_tokens INTEGER DEFAULT 0, "
        "original_meanings TEXT, maimemo_context TEXT, content_origin TEXT, "
        "content_source_db TEXT, content_source_scope TEXT, raw_full_text TEXT, "
        "word_ratings TEXT, sync_status INTEGER DEFAULT 0, updated_at TIMESTAMP)"
    )
    conn.commit()


# ── 基础功能 ──────────────────────────────────────────────────


def test_target_version_matches_v005():
    assert target_version() == 5


def test_empty_db_starts_at_v0():
    conn = _fresh_db()
    cur = conn.cursor()
    assert current_version(cur) == 0


def test_apply_migrations_to_empty_db():
    """全新空 DB：建骨架 → 跑迁移 → system_config 中 schema_version=5。"""
    conn = _fresh_db()
    _setup_skeleton(conn)

    start, end = apply_migrations(conn)
    assert start == 0
    assert end == 5
    assert _schema_version(conn) == 5


def test_idempotent_second_run_is_noop():
    conn = _fresh_db()
    _setup_skeleton(conn)

    start1, end1 = apply_migrations(conn)
    start2, end2 = apply_migrations(conn)
    assert start1 == 0 and end1 == 5
    # 第二次跑：current >= target，立即返回
    assert start2 == 5 and end2 == 5


# ── 旧库兼容 ──────────────────────────────────────────────────


def test_legacy_db_without_some_columns_gets_columns_added():
    """模拟 v=0 的旧 DB：核心表存在但缺列。V001 幂等地 ALTER 上去。"""
    conn = _fresh_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT)")
    cur.execute(
        "CREATE TABLE ai_word_notes (voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT)"
    )
    conn.commit()

    apply_migrations(conn)

    # 验证新列被加上了
    cur.execute("PRAGMA table_info(ai_word_notes)")
    cols = {row[1] for row in cur.fetchall()}
    assert "sync_status" in cols
    assert "content_origin" in cols
    assert "updated_at" in cols
    assert "it_level" in cols
    assert "match_confidence" in cols
    assert "match_reason" in cols

    cur.execute("PRAGMA table_info(processed_words)")
    cols2 = {row[1] for row in cur.fetchall()}
    assert "updated_at" in cols2

    assert _schema_version(conn) == 5


# ── 失败回滚 ──────────────────────────────────────────────────


def test_failure_in_migration_stops_at_last_good_version(monkeypatch):
    """V001~V005 成功后追加一个会爆的 V999，版本应停在 5。"""
    import database.migrations.runner as runner_mod

    conn = _fresh_db()
    _setup_skeleton(conn)

    # monkeypatch discover：追加虚构的 V999
    original_discover = runner_mod._discover_migrations

    def patched_discover():
        out = list(original_discover())
        out.append((999, "V999_bad"))
        return out

    def bad_apply(cur):
        raise RuntimeError("intentional")

    original_load = runner_mod._load_apply

    def patched_load(module_name):
        if module_name == "V999_bad":
            return bad_apply
        return original_load(module_name)

    monkeypatch.setattr(runner_mod, "_discover_migrations", patched_discover)
    monkeypatch.setattr(runner_mod, "_load_apply", patched_load)

    with pytest.raises(MigrationError) as ex:
        runner_mod.apply_migrations(conn)
    assert "V999" in str(ex.value)

    # V001~V005 已成功提交，V999 回滚 → schema_version 应停在 5
    assert _schema_version(conn) == 5


def test_ddl_succeeds_even_if_version_write_fails():
    """DDL/DML 应该成功提交，即使 system_config 写入失败。"""
    import database.migrations.runner as runner_mod

    primary_real = _fresh_db()
    _setup_skeleton(primary_real)

    # 拦截 system_config 写入，模拟云端拒绝
    real_cursor = primary_real.cursor()

    class FailingVersionCursor:
        def __init__(self, real_cur):
            self._cur = real_cur

        def execute(self, sql, *args, **kwargs):
            sql_upper = sql.strip().upper()
            # 拦截 schema_version 的 INSERT OR REPLACE
            if "SYSTEM_CONFIG" in sql_upper and "SCHEMA_VERSION" in sql_upper and "INSERT" in sql_upper:
                raise RuntimeError("Simulated: system_config write rejected")
            return self._cur.execute(sql, *args, **kwargs)

        def fetchone(self):
            return self._cur.fetchone()

        def fetchall(self):
            return self._cur.fetchall()

    class WrappedConn:
        def __init__(self, real_conn, cursor_factory):
            self._conn = real_conn
            self._cursor_factory = cursor_factory

        def cursor(self):
            return self._cursor_factory(self._conn.cursor())

        def commit(self):
            self._conn.commit()

        def rollback(self):
            self._conn.rollback()

    wrapped = WrappedConn(primary_real, lambda rc: FailingVersionCursor(rc))

    # DDL 应该成功，即使版本写入失败
    start, end = runner_mod.apply_migrations(wrapped)
    assert start == 0
    assert end == 5

    # DDL 确实已提交
    cur2 = primary_real.cursor()
    cur2.execute("PRAGMA table_info(ai_word_notes)")
    cols = {row[1] for row in cur2.fetchall()}
    assert "match_confidence" in cols
    assert "last_synced_content" in cols


# ── PRAGMA 回退兼容 ───────────────────────────────────────────


def test_pragma_fallback_when_system_config_missing():
    """如果 system_config 表中无 schema_version 但 PRAGMA user_version > 0，
    应回退读取 PRAGMA 值（兼容旧库迁移前的状态）。"""
    conn = sqlite3.connect(":memory:")
    # 不建 system_config 表，直接用 PRAGMA
    cur = conn.cursor()
    cur.execute("PRAGMA user_version = 3")

    from database.migrations.runner import _read_schema_version
    assert _read_schema_version(cur) == 3


def test_system_config_takes_priority_over_pragma():
    """system_config 中的值优先于 PRAGMA user_version。"""
    conn = _fresh_db()
    cur = conn.cursor()
    cur.execute("PRAGMA user_version = 1")
    cur.execute(
        "INSERT INTO system_config (key, value, updated_at) "
        "VALUES ('schema_version', '4', CURRENT_TIMESTAMP)"
    )
    conn.commit()

    from database.migrations.runner import _read_schema_version
    assert _read_schema_version(cur) == 4


# ── WalConflict 处理 ───────────────────────────────────────────


def test_wal_conflict_does_not_rollback_local_dml(monkeypatch):
    """commit() 抛 WalConflict 时，不应 rollback 本地 DDL/DML，应继续写版本号。"""
    import database.migrations.runner as runner_mod

    real_conn = _fresh_db()
    _setup_skeleton(real_conn)

    # 只跑 V001
    original_discover = runner_mod._discover_migrations
    monkeypatch.setattr(
        runner_mod, "_discover_migrations",
        lambda: [(v, m) for v, m in original_discover() if v == 1],
    )

    # 包装连接：第一次 commit 抛 WalConflict，后续 commit 正常
    wal_conflict_raised = False

    class WalConflictConn:
        def __init__(self, real):
            self._real = real

        def cursor(self):
            return self._real.cursor()

        def commit(self):
            nonlocal wal_conflict_raised
            if not wal_conflict_raised:
                wal_conflict_raised = True
                raise RuntimeError(
                    "WalConflict: sync error: WalConflict { frame: 1 }"
                )
            self._real.commit()

        def rollback(self):
            self._real.rollback()

    wrapped = WalConflictConn(real_conn)

    # WalConflict 不应导致 MigrationError
    start, end = runner_mod.apply_migrations(wrapped)
    assert start == 0
    assert end == 1

    # 版本号应该写入成功
    assert _schema_version(real_conn) == 1


def test_non_wal_conflict_still_raises(monkeypatch):
    """非 WalConflict 的 commit 错误仍然应抛 MigrationError。"""
    import database.migrations.runner as runner_mod

    real_conn = _fresh_db()
    _setup_skeleton(real_conn)

    original_discover = runner_mod._discover_migrations
    monkeypatch.setattr(
        runner_mod, "_discover_migrations",
        lambda: [(v, m) for v, m in original_discover() if v == 1],
    )

    class FailingConn:
        def __init__(self, real):
            self._real = real

        def cursor(self):
            return self._real.cursor()

        def commit(self):
            raise RuntimeError("disk I/O error")

        def rollback(self):
            self._real.rollback()

    wrapped = FailingConn(real_conn)

    with pytest.raises(MigrationError, match="disk I/O error"):
        runner_mod.apply_migrations(wrapped)
