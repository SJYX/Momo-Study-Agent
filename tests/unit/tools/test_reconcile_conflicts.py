"""tests: reconcile_conflicts comparison helpers."""
import pytest
from tools.reconcile_conflicts import _normalize


class TestNormalize:
    def test_empty_string(self):
        assert _normalize("") == ""

    def test_none_input(self):
        assert _normalize(None) == ""

    def test_whitespace_collapsed(self):
        assert _normalize("hello  world\t\nfoo") == "helloworldfoo"

    def test_identical_after_normalization(self):
        assert _normalize("放弃") == _normalize(" 放  弃 ")

    def test_different_content(self):
        assert _normalize("热情") != _normalize("热心")
