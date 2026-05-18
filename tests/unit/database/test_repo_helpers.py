"""tests/unit/database/test_repo_helpers.py: 行映射工具与写入分发的边界。"""
from __future__ import annotations

from database._repo_helpers import row_to_dict, row_value, rows_to_dicts


class _RowWithKeys:
    """模拟 libsql Row（同时暴露 keys() 和位置访问）。"""
    def __init__(self, columns, values):
        self._columns = columns
        self._values = values

    def keys(self):
        return self._columns

    def __iter__(self):
        return iter(self._values)

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._values[item]
        return self._values[self._columns.index(item)]


# ---------------------------------------------------------------------------
# row_value
# ---------------------------------------------------------------------------

def test_row_value_extracts_from_tuple_by_index():
    assert row_value(("a", "b"), 1, "ignored") == "b"


def test_row_value_extracts_from_keyed_row_by_name():
    row = _RowWithKeys(["voc_id", "spelling"], ["v1", "apple"])
    assert row_value(row, 0, "voc_id") == "v1"
    assert row_value(row, 1, "spelling") == "apple"


def test_row_value_returns_none_on_index_failure():
    class _NoMatchingKey:
        def __getitem__(self, item):
            raise KeyError(item)
    # 既无字符串列也无位置可访问 → 进入第二层 except，返回 None
    assert row_value(_NoMatchingKey(), 0, "x") is None


# ---------------------------------------------------------------------------
# row_to_dict
# ---------------------------------------------------------------------------

def test_row_to_dict_returns_none_for_falsy_input():
    assert row_to_dict(None) is None
    assert row_to_dict(()) is None


def test_row_to_dict_uses_keys_when_available():
    row = _RowWithKeys(["a", "b"], [1, 2])
    assert row_to_dict(row) == {"a": 1, "b": 2}


def test_row_to_dict_uses_fallback_columns_for_raw_tuple():
    assert row_to_dict((1, 2, 3), fallback_columns=["x", "y", "z"]) == {"x": 1, "y": 2, "z": 3}


def test_row_to_dict_returns_none_for_raw_tuple_without_fallback():
    assert row_to_dict((1, 2, 3)) is None


# ---------------------------------------------------------------------------
# rows_to_dicts
# ---------------------------------------------------------------------------

def test_rows_to_dicts_drops_unmappable_rows():
    rows = [
        _RowWithKeys(["a"], [1]),
        None,  # type: ignore[list-item]
    ]
    out = rows_to_dicts(rows)
    assert out == [{"a": 1}]


def test_rows_to_dicts_handles_empty_input():
    assert rows_to_dicts([]) == []
    assert rows_to_dicts(None) == []  # type: ignore[arg-type]
