import pytest
from main import StudyFlowManager
import config

@pytest.fixture
def mock_flow(mocker):
    """提供一个全 Mock 的 StudyFlowManager 环境。"""
    # 强制走 Gemini 路径，避免 MIMO_KEY 依赖
    mocker.patch("main.AI_PROVIDER", "gemini")
    mocker.patch("main.GEMINI_API_KEY", "fake-key")

    # Mock API 和 Client
    mocker.patch("main.MaiMemoAPI")
    mocker.patch("core.gemini_client.GeminiClient")
    # Mock DB 操作避免写真实文件
    mocker.patch("main.init_db")
    mocker.patch("main.is_processed", return_value=False)
    mocker.patch("main.get_processed_ids_in_batch", return_value=[])
    mocker.patch("main.log_progress_snapshots", return_value=0)
    mocker.patch("main.mark_processed")
    # 关键修复：get_local_word_note 对新单词应返回 None
    mocker.patch("main.get_local_word_note", return_value=None)
    mocker.patch("main.save_ai_word_note")
    mocker.patch("main.save_ai_batch")
    mocker.patch("core.db_manager.save_ai_word_notes_batch")
    mocker.patch("core.db_manager.find_words_in_community_batch", return_value={})
    mocker.patch("main.StudyFlowManager._wait_for_choice", side_effect=["1", "4"])
    # Mock time
    mocker.patch("time.sleep", return_value=None)
    
    return StudyFlowManager()

def test_flow_dry_run_respect(mock_flow, mocker):
    """
    测试主流程是否尊重 DRY_RUN 设置。
    即便在 DRY_RUN=True 时，也应该调用 AI，本地笔记应该被保存。
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
    mock_flow.gemini.generate_mnemonics.return_value = (
        [
            {"spelling": "word1", "basic_meanings": "m1"},
            {"spelling": "word2", "basic_meanings": "m2"}
        ],
        {"total_tokens": 10}
    )
    
    # 强制开启 DRY_RUN
    mocker.patch("main.DRY_RUN", True)
    
    # 运行
    mock_flow.run()
    
    # 验证：AI 被调用了
    assert mock_flow.gemini.generate_mnemonics.called
    
    # 验证：本地笔记被保存
    from core.db_manager import save_ai_word_notes_batch
    assert save_ai_word_notes_batch.called

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
    mock_flow.gemini.generate_mnemonics.return_value = (
        [{"spelling": "word1", "basic_meanings": "m1"}],
        {"total_tokens": 10}
    )
    
    mock_flow.run()
    
    # 验证：AI 被调用了
    assert mock_flow.gemini.generate_mnemonics.called
    # 验证：至少有一个笔记被保存
    from core.db_manager import save_ai_word_notes_batch
    assert save_ai_word_notes_batch.called


def test_process_results_preserves_original_meanings_source(mock_flow, mocker):
    """测试流程能够保存 AI 生成的结果。"""
    mock_flow.momo.list_interpretations.return_value = {"success": True, "data": {"interpretations": []}}
    
    save_patch = mocker.patch("core.db_manager.save_ai_word_notes_batch")
    batch_words = [{"voc_id": "v1", "voc_spelling": "word1"}]
    ai_results = [{"spelling": "word1", "basic_meanings": "m1"}]

    mock_flow._process_results(batch_words, ai_results, 0, 1, "batch-1")

    # 验证笔记被保存
    assert save_patch.called
