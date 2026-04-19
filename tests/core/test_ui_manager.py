import pytest
from unittest.mock import MagicMock, patch
from core.ui_manager import CLIUIManager

@pytest.fixture
def ui():
    logger = MagicMock()
    return CLIUIManager(logger)

def test_ask_confirmation_yes(ui):
    with patch("core.ui_manager.CLIUIManager.wait_for_choice", return_value="y"):
        assert ui.ask_confirmation("Continue?") is True

def test_ask_confirmation_no(ui):
    with patch("core.ui_manager.CLIUIManager.wait_for_choice", return_value="n"):
        assert ui.ask_confirmation("Continue?") is False

def test_render_future_days_menu_presets(ui):
    # 测试快捷选项 (1 -> 1天, 3 -> 7天)
    with patch("core.ui_manager.CLIUIManager.wait_for_choice", return_value="1"):
        assert ui.render_future_days_menu() == 1
        
    with patch("core.ui_manager.CLIUIManager.wait_for_choice", return_value="3"):
        assert ui.render_future_days_menu() == 7

def test_render_future_days_menu_custom_valid(ui):
    # 测试自定义有效值
    with patch("core.ui_manager.CLIUIManager.wait_for_choice", return_value="6"):
        with patch("core.ui_manager.CLIUIManager.ask_text", return_value="15"):
            assert ui.render_future_days_menu() == 15

def test_render_future_days_menu_custom_invalid(ui):
    # 测试自定义无效值回退
    with patch("core.ui_manager.CLIUIManager.wait_for_choice", return_value="6"):
        with patch("core.ui_manager.CLIUIManager.ask_text", return_value="invalid"):
            # 应该打印错误并返回默认 7
            assert ui.render_future_days_menu() == 7

def test_render_future_days_menu_back(ui):
    # 测试返回主菜单
    with patch("core.ui_manager.CLIUIManager.wait_for_choice", return_value="0"):
        assert ui.render_future_days_menu() == 0
