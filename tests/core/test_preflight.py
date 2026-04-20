import os
import pytest
from core.preflight import run_preflight

def test_preflight_all_pass(tmp_path, monkeypatch):
    """测试所有配置完整时的 PASS 情况"""
    root = tmp_path
    data_dir = root / "data" / "profiles"
    data_dir.mkdir(parents=True)
    
    # 模拟全局 .env
    env_file = root / ".env"
    env_file.write_text("FORCE_CLOUD_MODE=False\nTURSO_HUB_DB_URL=libsql://hub\nTURSO_HUB_AUTH_TOKEN=xxx", encoding="utf-8")
    
    # 模拟用户 .env
    profile_file = data_dir / "test_user.env"
    profile_file.write_text("MOMO_TOKEN=momo_xxx\nAI_PROVIDER=mimo\nMIMO_API_KEY=mimo_xxx", encoding="utf-8")
    
    result = run_preflight(str(root), "test_user")
    
    assert result["ok"] is True
    assert result["username"] == "test_user"
    assert result["force_cloud_mode"] is False
    # 验证关键检查项是否为 OK
    checks = {c["name"]: c for c in result["checks"]}
    assert checks["profile"]["ok"] is True
    assert checks["momo_token"]["ok"] is True
    assert checks["ai_provider"]["ok"] is True

def test_preflight_missing_profile(tmp_path):
    """测试缺少配置文件的情况"""
    root = tmp_path
    (root / "data" / "profiles").mkdir(parents=True)
    
    result = run_preflight(str(root), "non_existent_user")
    
    assert result["ok"] is False
    assert any(item["name"] == "profile" and item["blocking"] for item in result["blocking_items"])

def test_preflight_ai_key_missing(tmp_path):
    """测试配置了 provider 但缺失对应 Key 的情况"""
    root = tmp_path
    data_dir = root / "data" / "profiles"
    data_dir.mkdir(parents=True)
    
    # Provider 是 gemini，但没配置 GEMINI_API_KEY
    profile_file = data_dir / "test_user.env"
    profile_file.write_text("AI_PROVIDER=gemini\nMIMO_API_KEY=mimo_xxx", encoding="utf-8")
    
    result = run_preflight(str(root), "test_user")
    
    assert result["ok"] is False
    checks = {c["name"]: c for c in result["checks"]}
    assert checks["ai_key"]["ok"] is False
    assert checks["ai_key"]["blocking"] is True

def test_preflight_cloud_mode_conflict(tmp_path):
    """测试开启强制云端模式但缺少凭据的情况"""
    root = tmp_path
    data_dir = root / "data" / "profiles"
    data_dir.mkdir(parents=True)
    
    # 全局开启云端，但 Hub 凭据缺失
    env_file = root / ".env"
    env_file.write_text("FORCE_CLOUD_MODE=True", encoding="utf-8")
    
    profile_file = data_dir / "test_user.env"
    profile_file.write_text("MOMO_TOKEN=tk\nAI_PROVIDER=mimo\nMIMO_API_KEY=key", encoding="utf-8")
    
    result = run_preflight(str(root), "test_user")
    
    assert result["ok"] is False
    checks = {c["name"]: c for c in result["checks"]}
    assert checks["hub_config"]["ok"] is False
    assert checks["hub_config"]["blocking"] is True
    assert checks["force_cloud_conflict"]["ok"] is False

if __name__ == "__main__":
    pytest.main([__file__])
