# -*- coding: utf-8 -*-
"""Shared database utility helpers.

This module contains side-effect-light helper logic used by connection/schema/
business modules, including:
- logging throttle helpers
- cloud target discovery helpers
- secret encryption/decryption helpers
- text normalization helpers
- SQLite corruption/error classification helpers
- broken DB backup helpers
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from config import DATA_DIR, DB_PATH, ENCRYPTION_KEY, HUB_DB_PATH, PROFILES_DIR, TURSO_HUB_DB_URL

try:
    from core.logger import get_logger
except ImportError:
    import logging

    def get_logger():
        return logging.getLogger(__name__)


UTC_PLUS_8 = timezone(timedelta(hours=8))

# Cloud discovery/cache config
_CLOUD_TARGET_CACHE_TTL_SECONDS = int(os.getenv("CLOUD_TARGET_CACHE_TTL_SECONDS", "600"))
_CLOUD_LOOKUP_MAX_TARGETS = int(os.getenv("CLOUD_LOOKUP_MAX_TARGETS", "40"))
_MGMT_TOKEN_VALIDATE_TTL_SECONDS = int(os.getenv("MGMT_TOKEN_VALIDATE_TTL_SECONDS", "300"))

_cloud_targets_cache: Dict[str, Any] = {"expire_at": 0.0, "targets": []}
_mgmt_token_validation_cache: Dict[str, Any] = {"expire_at": 0.0, "valid": None, "reason": ""}

_throttled_log_state: Dict[str, float] = {}
_throttled_log_lock = None


try:
    import threading

    _throttled_log_lock = threading.Lock()
except Exception:
    _throttled_log_lock = None


def _debug_log(msg: str, start_time: Optional[float] = None, level: str = "DEBUG", module: str = "database.utils") -> None:
    elapsed = f" | Time: {int((time.time() - start_time) * 1000)}ms" if start_time else ""
    log_msg = f"{msg}{elapsed}"

    try:
        logger = get_logger()
        level_map = {
            "CRITICAL": getattr(logger, "critical", logger.debug),
            "ERROR": getattr(logger, "error", logger.debug),
            "WARNING": getattr(logger, "warning", logger.debug),
            "INFO": getattr(logger, "info", logger.debug),
            "DEBUG": getattr(logger, "debug", logger.debug),
        }
        log_func = level_map.get(level, logger.debug)
        try:
            log_func(log_msg, module=module)
        except TypeError:
            log_func(log_msg)
    except Exception:
        pass


def _debug_log_throttled(
    key: str,
    msg: str,
    interval_seconds: float = 30.0,
    start_time: Optional[float] = None,
    level: str = "DEBUG",
    module: str = "database.utils",
) -> None:
    now = time.time()
    should_log = False

    if _throttled_log_lock is None:
        should_log = True
    else:
        with _throttled_log_lock:
            last_ts = float(_throttled_log_state.get(key, 0.0) or 0.0)
            if now - last_ts >= float(interval_seconds):
                _throttled_log_state[key] = now
                should_log = True

    if should_log:
        _debug_log(msg, start_time=start_time, level=level, module=module)


def _normalize_turso_url(hostname: str) -> str:
    """Normalize Turso endpoint to sync_url format expected by libsql."""
    if not hostname:
        return ""
    raw = hostname.strip()
    if raw.startswith("libsql://") or raw.startswith("https://") or raw.startswith("wss://"):
        return raw
    if "." in raw or raw == "localhost":
        return f"libsql://{raw}"
    return f"libsql://{raw}"


def _hash_fingerprint(raw: str) -> str:
    """Compress long identifier into short hash."""
    return hashlib.sha256((raw or "unknown").encode("utf-8")).hexdigest()[:12]


def _main_db_fingerprint(db_path: Optional[str] = None) -> str:
    """Main DB instance fingerprint: prefer cloud URL, fallback local absolute path."""
    is_test = bool(db_path and "test_" in os.path.basename(db_path))
    url = os.getenv("TURSO_TEST_DB_URL") if is_test else os.getenv("TURSO_DB_URL")
    if not url:
        hostname = os.getenv("TURSO_TEST_DB_HOSTNAME") if is_test else os.getenv("TURSO_DB_HOSTNAME")
        if hostname:
            url = _normalize_turso_url(hostname)
    if url:
        return f"cloud:{url.strip()}"
    path = os.path.abspath(db_path or DB_PATH)
    return f"local:{path}"


def _hub_db_fingerprint() -> str:
    """Hub DB instance fingerprint."""
    if TURSO_HUB_DB_URL:
        return f"cloud:{TURSO_HUB_DB_URL.strip()}"
    return f"local:{os.path.abspath(HUB_DB_PATH)}"


def _read_profile_cloud_config(profile_env_path: str) -> Optional[Dict[str, str]]:
    """Read TURSO DB URL/token from a profile env file without mutating process env."""
    if not os.path.exists(profile_env_path):
        return None

    url = ""
    token = ""
    try:
        with open(profile_env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key == "TURSO_DB_URL":
                    url = value
                elif key == "TURSO_AUTH_TOKEN":
                    token = value
        if url and token:
            return {"url": url, "token": token}
    except Exception as e:
        _debug_log(f"读取 profile 云配置失败: {profile_env_path} -> {e}", level="WARNING")
    return None


def _validate_turso_management_token(force_refresh: bool = False) -> Dict[str, Any]:
    """Validate Turso management token once per TTL to avoid repeated slow failures."""
    now = time.time()
    mgmt_token = (os.getenv("TURSO_MGMT_TOKEN") or "").strip()
    if not mgmt_token:
        return {"checked": False, "valid": False, "reason": "missing-mgmt-token"}

    if (
        not force_refresh
        and _mgmt_token_validation_cache.get("valid") is not None
        and now < _mgmt_token_validation_cache.get("expire_at", 0.0)
    ):
        return {
            "checked": True,
            "valid": bool(_mgmt_token_validation_cache.get("valid")),
            "reason": _mgmt_token_validation_cache.get("reason", "cached"),
            "cached": True,
        }

    headers = {"Authorization": f"Bearer {mgmt_token}"}
    validate_url = "https://api.turso.tech/v1/auth/validate"
    fallback_validate_url = "https://api.turso.tech/v1/user"
    try:
        started_at = time.time()
        resp = requests.get(validate_url, headers=headers, timeout=6)
        elapsed_ms = int((time.time() - started_at) * 1000)

        if resp.status_code == 200:
            _mgmt_token_validation_cache["valid"] = True
            _mgmt_token_validation_cache["reason"] = "ok"
            _mgmt_token_validation_cache["expire_at"] = now + _MGMT_TOKEN_VALIDATE_TTL_SECONDS
            _debug_log(f"Turso 管理令牌校验通过 (/auth/validate) | validate_ms={elapsed_ms}")
            return {"checked": True, "valid": True, "reason": "ok", "cached": False}

        fallback_started_at = time.time()
        fallback_resp = requests.get(fallback_validate_url, headers=headers, timeout=6)
        fallback_elapsed_ms = int((time.time() - fallback_started_at) * 1000)
        if fallback_resp.status_code == 200:
            _mgmt_token_validation_cache["valid"] = True
            _mgmt_token_validation_cache["reason"] = "ok-fallback-user"
            _mgmt_token_validation_cache["expire_at"] = now + _MGMT_TOKEN_VALIDATE_TTL_SECONDS
            _debug_log(
                "Turso 管理令牌校验通过 (/auth/validate 失败后回退 /user) "
                f"| validate_ms={elapsed_ms}, fallback_ms={fallback_elapsed_ms}"
            )
            return {"checked": True, "valid": True, "reason": "ok-fallback-user", "cached": False}

        reason = f"auth-validate-http-{resp.status_code};fallback-http-{fallback_resp.status_code}"
        _mgmt_token_validation_cache["valid"] = False
        _mgmt_token_validation_cache["reason"] = reason
        _mgmt_token_validation_cache["expire_at"] = now + _MGMT_TOKEN_VALIDATE_TTL_SECONDS
        _debug_log(
            "Turso 管理令牌校验失败: "
            f"{reason} | validate_ms={elapsed_ms}, fallback_ms={fallback_elapsed_ms}",
            level="WARNING",
        )
        return {"checked": True, "valid": False, "reason": reason, "cached": False}
    except Exception as e:
        reason = f"validate-error:{e}"
        _mgmt_token_validation_cache["valid"] = False
        _mgmt_token_validation_cache["reason"] = reason
        _mgmt_token_validation_cache["expire_at"] = now + _MGMT_TOKEN_VALIDATE_TTL_SECONDS
        _debug_log(f"Turso 管理令牌校验异常: {e}", level="WARNING")
        return {"checked": True, "valid": False, "reason": reason, "cached": False}


def _fetch_turso_cloud_targets_via_api() -> List[Tuple[str, str, str]]:
    """Use Turso management API to discover history databases and generate DB auth tokens."""
    started_at = time.time()
    mgmt_token = (os.getenv("TURSO_MGMT_TOKEN") or "").strip()
    org_slug = (os.getenv("TURSO_ORG_SLUG") or "").strip()
    if not mgmt_token or not org_slug:
        return []

    validation = _validate_turso_management_token()
    if not validation.get("valid"):
        _debug_log(f"Turso API 云库发现跳过：管理令牌不可用 ({validation.get('reason')})", level="INFO")
        return []

    headers = {"Authorization": f"Bearer {mgmt_token}", "Content-Type": "application/json"}
    list_url = f"https://api.turso.tech/v1/organizations/{org_slug}/databases"
    try:
        list_started_at = time.time()
        resp = requests.get(list_url, headers=headers, timeout=12)
        list_elapsed_ms = int((time.time() - list_started_at) * 1000)
        if resp.status_code != 200:
            _debug_log(f"Turso API 获取数据库列表失败: {resp.status_code} | list_ms={list_elapsed_ms}", level="WARNING")
            return []

        dbs = resp.json().get("databases", [])
        targets: List[Tuple[str, str, str]] = []
        history_candidates = 0
        token_elapsed_total_ms = 0
        for db in dbs:
            db_name = (db.get("Name") or db.get("name") or "").strip()
            if not db_name.startswith("history-") and not db_name.startswith("history_"):
                continue
            history_candidates += 1

            hostname = (db.get("Hostname") or db.get("hostname") or "").strip()
            db_url = _normalize_turso_url(hostname)
            if not db_url:
                continue

            token_url = f"https://api.turso.tech/v1/organizations/{org_slug}/databases/{db_name}/auth/tokens"
            token_started_at = time.time()
            token_resp = requests.post(token_url, headers=headers, json={}, timeout=12)
            token_elapsed_ms = int((time.time() - token_started_at) * 1000)
            token_elapsed_total_ms += token_elapsed_ms
            if token_resp.status_code not in (200, 201):
                _debug_log(
                    f"Turso API 生成数据库令牌失败: {db_name} ({token_resp.status_code}) | token_ms={token_elapsed_ms}",
                    level="WARNING",
                )
                continue

            token_json = token_resp.json() if token_resp.text else {}
            db_token = (token_json.get("jwt") or token_json.get("token") or "").strip()
            if not db_token:
                continue

            targets.append((db_url, db_token, f"云端数据库({db_name})"))

        total_elapsed_ms = int((time.time() - started_at) * 1000)
        _debug_log(
            "Turso API 云库发现完成: "
            f"db_total={len(dbs)}, history_candidates={history_candidates}, discovered={len(targets)} "
            f"| list_ms={list_elapsed_ms}, token_total_ms={token_elapsed_total_ms}, total_ms={total_elapsed_ms}",
            level="INFO",
        )
        return targets
    except Exception as e:
        total_elapsed_ms = int((time.time() - started_at) * 1000)
        _debug_log(f"Turso API 云库发现失败: {e} | total_ms={total_elapsed_ms}", level="WARNING")
        return []


def _get_cached_turso_cloud_targets() -> List[Tuple[str, str, str]]:
    """Cache Turso API discovery result to reduce management API overhead."""
    now = time.time()
    cached_targets = _cloud_targets_cache.get("targets", [])
    if cached_targets and now < _cloud_targets_cache.get("expire_at", 0.0):
        ttl_left = int(_cloud_targets_cache.get("expire_at", 0.0) - now)
        _debug_log(f"Turso API 云库目标缓存命中: {len(cached_targets)} 个，TTL 剩余约 {ttl_left}s")
        return list(cached_targets)

    fresh_targets = _fetch_turso_cloud_targets_via_api()
    _cloud_targets_cache["targets"] = list(fresh_targets)
    _cloud_targets_cache["expire_at"] = now + _CLOUD_TARGET_CACHE_TTL_SECONDS
    _debug_log(f"Turso API 云库目标缓存刷新: {len(fresh_targets)} 个，TTL={_CLOUD_TARGET_CACHE_TTL_SECONDS}s")
    return list(fresh_targets)


def _clear_cloud_targets_cache() -> None:
    _cloud_targets_cache["targets"] = []
    _cloud_targets_cache["expire_at"] = 0.0


def _get_secret_key_bytes() -> bytes:
    """Derive symmetric key from ENCRYPTION_KEY. Empty result means secret storage disabled."""
    raw = (ENCRYPTION_KEY or "").strip()
    if not raw:
        return b""
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _encrypt_secret_value(secret: str) -> str:
    key = _get_secret_key_bytes()
    if not key:
        raise ValueError("ENCRYPTION_KEY 未配置，无法加密敏感信息")

    plain = (secret or "").encode("utf-8")
    nonce = os.urandom(16)
    stream = bytearray()
    counter = 0
    while len(stream) < len(plain):
        stream.extend(hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest())
        counter += 1

    cipher = bytes(p ^ s for p, s in zip(plain, stream[: len(plain)]))
    sig = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    blob = base64.urlsafe_b64encode(nonce + sig + cipher).decode("ascii")
    return f"v1:{blob}"


def _decrypt_secret_value(secret_blob: str) -> str:
    key = _get_secret_key_bytes()
    if not key:
        raise ValueError("ENCRYPTION_KEY 未配置，无法解密敏感信息")

    if not secret_blob:
        return ""
    if not str(secret_blob).startswith("v1:"):
        raise ValueError("不支持的密文版本")

    raw = base64.urlsafe_b64decode(secret_blob[3:].encode("ascii"))
    if len(raw) < 48:
        raise ValueError("密文长度非法")

    nonce = raw[:16]
    sig = raw[16:48]
    cipher = raw[48:]
    expect = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expect):
        raise ValueError("密文签名校验失败")

    stream = bytearray()
    counter = 0
    while len(stream) < len(cipher):
        stream.extend(hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest())
        counter += 1

    plain = bytes(c ^ s for c, s in zip(cipher, stream[: len(cipher)]))
    return plain.decode("utf-8")


def _collect_cloud_lookup_targets() -> List[Tuple[str, str, str]]:
    """Collect unique cloud targets with API-first discovery."""
    targets: List[Tuple[str, str, str]] = []
    seen_urls = set()

    def _append_target(url: Optional[str], token: Optional[str], source: str) -> None:
        nurl = (url or "").strip()
        ntoken = (token or "").strip()
        if not nurl or not ntoken or nurl in seen_urls:
            return
        seen_urls.add(nurl)
        targets.append((nurl, ntoken, source))

    # 0) current active profile cloud db (if present)
    _append_target(os.getenv("TURSO_DB_URL"), os.getenv("TURSO_AUTH_TOKEN"), "云端数据库(当前用户)")

    # 1) Turso management API discovery
    for db_url, db_token, source_label in _get_cached_turso_cloud_targets():
        _append_target(db_url, db_token, source_label)

    # 2) local profiles fallback
    try:
        profile_files = sorted([f for f in os.listdir(PROFILES_DIR) if f.endswith(".env")])
    except Exception as e:
        _debug_log(f"扫描 profiles 目录失败: {e}", level="WARNING")
        profile_files = []

    for env_file in profile_files:
        profile_name = os.path.splitext(env_file)[0]
        env_path = os.path.join(PROFILES_DIR, env_file)
        cfg = _read_profile_cloud_config(env_path)
        if not cfg:
            continue
        _append_target(cfg["url"], cfg["token"], f"云端数据库({profile_name})")

    if len(targets) > _CLOUD_LOOKUP_MAX_TARGETS:
        _debug_log(f"云库目标数量过多，已限制为前 {_CLOUD_LOOKUP_MAX_TARGETS} 个", level="WARNING")
        targets = targets[:_CLOUD_LOOKUP_MAX_TARGETS]

    return targets


def get_timestamp_with_tz() -> str:
    """Current timestamp in ISO 8601 with timezone."""
    return datetime.now(UTC_PLUS_8).isoformat()


def generate_user_id(username: str) -> str:
    """Unified user-id algorithm: first 16 chars of SHA256(lower(username))."""
    normalized = (username or "").strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def clean_for_maimemo(text: str) -> str:
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r"^#{1,6}\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^[\-\*]\s+", "• ", s, flags=re.MULTILINE)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\*(.+?)\*", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"`(.+?)`", r"\1", s)
    return s.strip()


def _is_sqlite_malformed_error(error: Exception) -> bool:
    msg = str(error or "").lower()
    return (
        "database disk image is malformed" in msg
        or "file is not a database" in msg
        or "malformed" in msg
    )


def _is_sqlite_row_decode_error(error: Exception) -> bool:
    msg = str(error or "").lower()
    return "could not decode to utf-8" in msg or ("utf-8" in msg and "decode" in msg)


def _is_sqlite_data_corruption_error(error: Exception) -> bool:
    return _is_sqlite_malformed_error(error) or _is_sqlite_row_decode_error(error)


def _is_replica_metadata_missing_error(error: Exception) -> bool:
    msg = str(error or "").lower()
    return "db file exists but metadata file does not" in msg or (
        "local state is incorrect" in msg and "metadata" in msg
    )


def _backup_broken_database_file(db_path: str, warning_message: str) -> Optional[str]:
    """Backup broken local db file and keep WAL sidecar files untouched."""
    try:
        abs_path = os.path.abspath(db_path)
        if not os.path.exists(abs_path):
            return None

        day_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
        backup_path = f"{abs_path}.er-broken-{day_tag}.bak"
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception:
                pass

        moved = False
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                shutil.move(abs_path, backup_path)
                moved = True
                break
            except OSError as move_error:
                last_error = move_error
                winerror = getattr(move_error, "winerror", None)
                if winerror == 32 or "being used by another process" in str(move_error).lower():
                    time.sleep(0.3 * (attempt + 1))
                    continue
                raise

        if not moved:
            try:
                shutil.copy2(abs_path, backup_path)
                removed_source = False
                try:
                    os.remove(abs_path)
                    removed_source = True
                except Exception:
                    _debug_log(
                        f"备份损坏数据库后无法删除源文件（可能仍被占用）: {abs_path}",
                        level="WARNING",
                    )
                if not removed_source:
                    return None
            except Exception as copy_error:
                if last_error:
                    _debug_log(f"备份损坏数据库失败: {last_error}", level="WARNING")
                _debug_log(f"备份损坏数据库失败: {copy_error}", level="WARNING")
                return None

        _debug_log(
            f"{warning_message}: {backup_path}\n"
            "注意：副本文件已备份，但相关 WAL 元数据未删除（避免多线程竞争导致损坏）",
            level="WARNING",
        )
        return backup_path
    except Exception as backup_error:
        _debug_log(f"备份损坏数据库失败: {backup_error}", level="WARNING")
        return None


def _backup_broken_replica_file(db_path: str) -> Optional[str]:
    return _backup_broken_database_file(db_path, "检测到本地副本损坏，已备份本地副本")


def _get_cloud_lookup_replica_path(cloud_url: str) -> str:
    """Get isolated local replica path for cross-db cloud lookup."""
    lookup_dir = os.path.join(DATA_DIR, "profiles", ".cloud_lookup_replicas")
    os.makedirs(lookup_dir, exist_ok=True)
    fp = _hash_fingerprint((cloud_url or "").strip())
    return os.path.join(lookup_dir, f"lookup_{fp}.db")
