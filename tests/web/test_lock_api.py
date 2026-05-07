"""tests/web/test_lock_api.py: profile lock 公开 API 行为测试。

覆盖两段式占用流程：
- claim_profile_lock_with_placeholder
- update_profile_lock_holder
- release_profile_lock 幂等
- get_profile_lock_holder
"""
from __future__ import annotations

import pytest

import web.backend.lock as lock_mod
from web.backend.lock import (
    PROFILE_LOCK_PLACEHOLDER,
    acquire_profile_lock,
    claim_profile_lock_with_placeholder,
    get_profile_lock_holder,
    release_profile_lock,
    update_profile_lock_holder,
)


@pytest.fixture(autouse=True)
def reset_locks():
    """每个用例前清空 profile 锁状态，避免相互污染。"""
    with lock_mod._profile_locks_guard:
        lock_mod._profile_lock_holders.clear()
        for lk in lock_mod._profile_locks.values():
            try:
                lk.release()
            except RuntimeError:
                pass
        lock_mod._profile_locks.clear()
    yield
    with lock_mod._profile_locks_guard:
        lock_mod._profile_lock_holders.clear()
        lock_mod._profile_locks.clear()


def test_claim_succeeds_when_lock_is_free():
    acquired, prior = claim_profile_lock_with_placeholder("alice")
    assert acquired is True
    assert prior is None
    assert get_profile_lock_holder("alice") == PROFILE_LOCK_PLACEHOLDER


def test_claim_fails_when_already_held_and_returns_holder():
    acquire_profile_lock("alice", "task-existing")
    acquired, prior = claim_profile_lock_with_placeholder("alice")
    assert acquired is False
    assert prior == "task-existing"


def test_update_holder_swaps_placeholder_to_real_task_id():
    claim_profile_lock_with_placeholder("alice")
    update_profile_lock_holder("alice", "task-real-abc123")
    assert get_profile_lock_holder("alice") == "task-real-abc123"


def test_release_clears_holder_and_lock_can_be_claimed_again():
    claim_profile_lock_with_placeholder("alice")
    update_profile_lock_holder("alice", "task-1")
    release_profile_lock("alice")
    assert get_profile_lock_holder("alice") is None

    # 释放后可以重新占用
    acquired, _ = claim_profile_lock_with_placeholder("alice")
    assert acquired is True


def test_release_is_idempotent():
    release_profile_lock("nonexistent")
    release_profile_lock("nonexistent")  # 不应抛
    assert get_profile_lock_holder("nonexistent") is None


def test_locks_are_per_profile_independent():
    a, _ = claim_profile_lock_with_placeholder("alice")
    b, _ = claim_profile_lock_with_placeholder("bob")
    assert a is True and b is True
    assert get_profile_lock_holder("alice") == PROFILE_LOCK_PLACEHOLDER
    assert get_profile_lock_holder("bob") == PROFILE_LOCK_PLACEHOLDER


def test_two_phase_claim_then_swap_then_release_cycle():
    # 完整一个生命周期
    acquired, prior = claim_profile_lock_with_placeholder("alice")
    assert acquired and prior is None
    update_profile_lock_holder("alice", "task-xyz")
    assert get_profile_lock_holder("alice") == "task-xyz"
    release_profile_lock("alice")
    assert get_profile_lock_holder("alice") is None


def test_concurrent_claims_only_one_wins():
    """两个并发 claim 只有一个成功，另一个拿到当前持有者信息。"""
    a1, _ = claim_profile_lock_with_placeholder("alice")
    a2, prior = claim_profile_lock_with_placeholder("alice")
    assert a1 is True
    assert a2 is False
    assert prior == PROFILE_LOCK_PLACEHOLDER
