"""
core/settings.py: 静态 settings 的 pydantic-settings 模型。

Phase 6.3b 起：把 ``config.py`` 中的"导出常量"层（API keys / Turso URLs / 重试常量
/ Kill Switch flags）改用 pydantic-settings 校验。**profile orchestration 不动**——
那部分是 6.3a 抽到 ``core/profile_loader.py`` 的业务逻辑。

设计取舍：
1. 不强制 import-time 校验。``config.py`` 实例化 settings 时若环境不全（比如开发期没设
   GEMINI_API_KEY），所有 API key 字段允许 None；上游使用方自查 None。
2. 字段名与 env 变量名一一对应（pydantic-settings 默认行为），与现有 ``os.getenv``
   名字 100% 一致，零迁移。
3. Kill Switch flags 默认 True，与 ``core/feature_flags`` 行为一致。
4. ``Settings`` 实例可以重新构造（运行时 .env 改变后调 ``rebuild_settings()``）。
   ``feature_flags.is_enabled`` 在 6.3b 后改为读 settings，但保留 ``set_enabled`` 测试钩子
   覆盖路径——这样测试不必关心 settings 模型。
"""
from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",  # .env 里的额外字段不报错
    )

    # ─────────────── API Keys ───────────────
    MOMO_TOKEN: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    MIMO_API_KEY: Optional[str] = None
    MIMO_API_BASE: str = "https://api.xiaomimimo.com/v1"

    # ─────────────── AI Settings ───────────────
    GEMINI_MODEL: str = "gemini-2.0-flash"
    MIMO_MODEL: str = "mimo-v2-flash"
    BATCH_SIZE: int = 1
    AI_PROVIDER: str = "mimo"

    # ─────────────── Turso Cloud ───────────────
    TURSO_DB_URL: Optional[str] = None
    TURSO_AUTH_TOKEN: Optional[str] = None
    TURSO_DB_HOSTNAME: Optional[str] = None
    TURSO_TEST_DB_URL: Optional[str] = None
    TURSO_TEST_AUTH_TOKEN: Optional[str] = None
    TURSO_TEST_DB_HOSTNAME: Optional[str] = None
    TURSO_HUB_DB_URL: Optional[str] = None
    TURSO_HUB_AUTH_TOKEN: Optional[str] = None
    TURSO_MGMT_TOKEN: Optional[str] = None
    TURSO_ORG_SLUG: Optional[str] = None
    TURSO_GROUP: str = "123"

    # ─────────────── Security ───────────────
    ADMIN_PASSWORD_HASH: Optional[str] = None
    ENCRYPTION_KEY: Optional[str] = None

    # ─────────────── Runtime mode ───────────────
    FORCE_CLOUD_MODE: bool = False

    # ─────────────── PLAYBOOK A4 Kill Switch ───────────────
    AUTO_WARMUP_SYNC_ENABLED: bool = True
    SYNC_STATUS_HEAVY_QUERY_ENABLED: bool = True
    BACKGROUND_RETRY_ENABLED: bool = True


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """返回缓存的 Settings 实例。第一次调用时从当前 os.environ 读取并校验。

    若校验失败（环境变量值不合法），异常会向上抛——调用方应当 try/except 然后降级。
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def rebuild_settings() -> Settings:
    """强制从当前 os.environ 重新构建 Settings——用于 ``switch_user`` 后刷新缓存。

    若 Settings 校验失败（如 bool 字段拿到 "garbage"），先把缓存置 None 再抛异常，
    避免下游误用旧实例。
    """
    global _settings
    _settings = None  # 失败时也确保下次重新构造，不返回过期实例
    _settings = Settings()
    return _settings
