import os
import sys
import pytest
from unittest.mock import MagicMock


@pytest.mark.xfail(
    reason=(
        "P0/P1 后 main.py bootstrap 改为 importlib.reload(config) 热加载（不再 subprocess）。"
        "此测试通过 runpy.run_path('main.py') 整模块加载，会跑到交互菜单触发 stdin OSError，"
        "且 tests/test_init.py 模块顶层 setenv MOMO_USER 会污染 bootstrap 分支判断。"
        "重写需要把 bootstrap 逻辑从 main.py 顶层抽成函数。计划在 P7（CLI 降级为备用入口）"
        "周期里随 main.py 整体重整一并处理。"
    ),
    strict=False,
)
def test_interactive_profile_selection_via_runpy(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("MOMO_USER", raising=False)

    import config
    monkeypatch.setattr(config, "ACTIVE_USER", "default")
    monkeypatch.setattr(config, "_USER_FROM_ENV", False)
    monkeypatch.setattr(config.pm, "pick_profile", lambda: "mock_asher")
    monkeypatch.setattr(config.pm, "normalize_username", lambda s: (s or "").strip().lower())

    monkeypatch.setattr(sys, "argv", ["main.py"])

    import runpy
    try:
        runpy.run_path("main.py", run_name="__main__")
    except (SystemExit, Exception):
        pass

    assert os.environ.get("MOMO_USER") == "mock_asher"
