"""tests/unit/web/test_profile_config.py

Verifies that load_profile_config picks up the unified AI_API_KEY / AI_MODEL /
AI_BASE_URL variables introduced by the LiteLLM migration. Without this, the
Web app silently ignores anything AIConfigCard saves.
"""
import os
import textwrap

import pytest


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Set up a fake BASE_DIR / DATA_DIR / PROFILES_DIR for one test."""
    base = tmp_path
    data = base / "data"
    profiles = data / "profiles"
    profiles.mkdir(parents=True)

    # Empty global .env so the loader doesn't merge stray env from the dev box.
    (base / ".env").write_text("", encoding="utf-8")

    import config as cfg
    monkeypatch.setattr(cfg, "BASE_DIR", str(base))
    monkeypatch.setattr(cfg, "DATA_DIR", str(data))
    monkeypatch.setattr(cfg, "PROFILES_DIR", str(profiles))
    return {"base": base, "data": data, "profiles": profiles}


def _write_profile(profiles_dir, username: str, body: str) -> None:
    path = profiles_dir / f"{username}.env"
    path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")


def test_load_profile_config_reads_unified_ai_fields(isolated_dirs):
    _write_profile(
        isolated_dirs["profiles"],
        "asher",
        """
        AI_PROVIDER=anthropic
        AI_API_KEY=sk-ant-test
        AI_MODEL=claude-sonnet-4-20250514
        AI_BASE_URL=
        """,
    )
    from web.backend.profile_config import load_profile_config
    cfg = load_profile_config("asher")
    assert cfg.ai_provider == "anthropic"
    assert cfg.ai_api_key == "sk-ant-test"
    assert cfg.ai_model == "claude-sonnet-4-20250514"
    assert cfg.ai_base_url == ""  # explicitly empty is preserved


def test_load_profile_config_reads_unified_ai_base_url(isolated_dirs):
    _write_profile(
        isolated_dirs["profiles"],
        "asher",
        """
        AI_PROVIDER=qwen
        AI_API_KEY=sk-q
        AI_MODEL=qwen-plus
        AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
        """,
    )
    from web.backend.profile_config import load_profile_config
    cfg = load_profile_config("asher")
    assert cfg.ai_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_load_profile_config_falls_back_to_legacy_keys(isolated_dirs):
    """When AI_API_KEY is absent, the snapshot should still derive a usable
    api_key from the legacy MIMO_API_KEY / GEMINI_API_KEY so wizard-created
    profiles keep working."""
    _write_profile(
        isolated_dirs["profiles"],
        "asher",
        """
        AI_PROVIDER=gemini
        GEMINI_API_KEY=AIza-legacy
        GEMINI_MODEL=gemini-2.0-flash
        """,
    )
    from web.backend.profile_config import load_profile_config
    cfg = load_profile_config("asher")
    # Either ai_api_key is populated from the legacy field, OR the legacy field
    # is exposed for downstream consumers. The Web user_context layer reads
    # ai_api_key, so prefer that.
    assert cfg.ai_api_key == "AIza-legacy"
    assert cfg.ai_model == "gemini-2.0-flash"


def test_load_profile_config_legacy_mimo_fallback(isolated_dirs):
    _write_profile(
        isolated_dirs["profiles"],
        "asher",
        """
        AI_PROVIDER=mimo
        MIMO_API_KEY=sk-mimo
        MIMO_MODEL=mimo-v2-flash
        MIMO_API_BASE=https://api.xiaomimimo.com/v1
        """,
    )
    from web.backend.profile_config import load_profile_config
    cfg = load_profile_config("asher")
    assert cfg.ai_api_key == "sk-mimo"
    assert cfg.ai_model == "mimo-v2-flash"
    assert cfg.ai_base_url == "https://api.xiaomimimo.com/v1"


def test_load_profile_config_new_keys_win_over_legacy(isolated_dirs):
    """If both unified and legacy keys are present, the unified ones must win
    — that's the whole point of the migration."""
    _write_profile(
        isolated_dirs["profiles"],
        "asher",
        """
        AI_PROVIDER=gemini
        AI_API_KEY=sk-new
        AI_MODEL=gemini-2.5-pro
        GEMINI_API_KEY=AIza-old
        GEMINI_MODEL=gemini-2.0-flash
        """,
    )
    from web.backend.profile_config import load_profile_config
    cfg = load_profile_config("asher")
    assert cfg.ai_api_key == "sk-new"
    assert cfg.ai_model == "gemini-2.5-pro"
