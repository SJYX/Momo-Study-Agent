import pytest
from maimemo_api import MaiMemoAPI

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
    场景：查询发现不存在旧释义 -> 执行创建操作。
    """
    # 模拟 list_interpretations 返回空列表
    mock_list_res = mocker.Mock()
    mock_list_res.status_code = 200
    mock_list_res.json.return_value = {"success": True, "data": {"interpretations": []}}
    
    # 模拟 create_interpretation 返回成功
    mock_create_res = mocker.Mock()
    mock_create_res.status_code = 200
    mock_create_res.json.return_value = {"success": True}
    
    # 设置 mock 行为
    mocker.patch("requests.request", side_effect=[mock_list_res, mock_create_res])
    
    success = mock_api.sync_interpretation("voc_123", "New Meaning")
    assert success is True

def test_sync_interpretation_update(mock_api, mocker):
    """
    测试同步释义逻辑：
    场景：查询发现已存在旧释义 -> 执行更新操作。
    """
    # 模拟 list_interpretations 返回包含 1 条旧数据
    mock_list_res = mocker.Mock()
    mock_list_res.status_code = 200
    mock_list_res.json.return_value = {
        "success": True, 
        "data": {"interpretations": [{"id": "intp_99"}]}
    }
    
    # 模拟 update_interpretation 返回成功
    mock_update_res = mocker.Mock()
    mock_update_res.status_code = 200
    mock_update_res.json.return_value = {"success": True}
    
    # 设置 mock 行为
    mocker.patch("requests.request", side_effect=[mock_list_res, mock_update_res])
    
    success = mock_api.sync_interpretation("voc_123", "Updated Meaning")
    assert success is True

def test_create_note_includes_tags(mock_api, mocker):
    """测试助记创建时是否携带 tags。"""
    mock_res = mocker.Mock()
    mock_res.status_code = 200
    mock_res.json.return_value = {"success": True}

    request_mock = mocker.patch("requests.request", return_value=mock_res)

    mock_api.create_note("voc_123", "1", "Note Content", tags=["AI", "帮助"])

    _, kwargs = request_mock.call_args
    assert kwargs["json"]["note"]["tags"] == ["帮助"]
