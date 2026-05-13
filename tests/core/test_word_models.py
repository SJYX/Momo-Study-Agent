"""tests/core/test_word_models.py: WordItem 字段歧义吸收与 DB/payload 互转。"""
from __future__ import annotations

import pytest

from core.word_models import WordItem


class TestFromCloudRaw:
    """覆盖云端字段歧义场景。"""

    def test_canonical_fields(self):
        raw = {
            "voc_id": "v1",
            "voc_spelling": "apple",
            "voc_meanings": "n. 苹果",
            "review_count": 3,
            "short_term_familiarity": 2.5,
        }
        item = WordItem.from_cloud_raw(raw)
        assert item is not None
        assert item.voc_id == "v1"
        assert item.spelling == "apple"
        assert item.meanings == "n. 苹果"
        assert item.review_count == 3
        assert item.short_term_familiarity == 2.5

    def test_alias_id(self):
        """voc_id 可由 `id` 字段顶替。"""
        item = WordItem.from_cloud_raw({"id": "42", "spelling": "x"})
        assert item is not None
        assert item.voc_id == "42"

    def test_alias_spelling(self):
        """voc_spelling 可由 `spelling` 字段顶替。"""
        item = WordItem.from_cloud_raw({"voc_id": "v", "spelling": "x"})
        assert item is not None
        assert item.spelling == "x"

    @pytest.mark.parametrize(
        "field_name",
        ["voc_meanings", "meanings", "voc_meaning"],
    )
    def test_alias_meanings(self, field_name):
        """meanings 三种历史字段都能识别。"""
        raw = {"voc_id": "v", "voc_spelling": "x", field_name: "意思"}
        item = WordItem.from_cloud_raw(raw)
        assert item is not None
        assert item.meanings == "意思"

    def test_alias_familiarity(self):
        """short_term_familiarity 可由 familiarity_short 顶替。"""
        item = WordItem.from_cloud_raw(
            {"voc_id": "v", "voc_spelling": "x", "familiarity_short": 1.2}
        )
        assert item is not None
        assert item.short_term_familiarity == 1.2

    def test_returns_none_on_missing_voc_id(self):
        assert WordItem.from_cloud_raw({"voc_spelling": "x"}) is None

    def test_returns_none_on_missing_spelling(self):
        assert WordItem.from_cloud_raw({"voc_id": "v"}) is None

    def test_returns_none_on_empty(self):
        assert WordItem.from_cloud_raw({}) is None
        assert WordItem.from_cloud_raw(None) is None  # type: ignore[arg-type]

    def test_returns_none_on_non_dict(self):
        assert WordItem.from_cloud_raw("not a dict") is None  # type: ignore[arg-type]
        assert WordItem.from_cloud_raw(["list"]) is None  # type: ignore[arg-type]

    def test_int_id_coerced_to_str(self):
        """有些云端返回 voc_id 是 int，需要转 str。"""
        item = WordItem.from_cloud_raw({"voc_id": 100, "voc_spelling": "x"})
        assert item is not None
        assert item.voc_id == "100"
        assert isinstance(item.voc_id, str)

    def test_strip_whitespace(self):
        """字段两侧的空白应被去除（避免历史脏数据导致 voc_id 错配）。"""
        item = WordItem.from_cloud_raw(
            {"voc_id": "  v1  ", "voc_spelling": "  apple "}
        )
        assert item is not None
        assert item.voc_id == "v1"
        assert item.spelling == "apple"

    def test_invalid_numeric_fields_fallback(self):
        """review_count 或 familiarity 非法时降级为 0，不抛异常。"""
        item = WordItem.from_cloud_raw(
            {
                "voc_id": "v",
                "voc_spelling": "x",
                "review_count": "not-a-number",
                "short_term_familiarity": "bad",
            }
        )
        assert item is not None
        assert item.review_count == 0
        assert item.short_term_familiarity == 0.0


class TestFromCloudRawBatch:
    def test_filters_dirty_items(self):
        raws = [
            {"voc_id": "v1", "voc_spelling": "a"},
            {"voc_spelling": "no_id"},  # 脏数据
            {"voc_id": "v2", "spelling": "b"},
            {},                                # 脏数据
            None,                              # 脏数据
        ]
        items = WordItem.from_cloud_raw_batch(raws)  # type: ignore[arg-type]
        assert len(items) == 2
        assert {it.voc_id for it in items} == {"v1", "v2"}

    def test_empty_input(self):
        assert WordItem.from_cloud_raw_batch([]) == []
        assert WordItem.from_cloud_raw_batch(None) == []  # type: ignore[arg-type]


class TestFromDbRow:
    def test_canonical(self):
        row = {
            "voc_id": "v1",
            "spelling": "apple",
            "basic_meanings": "n. 苹果",
            "review_count": 5,
            "familiarity_short": 2.0,
        }
        item = WordItem.from_db_row(row)
        assert item.voc_id == "v1"
        assert item.spelling == "apple"
        assert item.meanings == "n. 苹果"
        assert item.review_count == 5
        assert item.short_term_familiarity == 2.0

    def test_meanings_fallback(self):
        """处理同时存在 basic_meanings 与 meanings 的情况。"""
        row = {"voc_id": "v", "spelling": "x", "meanings": "fallback"}
        item = WordItem.from_db_row(row)
        assert item.meanings == "fallback"

    def test_empty_row(self):
        item = WordItem.from_db_row({})
        assert item.voc_id == ""
        assert item.spelling == ""


class TestConversions:
    def test_to_processed_tuple(self):
        item = WordItem(voc_id="v1", spelling="apple")
        assert item.to_processed_tuple() == ("v1", "apple")

    def test_to_payload(self):
        item = WordItem(
            voc_id="v1", spelling="apple", meanings="n.",
            review_count=3, short_term_familiarity=2.5,
        )
        p = item.to_payload()
        assert p["voc_id"] == "v1"
        assert p["voc_spelling"] == "apple"
        assert p["voc_meanings"] == "n."
        assert p["review_count"] == 3
        assert p["short_term_familiarity"] == 2.5
