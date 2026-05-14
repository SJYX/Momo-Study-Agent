import threading
import time
from unittest.mock import MagicMock

from core import active_profile_registry
from core.sync_manager import SyncManager
from core.sync_priority import Priority


def test_active_profile_pause_for_p3_until_active_switch():
    active_profile_registry.reset()
    active_profile_registry.set_active("alice")

    logger = MagicMock()
    momo_api = MagicMock()
    momo_api.sync_interpretation.return_value = {"sync_status": 1}
    sm = SyncManager(logger, momo_api, MagicMock())

    sm.queue_maimemo_sync(
        "v-p3",
        "word",
        "x",
        ["t"],
        force_sync=True,
        priority=Priority.P3,
        profile_name="bob",
    )

    time.sleep(0.35)
    assert momo_api.sync_interpretation.call_count == 0

    active_profile_registry.set_active("bob")
    sm.sync_queue.join()
    sm.shutdown()

    assert momo_api.sync_interpretation.call_count == 1
