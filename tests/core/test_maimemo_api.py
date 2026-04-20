import pytest
from compat.maimemo_api import MaiMemoAPI

@pytest.fixture
def mock_api(mocker):
    """提供一个 Mock 的 MaiMemoAPI 实例。"""
    mocker.patch("time.sleep", return_value=None) # 加速测试
    api = MaiMemoAPI("fake_token")
    return api

def test_api_headers(mock_api):
    """验证请求头是否正确包含 Token。"""
    assert mock_api.headers["Authorization"] == "Bearer fake_token"

def test_get_today_items_success(mock_api, mocker):
    """测试获取今日单词成功场景。"""
    mock_res = mocker.Mock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "success": True,
        "data": {"today_items": [{"voc_id": "1", "voc_spelling": "test"}]}
    }
    mocker.patch("requests.request", return_value=mock_res)
    
    res = mock_api.get_today_items()
    assert res["success"] is True
    assert len(res["data"]["today_items"]) == 1

def test_sync_interpretation_create(mock_api, mocker):
    """
    测试同步释义逻辑：
    场景：创建成功后，云端内容与本地一致。
    """
    # 模拟首次查询返回空列表
    mock_list_res = mocker.Mock()
    mock_list_res.status_code = 200
    mock_list_res.json.return_value = {"success": True, "data": {"interpretations": []}}

    # 模拟 create_interpretation 返回成功
    mock_create_res = mocker.Mock()
    mock_create_res.status_code = 200
    mock_create_res.json.return_value = {"success": True}

    # 模拟创建后核验到一致释义
    mock_verify_res = mocker.Mock()
    mock_verify_res.status_code = 200
    mock_verify_res.json.return_value = {
        "success": True,
        "data": {"interpretations": [{"interpretation": "New Meaning"}]}
    }
    
    # 设置 mock 行为
    mocker.patch("requests.request", side_effect=[mock_list_res, mock_create_res, mock_verify_res])
    
    success = mock_api.sync_interpretation("voc_123", "New Meaning")
    assert success is True

def test_sync_interpretation_update(mock_api, mocker):
    """
    测试同步释义逻辑：
    场景：远端已存在一致释义，直接视为同步成功。
    """
    # 模拟 list_interpretations 返回包含 1 条旧数据
    mock_list_res = mocker.Mock()
    mock_list_res.status_code = 200
    mock_list_res.json.return_value = {
        "success": True, 
        "data": {"interpretations": [{"id": "intp_99", "interpretation": "Updated Meaning"}]}
    }
    
    # 设置 mock 行为
    mocker.patch("requests.request", return_value=mock_list_res)
    
    success = mock_api.sync_interpretation("voc_123", "Updated Meaning", force_create=False)
    assert success is True


def test_sync_interpretation_conflict_returns_status(mock_api, mocker):
    """测试云端释义与本地不一致时返回冲突态。"""
    mock_list_res = mocker.Mock()
    mock_list_res.status_code = 200
    mock_list_res.json.return_value = {
        "success": True,
        "data": {"interpretations": [{"id": "intp_99", "interpretation": "Different Meaning"}]}
    }

    mocker.patch("requests.request", return_value=mock_list_res)

    result = mock_api.sync_interpretation(
        "voc_123",
        "Expected Meaning",
        force_create=False,
        return_details=True,
    )

    assert result["sync_status"] == 2
    assert result["success"] is False

def test_create_note_includes_tags(mock_api, mocker):
    """测试助记创建时是否携带 tags。"""
    mock_res = mocker.Mock()
    mock_res.status_code = 200
    mock_res.json.return_value = {"success": True}

    request_mock = mocker.patch("requests.request", return_value=mock_res)

    mock_api.create_note("voc_123", "1", "Note Content", tags=["AI", "帮助"])

    _, kwargs = request_mock.call_args
    assert kwargs["json"]["note"]["tags"] == ["帮助"]
