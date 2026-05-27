"""tests/unit/core/test_preflight.py — fix #11 in the LiteLLM-migration code review.

Profiles configured via AIConfigCard write only the unified AI_API_KEY /
AI_PROVIDER / AI_MODEL vars. preflight.py must recognise them; otherwise
CLI startup blocks even though config is valid.
"""
import os
import pytest


@pytest.fixture
def fake_profiles(tmp_path):
    """Build a fake project root with .env + profiles dir, return paths."""
    root = tmp_path
    profiles_dir = root / "data" / "profiles"
    profiles_dir.mkdir(parents=True)
    (root / ".env").write_text("", encoding="utf-8")
    return root, profiles_dir


def _write_profile(profiles_dir, username: str, body: str) -> None:
    import textwrap
    (profiles_dir / f"{username}.env").write_text(
        textwrap.dedent(body).strip() + "\n", encoding="utf-8"
    )


def test_preflight_accepts_AI_API_KEY_for_new_providers(fake_profiles):
    """Provider in PROVIDERS list + AI_API_KEY set → preflight passes."""
    root, profiles_dir = fake_profiles
    _write_profile(profiles_dir, "asher", """
        MOMO_TOKEN=tok
        AI_PROVIDER=deepseek
        AI_API_KEY=sk-deepseek
        AI_MODEL=deepseek-chat
    """)
    from core.preflight import run_preflight
    result = run_preflight(str(root), "asher")
    assert result["ok"] is True, [
        f"{c['name']}={c['status']} ({c['detail']})" for c in result["checks"] if not c["ok"]
    ]


def test_preflight_accepts_AI_API_KEY_for_anthropic(fake_profiles):
    root, profiles_dir = fake_profiles
    _write_profile(profiles_dir, "asher", """
        MOMO_TOKEN=tok
        AI_PROVIDER=anthropic
        AI_API_KEY=sk-ant
        AI_MODEL=claude-sonnet-4-20250514
    """)
    from core.preflight import run_preflight
    result = run_preflight(str(root), "asher")
    assert result["ok"] is True


def test_preflight_still_accepts_legacy_mimo_profile(fake_profiles):
    """Legacy wizard-created profiles must keep passing preflight."""
    root, profiles_dir = fake_profiles
    _write_profile(profiles_dir, "asher", """
        MOMO_TOKEN=tok
        AI_PROVIDER=mimo
        MIMO_API_KEY=sk-mimo
    """)
    from core.preflight import run_preflight
    result = run_preflight(str(root), "asher")
    assert result["ok"] is True


def test_preflight_still_accepts_legacy_gemini_profile(fake_profiles):
    root, profiles_dir = fake_profiles
    _write_profile(profiles_dir, "asher", """
        MOMO_TOKEN=tok
        AI_PROVIDER=gemini
        GEMINI_API_KEY=AIza
    """)
    from core.preflight import run_preflight
    result = run_preflight(str(root), "asher")
    assert result["ok"] is True


def test_preflight_rejects_unknown_provider(fake_profiles):
    root, profiles_dir = fake_profiles
    _write_profile(profiles_dir, "asher", """
        MOMO_TOKEN=tok
        AI_PROVIDER=nonsense
        AI_API_KEY=sk-x
    """)
    from core.preflight import run_preflight
    result = run_preflight(str(root), "asher")
    assert result["ok"] is False
    failed = {c["name"]: c for c in result["checks"] if not c["ok"]}
    assert "ai_provider" in failed


def test_preflight_rejects_missing_ai_key(fake_profiles):
    """Provider set but no key → block startup."""
    root, profiles_dir = fake_profiles
    _write_profile(profiles_dir, "asher", """
        MOMO_TOKEN=tok
        AI_PROVIDER=qwen
    """)
    from core.preflight import run_preflight
    result = run_preflight(str(root), "asher")
    assert result["ok"] is False
    failed = {c["name"]: c for c in result["checks"] if not c["ok"]}
    assert "ai_key" in failed
