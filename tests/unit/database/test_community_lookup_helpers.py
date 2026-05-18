"""tests/unit/database/test_community_lookup_helpers.py: 跨库查找的纯逻辑分支。"""
from __future__ import annotations

from database.community_lookup import (
    _absorb_lookup_results,
    _matches_ai_generation_context,
)


# ---------------------------------------------------------------------------
# _matches_ai_generation_context
# ---------------------------------------------------------------------------

def test_matches_when_no_provider_filter_specified():
    """当调用方未指定 ai_provider，认为所有 row 都匹配（向后兼容旧库）。"""
    assert _matches_ai_generation_context({"batch_ai_provider": "anything"}) is True


def test_mismatch_when_provider_differs():
    row = {"batch_ai_provider": "openai", "batch_prompt_version": "v1"}
    assert _matches_ai_generation_context(row, ai_provider="gemini") is False


def test_match_when_provider_and_version_align():
    row = {"batch_ai_provider": "Gemini", "batch_prompt_version": "v1"}
    assert _matches_ai_generation_context(row, ai_provider="gemini", prompt_version="v1") is True


def test_mismatch_when_prompt_version_differs():
    row = {"batch_ai_provider": "gemini", "batch_prompt_version": "v1"}
    assert _matches_ai_generation_context(row, ai_provider="gemini", prompt_version="v2") is False


def test_falls_back_to_legacy_field_names():
    row = {"ai_provider": "gemini", "prompt_version": "v1"}
    assert _matches_ai_generation_context(row, ai_provider="gemini", prompt_version="v1") is True


def test_rejects_when_batch_metadata_missing_and_filter_present():
    """当 row 完全没有 batch 元数据但调用方要求 provider 过滤时，应认为不匹配。"""
    row = {"voc_id": "v1"}
    assert _matches_ai_generation_context(row, ai_provider="gemini", prompt_version="v1") is False


# ---------------------------------------------------------------------------
# _absorb_lookup_results
# ---------------------------------------------------------------------------

def test_absorb_dedupes_by_voc_id():
    """重复出现的 voc_id 只记录第一次（按调用顺序）的来源。"""
    result: dict = {}
    remaining = ["v1", "v2"]
    rows = [{"voc_id": "v1", "batch_ai_provider": "gemini", "batch_prompt_version": "v"}]
    found = _absorb_lookup_results(
        rows, source_label="src1", result=result,
        remaining_ids=remaining, ai_provider=None, prompt_version=None,
    )
    assert found == 1
    assert "v1" in result and result["v1"][1] == "src1"
    assert remaining == ["v2"]

    # 第二次同 voc_id 不能覆盖 src1
    rows2 = [{"voc_id": "v1", "batch_ai_provider": "gemini", "batch_prompt_version": "v"}]
    found2 = _absorb_lookup_results(
        rows2, source_label="src2", result=result,
        remaining_ids=remaining, ai_provider=None, prompt_version=None,
    )
    assert found2 == 0
    assert result["v1"][1] == "src1"


def test_absorb_skips_rows_without_voc_id():
    result: dict = {}
    remaining = ["v1"]
    rows = [{"voc_id": None, "batch_ai_provider": "gemini", "batch_prompt_version": "v"}]
    found = _absorb_lookup_results(
        rows, source_label="src", result=result,
        remaining_ids=remaining, ai_provider=None, prompt_version=None,
    )
    assert found == 0
    assert result == {}
    assert remaining == ["v1"]


def test_absorb_skips_rows_failing_provider_filter():
    result: dict = {}
    remaining = ["v1"]
    rows = [{"voc_id": "v1", "batch_ai_provider": "openai", "batch_prompt_version": "v"}]
    found = _absorb_lookup_results(
        rows, source_label="src", result=result,
        remaining_ids=remaining, ai_provider="gemini", prompt_version="v",
    )
    assert found == 0
    assert remaining == ["v1"]
