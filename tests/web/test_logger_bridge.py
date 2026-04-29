"""
tests/web/test_logger_bridge.py -- LoggerBridge tests.
"""
from __future__ import annotations
import asyncio
import threading
import pytest
from web.backend.logger_bridge import LoggerBridge
from web.backend.tasks import TaskRegistry


class _FakeLogger:
    def __init__(self):
        self.context = {}
        self.infos = []
    def set_context(self, **kw):
        self.context.update(kw)
    def info(self, msg, **kw):
        self.infos.append((msg, kw))
    def warning(self, msg, **kw):
        pass
    def error(self, msg, **kw):
        pass


class TestLoggerBridge:
    def test_attach_and_detach(self):
        reg = TaskRegistry(max_workers=1)
        bridge = LoggerBridge(reg)
        logger = _FakeLogger()
        orig_id = id(logger.info)
        bridge.attach(logger)
        assert id(logger.info) != orig_id
        bridge.detach(logger)
        assert id(logger.info) == orig_id
        reg.shutdown()

    def test_attach_idempotent(self):
        reg = TaskRegistry(max_workers=1)
        bridge = LoggerBridge(reg)
        logger = _FakeLogger()
        bridge.attach(logger)
        sid = id(logger.info)
        bridge.attach(logger)
        assert id(logger.info) == sid
        bridge.detach(logger)
        reg.shutdown()

    def test_detach_without_attach(self):
        reg = TaskRegistry(max_workers=1)
        bridge = LoggerBridge(reg)
        logger = _FakeLogger()
        bridge.detach(logger)
        reg.shutdown()

    def test_event_forwarding(self):
        loop = asyncio.new_event_loop()
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()
        try:
            reg = TaskRegistry(max_workers=1)
            bridge = LoggerBridge(reg)
            logger = _FakeLogger()
            bridge.attach(logger)
            task_id = reg.submit(lambda: None, event_loop=loop, logger=None)
            logger.context["task_id"] = task_id
            import time as _t
            deadline = _t.time() + 2
            while _t.time() < deadline:
                rec = reg.get(task_id)
                if rec and rec.status == "running":
                    break
                _t.sleep(0.02)
            logger.info("test msg")
            events = reg.get_events(task_id)
            log_evts = [e for e in events if e.get("type") == "log" and e.get("message") == "test msg"]
            assert len(log_evts) >= 1
            bridge.detach(logger)
            reg.shutdown()
        finally:
            loop.call_soon_threadsafe(loop.stop)
            t.join(timeout=2)
            loop.close()

    def test_no_forwarding_without_task_id(self):
        reg = TaskRegistry(max_workers=1)
        bridge = LoggerBridge(reg)
        logger = _FakeLogger()
        bridge.attach(logger)
        logger.info("no task")
        assert len(logger.infos) == 1
        bridge.detach(logger)
        reg.shutdown()

    def test_extra_data_forwarded(self):
        reg = TaskRegistry(max_workers=1)
        bridge = LoggerBridge(reg)
        logger = _FakeLogger()
        bridge.attach(logger)
        logger.context["task_id"] = "nonexistent"
        logger.info("msg", extra={"event": "progress", "progress": {"pct": 50}})
        assert len(logger.infos) == 1
        bridge.detach(logger)
        reg.shutdown()
