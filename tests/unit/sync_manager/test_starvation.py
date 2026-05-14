from unittest.mock import MagicMock

from core.sync_manager import SyncManager
from core.sync_priority import Priority


def test_starvation_guard_yields_after_five_p1():
    logger = MagicMock()
    momo_api = MagicMock()
    momo_api.sync_interpretation.return_value = {"sync_status": 1}
    sm = SyncManager(logger, momo_api, MagicMock())

    sm.queue_maimemo_sync("p2-x", "p2x", "x", ["t"], force_sync=True, priority=Priority.P2)
    for i in range(6):
        sm.queue_maimemo_sync(f"p1-{i}", f"s{i}", "x", ["t"], force_sync=True, priority=Priority.P1)

    sm.sync_queue.join()
    sm.shutdown()

    ordered = [c.args[0] for c in momo_api.sync_interpretation.call_args_list]
    # 在前 7 个处理序列中，P2 必须不晚于第 6 个（索引 5）
    assert ordered.index("p2-x") <= 5
