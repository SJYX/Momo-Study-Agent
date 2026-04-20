import pytest
import json
from compat.gemini_client import GeminiClient, _extract_json_array

def test_extract_json_array_standard():
    """测试标准 JSON 数组提取。"""
    text = '```json\n[{"spelling": "apple"}]\n```'
    result = _extract_json_array(text)
    assert result == '[{"spelling": "apple"}]'

def test_extract_json_array_with_hallucination():
    """测试带有“幻觉乱码”的修复能力。"""
    # 模拟模型输出：合法的数组后面跟着随机文字和额外的中括号
    text = '[{"spelling": "apple"}] 这里的苹果很好吃 ]道路]'
    result = _extract_json_array(text)
    assert result == '[{"spelling": "apple"}]'

def test_extract_json_array_nested():
    """测试嵌套结构的提取。"""
    text = '[{"a": [1, 2]}, {"b": 3}] some garbage'
    result = _extract_json_array(text)
    assert result == '[{"a": [1, 2]}, {"b": 3}]'

def test_gemini_client_init():
    """测试客户端初始化。"""
    client = GeminiClient(api_key="fake_key", model_name="test-model")
    assert client.model_name == "test-model"

def test_generate_mnemonics_mock(mocker):
    """使用 Mock 测试生成逻辑，确保不发生真实请求。"""
    client = GeminiClient(api_key="fake_key")
    mocker.patch.object(
        client,
        "generate_with_instruction",
        return_value=('```json\n[{"spelling": "mock_word"}]\n```', {"total_tokens": 10}),
    )

    results, metadata = client.generate_mnemonics(["test"])
    
    assert len(results) == 1
    assert results[0]["spelling"] == "mock_word"
    assert metadata.get("total_tokens") == 10
