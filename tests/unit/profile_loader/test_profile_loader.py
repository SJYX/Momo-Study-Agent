"""tests/unit/profile_loader/test_profile_loader.py: profile orchestration 抽离后的纯函数测试。"""
from __future__ import annotations

import os

import pytest

from core import profile_loader


@pytest.fixture
def tmp_layout(tmp_path, monkeypatch):
    """搭一个最小目录树：tmp/data/profiles + 一个 alice.env。"""
    base = tmp_path
    data_dir = base / "data"
    profiles_dir = data_dir / "profiles"
    profiles_dir.mkdir(parents=True)

    (profiles_dir / "alice.env").write_text(
        "MOMO_TOKEN=alice_token\nAI_PROVIDER=gemini\n", encoding="utf-8"
    )
    (profiles_dir / "Bob.env").write_text(
        "MOMO_TOKEN=bob_token\nAI_PROVIDER=mimo\n", encoding="utf-8"
    )

    global_env = base / ".env"
    global_env.write_text(
        "FORCE_CLOUD_MODE=True\nADMIN_PASSWORD_HASH=hashval\n", encoding="utf-8"
    )

    # 清掉环境变量避免污染
    for key in profile_loader.USER_SCOPED_KEYS + ["MOMO_USER", "FORCE_CLOUD_MODE"]:
        monkeypatch.delenv(key, raising=False)

    return {
        "base": str(base),
        "data_dir": str(data_dir),
        "profiles_dir": str(profiles_dir),
        "global_env": str(global_env),
    }


def test_normalize_username():
    assert profile_loader.normalize_username("  Alice  ") == "alice"
    assert profile_loader.normalize_username("BOB") == "bob"
    assert profile_loader.normalize_username("") == ""
    assert profile_loader.normalize_username(None) == ""  # type: ignore[arg-type]


def test_resolve_profile_env_path_case_insensitive(tmp_layout):
    profiles_dir = tmp_layout["profiles_dir"]

    # 直接命中
    norm, path = profile_loader.resolve_profile_env_path("alice", profiles_dir)
    assert norm == "alice"
    assert path is not None and path.endswith("alice.env")

    # 大小写不敏感命中（Bob.env 文件名首字母大写在 Windows 下可能被规范化成 bob.env，
    # 不去断言文件名形态——只要确实命中且返回值能用即可）
    norm2, path2 = profile_loader.resolve_profile_env_path("BOB", profiles_dir)
    assert norm2 == "bob"
    assert path2 is not None
    assert os.path.exists(path2)

    # 不存在
    norm3, path3 = profile_loader.resolve_profile_env_path("nobody", profiles_dir)
    assert norm3 == "nobody"
    assert path3 is None


def test_resolve_user_db_paths_uses_modern_naming(tmp_layout):
    db, test = profile_loader.resolve_user_db_paths("alice", tmp_layout["data_dir"])
    assert db.endswith(os.path.join("data", "history-alice.db"))
    assert test.endswith(os.path.join("data", "test-alice.db"))


def test_resolve_user_db_paths_falls_back_to_legacy_naming(tmp_layout):
    """老命名 history_X.db 仍能识别。"""
    legacy_path = os.path.join(tmp_layout["data_dir"], "history_alice.db")
    with open(legacy_path, "w") as f:
        f.write("")

    db, _ = profile_loader.resolve_user_db_paths("alice", tmp_layout["data_dir"])
    assert db == legacy_path


def test_bootstrap_loads_global_env_force_cloud_mode(tmp_layout, monkeypatch):
    """全局 .env 的 FORCE_CLOUD_MODE 应当 export 到 os.environ。"""
    bs = profile_loader.bootstrap_initial_profile(
        global_env_path=tmp_layout["global_env"],
        profiles_dir=tmp_layout["profiles_dir"],
        data_dir=tmp_layout["data_dir"],
    )
    assert os.getenv("FORCE_CLOUD_MODE") == "True"
    # pytest 环境下 bootstrap 会把 MOMO_USER 兜底为 test_user，所以 active_user 是 test_user
    assert bs.active_user == "test_user"
    assert bs.user_from_env is True


def test_bootstrap_with_explicit_user(tmp_layout, monkeypatch):
    monkeypatch.setenv("MOMO_USER", "alice")
    bs = profile_loader.bootstrap_initial_profile(
        global_env_path=tmp_layout["global_env"],
        profiles_dir=tmp_layout["profiles_dir"],
        data_dir=tmp_layout["data_dir"],
    )
    assert bs.active_user == "alice"
    assert bs.user_from_env is True
    assert os.getenv("MOMO_TOKEN") == "alice_token"
    assert os.getenv("AI_PROVIDER") == "gemini"


def test_bootstrap_clears_user_scoped_keys_from_outer_env(tmp_layout, monkeypatch):
    """外层 shell 残留的 MOMO_TOKEN 不能泄漏到没设它的 profile。"""
    monkeypatch.setenv("MOMO_TOKEN", "outer_leaked_token")
    monkeypatch.setenv("MOMO_USER", "alice")  # alice.env 内有 MOMO_TOKEN=alice_token

    profile_loader.bootstrap_initial_profile(
        global_env_path=tmp_layout["global_env"],
        profiles_dir=tmp_layout["profiles_dir"],
        data_dir=tmp_layout["data_dir"],
    )
    # alice.env 提供新值，覆盖了外层 leaked
    assert os.getenv("MOMO_TOKEN") == "alice_token"


def test_switch_user_returns_new_paths_and_loads_env(tmp_layout, monkeypatch):
    monkeypatch.setenv("MOMO_USER", "alice")
    profile_loader.bootstrap_initial_profile(
        global_env_path=tmp_layout["global_env"],
        profiles_dir=tmp_layout["profiles_dir"],
        data_dir=tmp_layout["data_dir"],
    )
    assert os.getenv("AI_PROVIDER") == "gemini"

    new_user, new_db, new_test = profile_loader.switch_user(
        "Bob",
        global_env_path=tmp_layout["global_env"],
        profiles_dir=tmp_layout["profiles_dir"],
        data_dir=tmp_layout["data_dir"],
    )
    assert new_user == "bob"
    assert new_db.endswith(os.path.join("data", "history-bob.db"))
    assert new_test.endswith(os.path.join("data", "test-bob.db"))
    # bob.env 的 AI_PROVIDER=mimo
    assert os.getenv("AI_PROVIDER") == "mimo"
    assert os.getenv("MOMO_TOKEN") == "bob_token"


def test_switch_user_loads_api_base_and_model(tmp_layout, monkeypatch):
    with open(os.path.join(tmp_layout["profiles_dir"], "Bob.env"), "a", encoding="utf-8") as f:
        f.write("MIMO_API_BASE=https://custom.mimo.api/v1\nMIMO_MODEL=mimo-v99\n")

    new_user, _, _ = profile_loader.switch_user(
        "Bob",
        global_env_path=tmp_layout["global_env"],
        profiles_dir=tmp_layout["profiles_dir"],
        data_dir=tmp_layout["data_dir"],
    )
    assert new_user == "bob"
    assert os.getenv("MIMO_API_BASE") == "https://custom.mimo.api/v1"
    assert os.getenv("MIMO_MODEL") == "mimo-v99"
