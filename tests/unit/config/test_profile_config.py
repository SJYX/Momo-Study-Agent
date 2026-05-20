import os
import pytest
from web.backend.profile_config import load_profile_config, ProfileConfig

@pytest.fixture
def tmp_config_layout(tmp_path, monkeypatch):
    base = tmp_path
    data_dir = base / "data"
    profiles_dir = data_dir / "profiles"
    profiles_dir.mkdir(parents=True)

    (profiles_dir / "alice.env").write_text(
        "MOMO_TOKEN=alice_token\nAI_PROVIDER=gemini\nGEMINI_MODEL=gemini-custom\n", encoding="utf-8"
    )
    (profiles_dir / "bob.env").write_text(
        "MOMO_TOKEN=bob_token\nAI_PROVIDER=mimo\nMIMO_API_BASE=https://custom.mimo/v1\nMIMO_MODEL=mimo-custom\n", encoding="utf-8"
    )

    # Monkeypatch config attributes to avoid accessing real files
    import config as cfg
    monkeypatch.setattr(cfg, "BASE_DIR", str(base))
    monkeypatch.setattr(cfg, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(cfg, "PROFILES_DIR", str(profiles_dir))

    return {
        "base": str(base),
        "data_dir": str(data_dir),
        "profiles_dir": str(profiles_dir),
    }

def test_load_profile_config_loads_custom_fields(tmp_config_layout):
    cfg_alice = load_profile_config("alice")
    assert cfg_alice.profile_name == "alice"
    assert cfg_alice.ai_provider == "gemini"
    assert cfg_alice.gemini_model == "gemini-custom"
    assert cfg_alice.mimo_api_base == ""
    assert cfg_alice.mimo_model == ""

    cfg_bob = load_profile_config("bob")
    assert cfg_bob.profile_name == "bob"
    assert cfg_bob.ai_provider == "mimo"
    assert cfg_bob.mimo_api_base == "https://custom.mimo/v1"
    assert cfg_bob.mimo_model == "mimo-custom"
