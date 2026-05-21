"""tests/unit/database/test_sync_service_skip_paths.py: 同步管线 skip/error 状态归类。"""
from __future__ import annotations

from database import connection as conn_mod
from database import sync_service
from database.sync_service import (
    _is_cloud_connection_unavailable_error,
    _run_sync_pipeline,
    sync_databases,
    sync_hub_databases,
)


def test_is_cloud_unavailable_recognizes_known_phrases():
    assert _is_cloud_connection_unavailable_error(RuntimeError("Cannot connect to the cloud"))
    assert _is_cloud_connection_unavailable_error(RuntimeError("unable to connect: dns"))
    assert _is_cloud_connection_unavailable_error(RuntimeError("强制云端模式已启用"))


def test_is_cloud_unavailable_rejects_unrelated_errors():
    assert not _is_cloud_connection_unavailable_error(ValueError("bad input"))
    assert not _is_cloud_connection_unavailable_error(RuntimeError("disk corruption"))


def test_sync_databases_skipped_when_no_cloud_credentials(monkeypatch):
    """conftest 已清空 TURSO_DB_URL，sync_databases 应进入 skip 分支。"""
    stats = sync_databases()
    assert stats["status"] == "skipped"
    assert stats["reason"] in {"missing-cloud-credentials", "backend-unavailable"}


def test_sync_hub_databases_skipped_when_no_hub_credentials():
    stats = sync_hub_databases()
    assert stats["status"] == "skipped"
    assert stats["reason"] in {"missing-hub-cloud-credentials", "backend-unavailable"}


def test_run_sync_pipeline_returns_skip_on_cloud_unavailable():
    """如果 conn_factory 抛出云端不可用异常，pipeline 应返回 status=skipped/cloud-unavailable。"""
    def boom():
        raise RuntimeError("Cannot connect to the cloud (mock)")

    stats = _run_sync_pipeline(
        creds_ok=True,
        creds_skip_reason="",
        conn_factory=boom,
        dry_run=False,
        progress_callback=None,
        messages={
            "skip_creds_msg": "skip", "connect": "c", "cloud_unavail_skip_prefix": "skip",
            "sync_doing": "s", "local_only": "l", "done": "d",
            "error_log_prefix": "err", "error_progress_prefix": "err",
        },
        skip_reason_local_only="local-only",
    )
    assert stats["status"] == "skipped"
    assert stats["reason"] == "cloud-unavailable"


def test_run_sync_pipeline_returns_local_only_skip_when_conn_lacks_sync():
    class _LocalOnlyConn:
        pass  # 没有 .sync() 方法

    stats = _run_sync_pipeline(
        creds_ok=True,
        creds_skip_reason="",
        conn_factory=lambda: _LocalOnlyConn(),
        dry_run=False,
        progress_callback=None,
        messages={
            "skip_creds_msg": "skip", "connect": "c", "cloud_unavail_skip_prefix": "skip",
            "sync_doing": "s", "local_only": "l", "done": "d",
            "error_log_prefix": "err", "error_progress_prefix": "err",
        },
        skip_reason_local_only="local-only-sentinel",
    )
    assert stats["status"] == "skipped"
    assert stats["reason"] == "local-only-sentinel"


def test_run_sync_pipeline_runs_sync_when_dry_run_false(monkeypatch):
    """非 dry-run 时 backend.do_sync_on(conn) 应被调用并返回 ok。"""
    import contextlib

    class _MockBackend:
        def do_sync_on(self, conn):
            return None  # real backends return None; frames_synced defaults to 0
        def op_lock_for(self, conn):
            return contextlib.nullcontext()

    class _CloudConn:
        def sync(self):
            pass  # presence needed for the early-return guard at line 84

    from database import sync_service as _sync_mod
    monkeypatch.setattr(_sync_mod, "get_active_backend", lambda: _MockBackend())

    stats = _run_sync_pipeline(
        creds_ok=True,
        creds_skip_reason="",
        conn_factory=lambda: _CloudConn(),
        dry_run=False,
        progress_callback=None,
        messages={
            "skip_creds_msg": "skip", "connect": "c", "cloud_unavail_skip_prefix": "skip",
            "sync_doing": "s", "local_only": "l", "done": "d",
            "error_log_prefix": "err", "error_progress_prefix": "err",
        },
        skip_reason_local_only="local-only",
    )
    assert stats["status"] == "ok"


def test_run_sync_pipeline_skips_sync_call_when_dry_run_true():
    """dry-run 不调用 conn.sync()。"""
    calls = {"sync": 0}

    class _CloudConn:
        def sync(self):
            calls["sync"] += 1

    stats = _run_sync_pipeline(
        creds_ok=True,
        creds_skip_reason="",
        conn_factory=lambda: _CloudConn(),
        dry_run=True,
        progress_callback=None,
        messages={
            "skip_creds_msg": "skip", "connect": "c", "cloud_unavail_skip_prefix": "skip",
            "sync_doing": "s", "local_only": "l", "done": "d",
            "error_log_prefix": "err", "error_progress_prefix": "err",
        },
        skip_reason_local_only="local-only",
    )
    assert stats["status"] == "ok"
    assert calls["sync"] == 0
    assert "frames_synced" not in stats  # dry-run 不该填充
