import pytest
import uuid
from unittest.mock import MagicMock, patch
from core.study_workflow import StudyWorkflow

@pytest.fixture
def mock_deps():
    logger = MagicMock()
    ai_client = MagicMock()
    momo_api = MagicMock()
    ui_manager = MagicMock()
    return logger, ai_client, momo_api, ui_manager

@pytest.fixture
def workflow(mock_deps):
    logger, ai_client, momo_api, ui_manager = mock_deps
    return StudyWorkflow(logger, ai_client, momo_api, ui_manager)

def test_process_empty_list(workflow, mock_deps):
    logger, _, _, _ = mock_deps
    workflow.process_word_list([], "空任务")
    logger.info.assert_any_call("空任务 无需处理")

def test_process_dirty_data_filtering(workflow, mock_deps):
    logger, _, _, _ = mock_deps
    dirty_data = [
        {"voc_id": "v1"}, # 缺失拼写
        {"voc_spelling": "word2"}, # 缺失 ID
        {"voc_id": None, "voc_spelling": "word3"} # ID 为 None
    ]
    workflow.process_word_list(dirty_data, "脏数据测试")
    logger.info.assert_any_call("脏数据测试 过滤后无可处理有效单词")

def test_process_deduplication_logic(workflow, mock_deps):
    logger, ai_client, _, _ = mock_deps
    word_list = [
        {"voc_id": "v1", "voc_spelling": "processed_word"},
        {"voc_id": "v2", "voc_spelling": "new_word"}
    ]
    
    # 模拟 v1 已处理
    with patch("core.study_workflow.get_processed_ids_in_batch", return_value=["v1"]):
        with patch("core.study_workflow.save_ai_batch", return_value=True):
            with patch("core.study_workflow.save_ai_word_notes_batch", return_value=True):
                # 模拟 AI 返回
                ai_client.generate_mnemonics.return_value = (
                    [{"spelling": "new_word", "basic_meanings": "m2"}],
                    {"total_tokens": 5, "request_id": "req-1"}
                )
                
                workflow.process_word_list(word_list, "去重测试")
                
                # 验证 v1 被跳过
                logger.info.assert_any_call("[去重] 去重测试: 总计 2 词，已处理跳过 1 词，待处理 1 词")
                # 验证 AI 只被调用了一次（针对 new_word）
                ai_client.generate_mnemonics.assert_called_once_with(["new_word"])

def test_ai_batch_failure_handling(workflow, mock_deps):
    logger, ai_client, _, _ = mock_deps
    word_list = [{"voc_id": "v1", "voc_spelling": "word1"}]
    
    with patch("core.study_workflow.get_processed_ids_in_batch", return_value=[]):
        # 模拟 AI 返回空结果
        ai_client.generate_mnemonics.return_value = ([], {})
        
        workflow.process_word_list(word_list, "失败测试")
        
        # 验证输出了警告
        logger.warning.assert_any_call("⚠️ AI 批次 1/1 返回空结果，已跳过: word1")


def test_dedup_recovers_from_local_notes(workflow, mock_deps):
    logger, ai_client, _, _ = mock_deps
    word_list = [
        {"voc_id": "v1", "voc_spelling": "word1"},
        {"voc_id": "v2", "voc_spelling": "word2"},
    ]

    with patch("core.study_workflow.get_processed_ids_in_batch", return_value=[]), \
         patch("core.study_workflow.get_local_word_note") as mock_local_note, \
         patch("core.study_workflow.mark_processed_batch", return_value=True) as mock_mark_batch:
        mock_local_note.side_effect = [
            {"voc_id": "v1", "spelling": "word1", "basic_meanings": "m1"},
            {"voc_id": "v2", "spelling": "word2", "basic_meanings": "m2"},
        ]

        workflow.process_word_list(word_list, "去重自愈测试")

        # 两个单词都应在自愈阶段被回填并跳过，AI 不应再被调用。
        logger.info.assert_any_call("[去重] 去重自愈测试: 总计 2 词，已处理跳过 2 词，待处理 0 词")
        logger.info.assert_any_call("✨ 无需调用 AI。")
        ai_client.generate_mnemonics.assert_not_called()
        mock_mark_batch.assert_called_once_with([("v1", "word1"), ("v2", "word2")])


def test_dedup_recovers_from_progress_history(workflow, mock_deps):
    logger, ai_client, _, _ = mock_deps
    word_list = [
        {"voc_id": "v1", "voc_spelling": "word1"},
        {"voc_id": "v2", "voc_spelling": "word2"},
    ]

    with patch("core.study_workflow.get_processed_ids_in_batch", return_value=[]), \
         patch("core.study_workflow.get_progress_tracked_ids_in_batch", return_value={"v1", "v2"}), \
         patch("core.study_workflow.mark_processed_batch", return_value=True) as mock_mark_batch:

        workflow.process_word_list(word_list, "进度历史回填测试")

        logger.info.assert_any_call("[去重] 进度历史回填测试: 总计 2 词，已处理跳过 2 词，待处理 0 词")
        logger.info.assert_any_call("✨ 无需调用 AI。")
        ai_client.generate_mnemonics.assert_not_called()
        mock_mark_batch.assert_called_once_with([("v1", "word1"), ("v2", "word2")])


def test_format_words_preview_robustness():
    """验证我们在最近修复中强化的预览逻辑。"""
    from core.study_workflow import StudyWorkflow
    
    # 正常情况
    assert StudyWorkflow._format_words_preview(["a", "b"]) == "a, b"
    
    # 包含 None
    assert StudyWorkflow._format_words_preview(["a", None, "c"]) == "a, c"
    
    # 全为 None
    assert StudyWorkflow._format_words_preview([None, None]) == "[empty]"
    
    # 超过限制
    words = [str(i) for i in range(25)]
    preview = StudyWorkflow._format_words_preview(words, limit=20)
    assert "..." in preview
    assert "(+5)" in preview
