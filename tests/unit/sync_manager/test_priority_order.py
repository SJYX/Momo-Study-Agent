import time
from unittest.mock import MagicMock

from core.sync_manager import SyncManager
from core.sync_priority import Priority


def _build_sm():
    logger = MagicMock()
    momo_api = MagicMock()
    momo_api.sync_interpretation.return_value = {"sync_status": 1}
    sm = SyncManager(logger, momo_api, MagicMock(), MagicMock())
    return sm, momo_api


def test_priority_order_and_fifo_same_priority():
    sm, momo_api = _build_sm()

    sm.queue_maimemo_sync("p2-a", "p2a", "x", ["t"], force_sync=True, priority=Priority.P2)
    sm.queue_maimemo_sync("p1-a", "p1a", "x", ["t"], force_sync=True, priority=Priority.P1)
    sm.queue_maimemo_sync("p2-b", "p2b", "x", ["t"], force_sync=True, priority=Priority.P2)
    sm.queue_maimemo_sync("p3-a", "p3a", "x", ["t"], force_sync=True, priority=Priority.P3)

    sm.sync_queue.join()
    sm.shutdown()

    calls = [c.args[0] for c in momo_api.sync_interpretation.call_args_list]
    assert calls == ["p1-a", "p2-a", "p2-b", "p3-a"]
