import pytest
from core.study_flow import StudyFlowManager
from unittest.mock import MagicMock

@pytest.fixture
def mock_flow(mocker):
    """提供一个全 Mock 的 StudyFlowManager 环境。

    注：StudyFlowManager 已从 main.py 抽到 core/study_flow.py（Phase 3）。
    patch 路径相应改为 core.study_flow.*
    """
    # Mock core components（在 study_flow 模块命名空间中）
    mocker.patch("core.study_flow.setup_logger")
    mocker.patch("core.study_flow.MaiMemoAPI")
    mocker.patch("core.study_flow.CLIUIManager")
    mocker.patch("core.study_flow.StudyWorkflow")
    # build_ai_client 是 factories.py 暴露的工厂；patch 后返回 MagicMock
    mocker.patch("core.study_flow.build_ai_client", return_value=MagicMock())

    # Mock config
    mocker.patch("core.study_flow.ACTIVE_USER", "test_user")

    manager = StudyFlowManager()
    # 注入 Mock 对象以便后续断言
    manager.momo = MagicMock()
    manager.ui = MagicMock()

    return manager

def test_flow_choice_1_today_tasks(mock_flow, mocker):
    """测试选择今日任务时的调度流程。"""
    # 模拟用户选择今日任务后退出
    mock_flow.ui.wait_for_choice.side_effect = ["1", "4"]

    # 模拟获取到任务
    mock_flow.momo.get_today_items.return_value = {
        "success": True,
        "data": {"today_items": [{"voc_id": "v1", "voc_spelling": "word1"}]}
    }

    mock_flow.run()

    # 验证是否调用了 workflow
    assert mock_flow.workflow.process_word_list.called
    args, _ = mock_flow.workflow.process_word_list.call_args
    assert "今日任务" in args

def test_flow_choice_4_exit(mock_flow, mocker):
    """测试选择退出。"""
    mock_flow.ui.wait_for_choice.side_effect = ["4"]

    mock_flow.run()
    mock_flow.shutdown()

    # 验证 shutdown 被调用
    assert mock_flow.workflow.shutdown.called
