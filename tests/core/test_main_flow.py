import pytest
from main import StudyFlowManager
import config

@pytest.fixture
def mock_flow(mocker):
    """提供一个全 Mock 的 StudyFlowManager 环境。"""
    # Mock API 和 Client
    mocker.patch("main.MaiMemoAPI")
    mocker.patch("main.GeminiClient")
    # Mock DB 操作避免写真实文件
    mocker.patch("main.init_db")
    mocker.patch("main.is_processed", return_value=False)
    mocker.patch("main.mark_processed")
    mocker.patch("main.save_ai_word_note")
    # Mock time
    mocker.patch("time.sleep", return_value=None)
    
    return StudyFlowManager()

def test_flow_dry_run_respect(mock_flow, mocker):
    """
    测试主流程是否尊重 DRY_RUN 设置。
    即便在 DRY_RUN=True 时，也应该调用 AI，但不应调用同步 API。
    """
    # 模拟获取到 2 个单词
    mock_flow.momo.get_today_items.return_value = {
        "success": True,
        "data": {"today_items": [
            {"voc_id": "v1", "voc_spelling": "word1"},
            {"voc_id": "v2", "voc_spelling": "word2"}
        ]}
    }
    
    # 模拟 AI 返回
    mock_flow.gemini.generate_mnemonics.return_value = [
        {"spelling": "word1", "basic_meanings": "m1"},
        {"spelling": "word2", "basic_meanings": "m2"}
    ]
    
    # 强制开启 DRY_RUN
    mocker.patch("main.DRY_RUN", True)
    
    # 运行
    mock_flow.run()
    
    # 验证：AI 被调用了
    assert mock_flow.gemini.generate_mnemonics.called
    
    # 验证：Maimemo 同步由于 DRY_RUN 不应被调用
    assert not mock_flow.momo.sync_interpretation.called
    
    # 验证：本地状态仍然被保存和标记了（这是规则允许的）
    from main import save_ai_word_note, mark_processed
    assert save_ai_word_note.called
    assert mark_processed.called

def test_flow_partial_ai_failure(mock_flow, mocker):
    """
    测试当 AI 只返回了一部分单词结果时的容错能力。
    """
    mock_flow.momo.get_today_items.return_value = {
        "success": True,
        "data": {"today_items": [
            {"voc_id": "v1", "voc_spelling": "word1"},
            {"voc_id": "v2", "voc_spelling": "word2"}
        ]}
    }
    
    # AI 只返回了 word1
    mock_flow.gemini.generate_mnemonics.return_value = [
        {"spelling": "word1", "basic_meanings": "m1"}
    ]
    
    mock_flow.run()
    
    # 验证：只有 word1 被标记了
    from main import mark_processed
    mark_processed.assert_called_with("v1", "word1")
    # 检查 call_count 确保没有多余调用
    assert mark_processed.call_count == 1
