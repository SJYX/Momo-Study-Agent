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
    
    # 模拟 WordService：v1 已处理
    with patch.object(workflow.word_service, "normalize_cloud_items") as mock_normalize:
        with patch.object(workflow.word_service, "enrich_with_states") as mock_enrich:
            with patch.object(workflow.word_service, "partition_by_processability") as mock_partition:
                with patch("core.study_workflow.save_ai_batch", return_value=True):
                    with patch("core.study_workflow.save_ai_word_notes_batch", return_value=True):
                        from core.word_models import WordItem
                        from database.word_state import WordState
                        
                        # normalize 返回两个 item
                        normalized = [
                            WordItem(voc_id="v1", spelling="processed_word"),
                            WordItem(voc_id="v2", spelling="new_word"),
                        ]
                        mock_normalize.return_value = normalized
                        
                        # enrich 返回 item 和 state 的元组
                        mock_enrich.return_value = [
                            (normalized[0], WordState.SYNCED),
                            (normalized[1], WordState.NOT_STARTED),
                        ]
                        
                        # partition: v1 已处理，v2 待处理
                        processed = [normalized[0]]
                        pending = [normalized[1]]
                        mock_partition.return_value = (pending, processed)
                        
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
    
    with patch.object(workflow.word_service, "normalize_cloud_items") as mock_normalize:
        with patch.object(workflow.word_service, "enrich_with_states") as mock_enrich:
            with patch.object(workflow.word_service, "partition_by_processability") as mock_partition:
                from core.word_models import WordItem
                from database.word_state import WordState
                
                # normalize 返回 1 个 item
                normalized = [WordItem(voc_id="v1", spelling="word1")]
                mock_normalize.return_value = normalized
                
                # enrich 返回 item 和 state 的元组
                mock_enrich.return_value = [(normalized[0], WordState.NOT_STARTED)]
                
                # partition: v1 待处理
                mock_partition.return_value = (normalized, [])
                
                # 模拟 AI 返回空结果
                ai_client.generate_mnemonics.return_value = ([], {})
                
                workflow.process_word_list(word_list, "失败测试")
                
                # 验证输出了警告
                warning_messages = [c.args[0] for c in logger.warning.call_args_list if c.args]
                assert "⚠️ AI 批次 1/1 返回空结果，已跳过: word1" in warning_messages


def test_dedup_recovers_from_local_notes(workflow, mock_deps):
    logger, ai_client, _, _ = mock_deps
    word_list = [
        {"voc_id": "v1", "voc_spelling": "word1"},
        {"voc_id": "v2", "voc_spelling": "word2"},
    ]

    with patch.object(workflow.word_service, "normalize_cloud_items") as mock_normalize:
        with patch.object(workflow.word_service, "enrich_with_states") as mock_enrich:
            with patch.object(workflow.word_service, "partition_by_processability") as mock_partition:
                from core.word_models import WordItem
                from database.word_state import WordState
                
                # normalize 返回 2 个 item
                normalized = [
                    WordItem(voc_id="v1", spelling="word1"),
                    WordItem(voc_id="v2", spelling="word2"),
                ]
                mock_normalize.return_value = normalized
                
                # enrich 返回 item 和 state 的元组
                mock_enrich.return_value = [
                    (normalized[0], WordState.LOCAL_READY),
                    (normalized[1], WordState.LOCAL_READY),
                ]
                
                # partition: 两个都已处理（从本地笔记恢复）
                mock_partition.return_value = ([], normalized)
                
                workflow.process_word_list(word_list, "去重自愈测试")

                # 两个单词都应被识别为已处理并跳过，AI 不应再被调用。
                logger.info.assert_any_call("[去重] 去重自愈测试: 总计 2 词，已处理跳过 2 词，待处理 0 词")
                logger.info.assert_any_call("✨ 无需调用 AI。")
                ai_client.generate_mnemonics.assert_not_called()


def test_dedup_recovers_from_progress_history(workflow, mock_deps):
    logger, ai_client, _, _ = mock_deps
    word_list = [
        {"voc_id": "v1", "voc_spelling": "word1"},
        {"voc_id": "v2", "voc_spelling": "word2"},
    ]

    with patch.object(workflow.word_service, "normalize_cloud_items") as mock_normalize:
        with patch.object(workflow.word_service, "enrich_with_states") as mock_enrich:
            with patch.object(workflow.word_service, "partition_by_processability") as mock_partition:
                from core.word_models import WordItem
                from database.word_state import WordState
                
                # normalize 返回 2 个 item
                normalized = [
                    WordItem(voc_id="v1", spelling="word1"),
                    WordItem(voc_id="v2", spelling="word2"),
                ]
                mock_normalize.return_value = normalized
                
                # enrich 返回 item 和 state 的元组
                mock_enrich.return_value = [
                    (normalized[0], WordState.SYNCED),
                    (normalized[1], WordState.SYNCED),
                ]
                
                # partition: 两个都已处理（从进度历史恢复）
                mock_partition.return_value = ([], normalized)
                
                workflow.process_word_list(word_list, "进度历史回填测试")

                logger.info.assert_any_call("[去重] 进度历史回填测试: 总计 2 词，已处理跳过 2 词，待处理 0 词")
                logger.info.assert_any_call("✨ 无需调用 AI。")
                ai_client.generate_mnemonics.assert_not_called()


def test_skipped_row_status_for_failed_sync(workflow, mock_deps):
    """H1 回归：sync_status=5 的词在 skipped 分支应显示为 error/sync_failed,
    而不是被静默渲染为 done/skipped(见审查报告 §2 H1)。"""
    logger, ai_client, _, _ = mock_deps
    word_list = [{"voc_id": "vFAIL", "voc_spelling": "failed_word"}]

    with patch.object(workflow.word_service, "normalize_cloud_items") as mock_normalize:
        with patch.object(workflow.word_service, "enrich_with_states") as mock_enrich:
            with patch.object(workflow.word_service, "partition_by_processability") as mock_partition:
                with patch("core.study_workflow.get_local_word_note") as mock_note:
                    from core.word_models import WordItem
                    from database.word_state import WordState

                    normalized = [WordItem(voc_id="vFAIL", spelling="failed_word")]
                    mock_normalize.return_value = normalized
                    mock_enrich.return_value = [(normalized[0], WordState.FAILED)]
                    mock_partition.return_value = ([], normalized)  # 全部在 processed_items
                    mock_note.return_value = {
                        "sync_status": 5,
                        "match_reason": "invalid_res_id",
                    }

                    workflow.process_word_list(word_list, "失败状态测试")

                    # 找到 [RowStatus] 跳过单词状态回填 这条 info call
                    row_status_calls = [
                        c for c in logger.info.call_args_list
                        if c.kwargs.get("extra", {}).get("event") == "row_status"
                        and "本轮跳过单词状态回填" in str(c.args[0])
                    ]
                    assert row_status_calls, "应当发出 [RowStatus] 本轮跳过单词状态回填 事件"

                    rows = row_status_calls[0].kwargs["extra"]["data"]["rows"]
                    failed_rows = [r for r in rows if r["item_id"] == "failed_word"]
                    assert failed_rows, "应当包含 failed_word 的状态行"
                    assert failed_rows[0]["phase"] == "sync_failed"
                    assert failed_rows[0]["status"] == "error"
                    assert failed_rows[0]["error"] == "invalid_res_id"


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
