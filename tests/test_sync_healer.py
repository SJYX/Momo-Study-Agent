"""测试同步自愈机制"""
import pytest
import time
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from database.sync_healer import get_stuck_records, heal_stuck_sync_status


def test_get_stuck_records_returns_old_unsynced():
    """验证 get_stuck_records 返回超过 1 小时且 sync_status=0 的记录"""
    mock_session = Mock()
    mock_cursor = Mock()
    mock_session.execute.return_value = mock_cursor

    # 模拟返回 2 条卡住的记录
    old_time = datetime.now() - timedelta(hours=2)
    mock_cursor.fetchall.return_value = [
        {"id": 1, "voc_id": "vocab_1", "created_at": old_time.isoformat()},
        {"id": 2, "voc_id": "vocab_2", "created_at": old_time.isoformat()},
    ]

    records = get_stuck_records(
        older_than_hours=1,
        limit=50,
        db_path="test.db",
        session=mock_session
    )

    assert len(records) == 2
    assert records[0]["voc_id"] == "vocab_1"
    assert records[1]["voc_id"] == "vocab_2"

    # 验证 SQL 查询参数
    call_args = mock_session.execute.call_args
    assert "sync_status = 0" in call_args[0][0]
    assert "created_at <" in call_args[0][0]


def test_heal_stuck_sync_status_fixes_records():
    """验证自愈机制在云端有数据时修复记录"""
    mock_api = Mock()
    mock_session = Mock()

    # 模拟 get_stuck_records 返回 1 条记录
    with patch('database.sync_healer.get_stuck_records') as mock_get_stuck:
        old_time = datetime.now() - timedelta(hours=2)
        mock_get_stuck.return_value = [
            {"id": 1, "voc_id": "vocab_1", "created_at": old_time.isoformat()}
        ]

        # 模拟云端有数据
        mock_api.list_interpretations.return_value = {
            "data": [{"id": "interp_1", "interpretation": "test"}]
        }

        healed_count = heal_stuck_sync_status(
            momo_api=mock_api,
            max_records=50,
            db_path="test.db",
            session=mock_session
        )

        assert healed_count == 1

        # 验证调用了 API 检查云端数据
        mock_api.list_interpretations.assert_called_once_with("vocab_1")

        # 验证更新了 sync_status
        update_call = mock_session.execute.call_args_list[-1]
        assert "UPDATE ai_word_notes" in update_call[0][0]
        assert "sync_status = 1" in update_call[0][0]


def test_heal_stuck_sync_status_skips_if_no_cloud_data():
    """验证自愈机制在云端无数据时跳过记录"""
    mock_api = Mock()
    mock_session = Mock()

    with patch('database.sync_healer.get_stuck_records') as mock_get_stuck:
        old_time = datetime.now() - timedelta(hours=2)
        mock_get_stuck.return_value = [
            {"id": 1, "voc_id": "vocab_1", "created_at": old_time.isoformat()}
        ]

        # 模拟云端无数据
        mock_api.list_interpretations.return_value = {"data": []}

        healed_count = heal_stuck_sync_status(
            momo_api=mock_api,
            max_records=50,
            db_path="test.db",
            session=mock_session
        )

        assert healed_count == 0

        # 验证调用了 API 但没有更新数据库
        mock_api.list_interpretations.assert_called_once_with("vocab_1")

        # 验证没有执行 UPDATE（只有 SELECT 调用）
        for call in mock_session.execute.call_args_list:
            assert "UPDATE" not in call[0][0]
