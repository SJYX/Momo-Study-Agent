import pytest
import json
import os
from core.mimo_client import MimoClient

class FakeResponse:
    def __init__(self, json_data):
        self.json_data = json_data
        self.status_code = 200
    def json(self):
        return self.json_data

def test_mimo_client_robustness_mixed_types(monkeypatch):
    """验证 MimoClient 能够处理 AI 返回的非对象 JSON 条目（防止 'str' object does not support item assignment）"""
    client = MimoClient(api_key="fake-key")
    
    # 模拟 AI 返回混合类型的列表
    fake_payload = {
        "choices": [{
            "message": {
                "content": json.dumps([
                    {"spelling": "apple", "memory_aid": "A"},
                    "THIS IS A RAW STRING THAT SHOULD BE SKIPPED",
                    {"spelling": "banana", "memory_aid": "B"}
                ])
            }
        }],
        "usage": {"total_tokens": 100}
    }
    
    monkeypatch.setattr(client.session, "post", lambda *args, **kwargs: FakeResponse(fake_payload))
    
    results, metadata = client.generate_mnemonics(["apple", "banana"])
    
    # 验证是否成功跳过了字符串，且没有崩溃
    assert len(results) == 2
    assert results[0]["spelling"] == "apple"
    assert results[1]["spelling"] == "banana"
    assert "raw_full_text" in results[0]

def test_mimo_client_robustness_object_format(monkeypatch):
    """验证 MimoClient 能够处理带 'results' 键的 JSON 对象格式 (回退后的标准格式)"""
    client = MimoClient(api_key="fake-key")
    
    fake_payload = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "results": [
                        {"spelling": "cherry", "memory_aid": "C"},
                        {"spelling": "date", "memory_aid": "D"}
                    ]
                })
            }
        }],
        "usage": {"total_tokens": 100}
    }
    
    monkeypatch.setattr(client.session, "post", lambda *args, **kwargs: FakeResponse(fake_payload))
    
    results, metadata = client.generate_mnemonics(["cherry", "date"])
    
    assert len(results) == 2
    assert results[0]["spelling"] == "cherry"
    assert results[1]["spelling"] == "date"

if __name__ == "__main__":
    pytest.main([__file__])
