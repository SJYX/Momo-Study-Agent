"""tests/unit/database/test_build_note_upsert_args.py: 笔记参数组装一致性。"""
from __future__ import annotations

import json

from database.notes_repo import build_note_upsert_args
from database.sql_constants import NOTE_UPSERT_SQL


def test_args_count_matches_sql_placeholders():
    args = build_note_upsert_args("vid-1", {"spelling": "apple"}, {})
    assert len(args) == NOTE_UPSERT_SQL.count("?")


def test_voc_id_is_stringified():
    args = build_note_upsert_args(12345, {"spelling": "x"}, {})
    assert args[0] == "12345"


def test_default_sync_status_for_ai_generated_is_zero():
    """content_origin=ai_generated → sync_status=0（未同步）。"""
    args = build_note_upsert_args("v", {"spelling": "x"}, {"content_origin": "ai_generated"})
    # sync_status 是倒数第 2 个字段（updated_at 是最后一个）
    assert args[-2] == 0


def test_default_sync_status_for_non_ai_origin_is_one():
    """content_origin != ai_generated → sync_status=1（视为已同步）。"""
    args = build_note_upsert_args("v", {"spelling": "x"}, {"content_origin": "imported"})
    assert args[-2] == 1


def test_explicit_sync_status_overrides_default():
    args = build_note_upsert_args("v", {"spelling": "x"}, {"content_origin": "imported"}, sync_status=0)
    assert args[-2] == 0


def test_metadata_takes_priority_over_payload_for_overlapping_fields():
    payload = {"spelling": "x", "content_origin": "from-payload", "original_meanings": "p_orig"}
    metadata = {"content_origin": "from-metadata", "original_meanings": "m_orig"}
    args = build_note_upsert_args("v", payload, metadata)
    # original_meanings 是位置索引 16
    assert args[16] == "m_orig"
    # content_origin 是位置索引 18
    assert args[18] == "from-metadata"


def test_raw_full_text_serializes_payload_when_missing():
    payload = {"spelling": "apple", "basic_meanings": "苹果"}
    args = build_note_upsert_args("v", payload, {})
    raw = args[11]
    parsed = json.loads(raw)
    assert parsed["spelling"] == "apple"
    assert parsed["basic_meanings"] == "苹果"
    # raw_full_text 不应被回填到自身
    assert "raw_full_text" not in parsed


def test_raw_full_text_passthrough_when_provided():
    payload = {"spelling": "x", "raw_full_text": "PRESET"}
    args = build_note_upsert_args("v", payload, {})
    assert args[11] == "PRESET"


def test_maimemo_context_is_json_serialized():
    metadata = {"maimemo_context": {"notepad_id": "n1", "tag": "高频"}}
    args = build_note_upsert_args("v", {"spelling": "x"}, metadata)
    # maimemo_context 是位置索引 17
    parsed = json.loads(args[17])
    assert parsed == {"notepad_id": "n1", "tag": "高频"}


def test_maimemo_context_none_when_missing():
    args = build_note_upsert_args("v", {"spelling": "x"}, {})
    assert args[17] is None


def test_token_fields_default_to_zero():
    args = build_note_upsert_args("v", {"spelling": "x"}, {})
    # prompt_tokens=12, completion_tokens=13, total_tokens=14
    assert args[12] == 0 and args[13] == 0 and args[14] == 0


def test_batch_id_pulled_from_metadata():
    args = build_note_upsert_args("v", {"spelling": "x"}, {"batch_id": "B-007"})
    # batch_id 位置索引 15
    assert args[15] == "B-007"


def test_single_and_batch_path_produce_identical_args_for_same_input():
    """单条与批量两条写入路径应组装出完全相同的参数。"""
    payload = {"spelling": "apple", "basic_meanings": "苹果", "prompt_tokens": 100}
    metadata = {"batch_id": "B1", "content_origin": "ai_generated"}
    single = build_note_upsert_args("v1", payload, metadata, sync_status=0)
    # 批量内部默认 sync_status=None（推导）—— content_origin=ai_generated → 0
    batch_each = build_note_upsert_args("v1", payload, metadata)
    # 除 updated_at（位置 22）外其他字段必须一致
    assert single[:22] == batch_each[:22]
