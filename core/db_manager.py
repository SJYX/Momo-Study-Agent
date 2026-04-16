# -*- coding: utf-8 -*-
import sqlite3, os, json, re, hashlib, shutil, time, hmac, base64, threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple, List, Any, Callable
import requests
from urllib.parse import urlparse
from config import ACTIVE_USER, DB_PATH, TEST_DB_PATH, DATA_DIR, PROFILES_DIR, TURSO_HUB_DB_URL, TURSO_HUB_AUTH_TOKEN, HUB_DB_PATH, FORCE_CLOUD_MODE, ENCRYPTION_KEY

TURSO_DB_URL = os.getenv('TURSO_DB_URL')
TURSO_AUTH_TOKEN = os.getenv('TURSO_AUTH_TOKEN')
TURSO_DB_HOSTNAME = os.getenv('TURSO_DB_HOSTNAME')
TURSO_TEST_DB_URL = os.getenv('TURSO_TEST_DB_URL')
TURSO_TEST_AUTH_TOKEN = os.getenv('TURSO_TEST_AUTH_TOKEN')
TURSO_TEST_DB_HOSTNAME = os.getenv('TURSO_TEST_DB_HOSTNAME')

try:
    import libsql_client
    HAS_LIBSQL = True
except ImportError:
    HAS_LIBSQL = False
# 导入日志系统
try:
    from .logger import ContextLogger, log_performance, get_logger
    import logging
except ImportError:
    # 如果导入失败，提供简单的替代
    class ContextLogger:
        def __init__(self, logger): self.logger = logger
        def info(self, *args, **kwargs): pass
        def error(self, *args, **kwargs): pass
        def debug(self, *args, **kwargs): pass
    
    def log_performance(logger_func):
        def decorator(func):
            return func
        return decorator
    def get_logger():
        import logging
        return ContextLogger(logging.getLogger(__name__))

# 表存在状态缓存（避免重复检查）
_table_exists_cache = {}
_cloud_targets_cache = {"expire_at": 0.0, "targets": []}
_CLOUD_TARGET_CACHE_TTL_SECONDS = int(os.getenv("CLOUD_TARGET_CACHE_TTL_SECONDS", "600"))
_CLOUD_LOOKUP_MAX_TARGETS = int(os.getenv("CLOUD_LOOKUP_MAX_TARGETS", "40"))
_MGMT_TOKEN_VALIDATE_TTL_SECONDS = int(os.getenv("MGMT_TOKEN_VALIDATE_TTL_SECONDS", "300"))
_mgmt_token_validation_cache = {"expire_at": 0.0, "valid": None, "reason": ""}
_HUB_INIT_STATE_TTL_SECONDS = int(os.getenv("HUB_INIT_STATE_TTL_SECONDS", "600"))
_HUB_SCHEMA_VERSION = os.getenv("HUB_SCHEMA_VERSION", "1")
_hub_init_state_cache = {"expire_at": 0.0, "state": None}
_throttled_log_state = {}
_throttled_log_lock = threading.Lock()
UTC_PLUS_8 = timezone(timedelta(hours=8))

def _hash_fingerprint(raw: str) -> str:
    """将连接标识压缩成短哈希，避免 marker 文件名过长。"""
    return hashlib.sha256((raw or "unknown").encode("utf-8")).hexdigest()[:12]

def _main_db_fingerprint(db_path: str = None) -> str:
    """主数据库实例指纹：优先云端 URL，其次本地绝对路径。"""
    is_test = db_path and 'test_' in os.path.basename(db_path)
    url = TURSO_TEST_DB_URL if is_test else TURSO_DB_URL
    if not url:
        hostname = TURSO_TEST_DB_HOSTNAME if is_test else TURSO_DB_HOSTNAME
        if hostname:
            url = _normalize_turso_url(hostname)
    if url:
        return f"cloud:{url.strip()}"
    path = os.path.abspath(db_path or DB_PATH)
    return f"local:{path}"

def _hub_db_fingerprint() -> str:
    """Hub 数据库实例指纹。"""
    if TURSO_HUB_DB_URL:
        return f"cloud:{TURSO_HUB_DB_URL.strip()}"
    return f"local:{os.path.abspath(HUB_DB_PATH)}"


def _hub_init_state_path() -> str:
    marker_dir = os.path.join(DATA_DIR, "db_init_markers")
    os.makedirs(marker_dir, exist_ok=True)
    return os.path.join(marker_dir, "hub_init_state.json")


def _load_hub_init_state(force_refresh: bool = False) -> Optional[dict]:
    now = time.time()
    if not force_refresh and _hub_init_state_cache.get("state") and now < _hub_init_state_cache.get("expire_at", 0.0):
        return _hub_init_state_cache["state"]

    path = _hub_init_state_path()
    if not os.path.exists(path):
        _hub_init_state_cache["state"] = None
        _hub_init_state_cache["expire_at"] = now + _HUB_INIT_STATE_TTL_SECONDS
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if isinstance(state, dict):
            _hub_init_state_cache["state"] = state
            _hub_init_state_cache["expire_at"] = now + _HUB_INIT_STATE_TTL_SECONDS
            return state
    except Exception as e:
        _debug_log(f"读取 Hub 初始化状态失败: {e}")

    _hub_init_state_cache["state"] = None
    _hub_init_state_cache["expire_at"] = now + _HUB_INIT_STATE_TTL_SECONDS
    return None


def _save_hub_init_state(state: dict) -> None:
    path = _hub_init_state_path()
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        _hub_init_state_cache["state"] = state
        _hub_init_state_cache["expire_at"] = time.time() + _HUB_INIT_STATE_TTL_SECONDS
    except Exception as e:
        _debug_log(f"保存 Hub 初始化状态失败: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _hub_init_state_is_fresh(hub_fp: str) -> bool:
    state = _load_hub_init_state()
    if not state:
        return False

    if state.get("hub_fp") != hub_fp:
        return False
    if state.get("schema_version") != _HUB_SCHEMA_VERSION:
        return False

    last_success_at = float(state.get("last_success_at", 0.0) or 0.0)
    if not last_success_at:
        return False

    return (time.time() - last_success_at) <= _HUB_INIT_STATE_TTL_SECONDS

def _get_db_init_marker_path(db_type: str, db_fingerprint: str = None) -> str:
    """获取数据库初始化标记文件路径"""
    marker_dir = os.path.join(DATA_DIR, "db_init_markers")
    os.makedirs(marker_dir, exist_ok=True)
    if db_fingerprint:
        digest = _hash_fingerprint(db_fingerprint)
        return os.path.join(marker_dir, f"{db_type}_{digest}_initialized.flag")
    return os.path.join(marker_dir, f"{db_type}_initialized.flag")

def _is_db_initialized(db_type: str, db_fingerprint: str = None) -> bool:
    """检查数据库是否已经初始化（通过本地标记文件）"""
    marker_path = _get_db_init_marker_path(db_type, db_fingerprint)
    return os.path.exists(marker_path)

def _mark_db_initialized(db_type: str, db_fingerprint: str = None):
    """标记数据库已初始化"""
    marker_path = _get_db_init_marker_path(db_type, db_fingerprint)
    with open(marker_path, 'w') as f:
        f.write(f"initialized at {time.time()}")

def _check_table_exists(cursor, table_name: str, db_type: str = "main", cache_scope: str = None) -> bool:
    """检查表是否存在，使用缓存避免重复查询

    Args:
        cursor: 数据库游标
        table_name: 表名
        db_type: 数据库类型 ("main" 或 "hub")
    """
    # 使用数据库类型 + 连接作用域 + 表名作为缓存键，避免跨库误复用
    scope = cache_scope or "default"
    cache_key = f"{db_type}_{scope}_{table_name}"

    # 检查缓存
    if cache_key in _table_exists_cache:
        return _table_exists_cache[cache_key]

    # 执行查询
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    exists = cursor.fetchone() is not None

    # 更新缓存
    _table_exists_cache[cache_key] = exists
    return exists

def _debug_log(msg, start_time=None, level="DEBUG", module="db_manager"):
    """利用现有日志系统的可分级调试函数
    
    Args:
        msg: 日志消息
        start_time: 操作开始时间（用于计算耗时）
        level: 日志级别 ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        module: 模块名称（用于模块级别过滤）
    """
    
    # 计算耗时
    elapsed = f' | Time: {int((time.time() - start_time)*1000)}ms' if start_time else ''
    log_msg = f"{msg}{elapsed}"
    
    try:
        logger = get_logger()
        level_map = {
            "CRITICAL": logger.critical,
            "ERROR": logger.error,
            "WARNING": logger.warning,
            "INFO": logger.info,
            "DEBUG": logger.debug,
        }
        
        log_func = level_map.get(level, logger.debug)
        log_func(log_msg, module=module)
    except Exception:
        # 如果日志失败，忽略错误，避免影响主流程
        pass


def _debug_log_throttled(key: str, msg: str, interval_seconds: float = 30.0, start_time=None, level="DEBUG", module="db_manager"):
    """按 key 对高频日志进行限频，减少重复刷屏。"""
    now = time.time()
    should_log = False
    with _throttled_log_lock:
        last_ts = float(_throttled_log_state.get(key, 0.0) or 0.0)
        if now - last_ts >= float(interval_seconds):
            _throttled_log_state[key] = now
            should_log = True

    if should_log:
        _debug_log(msg, start_time=start_time, level=level, module=module)

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
        _debug_log(f"读取 profile 云配置失败: {profile_env_path} -> {e}")
    return None

def _validate_turso_management_token(force_refresh: bool = False) -> Dict[str, Any]:
    """Validate Turso management token once per TTL to avoid repeated slow failures."""
    now = time.time()
    mgmt_token = (os.getenv("TURSO_MGMT_TOKEN") or "").strip()
    if not mgmt_token:
        return {"checked": False, "valid": False, "reason": "missing-mgmt-token"}

    if not force_refresh and _mgmt_token_validation_cache.get("valid") is not None and now < _mgmt_token_validation_cache.get("expire_at", 0.0):
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

        # 兼容不同 token 类型与后端能力差异：主校验失败时回退 /v1/user
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
            f"{reason} | validate_ms={elapsed_ms}, fallback_ms={fallback_elapsed_ms}"
        )
        return {"checked": True, "valid": False, "reason": reason, "cached": False}
    except Exception as e:
        reason = f"validate-error:{e}"
        _mgmt_token_validation_cache["valid"] = False
        _mgmt_token_validation_cache["reason"] = reason
        _mgmt_token_validation_cache["expire_at"] = now + _MGMT_TOKEN_VALIDATE_TTL_SECONDS
        _debug_log(f"Turso 管理令牌校验异常: {e}")
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
        _debug_log(f"Turso API 云库发现跳过：管理令牌不可用 ({validation.get('reason')})")
        return []

    headers = {"Authorization": f"Bearer {mgmt_token}", "Content-Type": "application/json"}
    list_url = f"https://api.turso.tech/v1/organizations/{org_slug}/databases"
    try:
        list_started_at = time.time()
        resp = requests.get(list_url, headers=headers, timeout=12)
        list_elapsed_ms = int((time.time() - list_started_at) * 1000)
        if resp.status_code != 200:
            _debug_log(f"Turso API 获取数据库列表失败: {resp.status_code} | list_ms={list_elapsed_ms}")
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
                _debug_log(f"Turso API 生成数据库令牌失败: {db_name} ({token_resp.status_code}) | token_ms={token_elapsed_ms}")
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
            f"| list_ms={list_elapsed_ms}, token_total_ms={token_elapsed_total_ms}, total_ms={total_elapsed_ms}"
        )
        return targets
    except Exception as e:
        total_elapsed_ms = int((time.time() - started_at) * 1000)
        _debug_log(f"Turso API 云库发现失败: {e} | total_ms={total_elapsed_ms}")
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
    return fresh_targets

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

    cipher = bytes(p ^ s for p, s in zip(plain, stream[:len(plain)]))
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

    plain = bytes(c ^ s for c, s in zip(cipher, stream[:len(cipher)]))
    return plain.decode("utf-8")

def _collect_cloud_lookup_targets() -> List[Tuple[str, str, str]]:
    """Collect unique cloud targets with API-first discovery.

    Returns:
        list[(url, token, source_label)]
    """
    targets: List[Tuple[str, str, str]] = []
    seen_urls = set()

    def _append_target(url: str, token: str, source: str):
        nurl = (url or "").strip()
        ntoken = (token or "").strip()
        if not nurl or not ntoken or nurl in seen_urls:
            return
        seen_urls.add(nurl)
        targets.append((nurl, ntoken, source))

    # 0. 当前用户云库始终优先
    _append_target(TURSO_DB_URL, TURSO_AUTH_TOKEN, "云端数据库(当前用户)")

    # 1. 优先通过 Turso 管理 API 发现数据库（避免完全依赖本地 env）
    for db_url, db_token, source_label in _get_cached_turso_cloud_targets():
        _append_target(db_url, db_token, source_label)

    # 2. 回退到本地 profiles 配置
    try:
        profile_files = sorted([f for f in os.listdir(PROFILES_DIR) if f.endswith(".env")])
    except Exception as e:
        _debug_log(f"扫描 profiles 目录失败: {e}")
        profile_files = []

    for env_file in profile_files:
        profile_name = os.path.splitext(env_file)[0]
        env_path = os.path.join(PROFILES_DIR, env_file)
        cfg = _read_profile_cloud_config(env_path)
        if not cfg:
            continue

        _append_target(cfg["url"], cfg["token"], f"云端数据库({profile_name})")

    if len(targets) > _CLOUD_LOOKUP_MAX_TARGETS:
        _debug_log(f"云库目标数量过多，已限制为前 {_CLOUD_LOOKUP_MAX_TARGETS} 个")
        targets = targets[:_CLOUD_LOOKUP_MAX_TARGETS]

    return targets

def get_timestamp_with_tz() -> str:
    """获取当前时间戳，格式为 ISO 8601 含时区。"""
    return datetime.now(UTC_PLUS_8).isoformat()

def generate_user_id(username: str) -> str:
    """统一用户 ID 生成算法：SHA256(username) 的前 16 位"""
    import hashlib
    normalized = username.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]

def clean_for_maimemo(text: str) -> str:
    if text is None: return ''
    text = re.sub(r'^#{1,6}\s+', '', str(text), flags=re.MULTILINE)
    text = re.sub(r'^[\-\*]\s+', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'`(.+?)`', r'\1', text)
    return text.strip()

def _get_local_conn(db_path: str = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=20.0)  # 增加超时时间以解决多线程死锁
    conn.row_factory = sqlite3.Row
    # 启用WAL模式以提高并发性能
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


class _LibsqlCompatCursor:
    """将 libsql_client 的同步结果包装成 sqlite3 风格接口。"""

    def __init__(self, client):
        self._client = client
        self._result = None
        self.description = None

    def execute(self, sql, params=()):
        self._result = self._client.execute(sql, params)
        self.description = [(col, None, None, None, None, None, None) for col in (self._result.columns or [])]
        return self

    def executemany(self, sql, seq_of_params):
        last_result = None
        for params in seq_of_params:
            last_result = self._client.execute(sql, params)
        self._result = last_result
        self.description = [(col, None, None, None, None, None, None) for col in (self._result.columns or [])] if self._result else None
        return self

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None

    def fetchall(self):
        if not self._result:
            return []
        return list(self._result.rows or [])

    @property
    def lastrowid(self):
        if not self._result:
            return None
        return self._result.last_insert_rowid

    def close(self):
        return None


class _LibsqlCompatConnection:
    """提供 sqlite3 兼容的连接对象。"""

    def __init__(self, client):
        self._client = client
        self.row_factory = None

    def cursor(self):
        return _LibsqlCompatCursor(self._client)

    def commit(self):
        return None

    def close(self):
        if hasattr(self._client, 'close'):
            self._client.close()


def _get_cloud_conn(url: str, token: str):
    raw = (url or '').strip()
    if not raw:
        raise ValueError('cloud url is empty')

    # Some environments/proxies break websocket handshake (505).
    # Try multiple endpoint schemes to maximize compatibility.
    host = raw
    if '://' in raw:
        host = raw.split('://', 1)[1].split('/', 1)[0]

    candidates: List[str] = []
    if raw.startswith('libsql://'):
        candidates = [f'libsql://{host}', f'https://{host}', f'wss://{host}/']
    elif raw.startswith('https://') or raw.startswith('http://'):
        scheme_host = f'https://{host}' if raw.startswith('http') else raw
        candidates = [scheme_host, f'libsql://{host}', f'wss://{host}/']
    elif raw.startswith('wss://') or raw.startswith('ws://'):
        candidates = [f'wss://{host}/', f'libsql://{host}', f'https://{host}']
    else:
        candidates = [f'libsql://{host}', f'https://{host}', f'wss://{host}/']

    seen = set()
    ordered_candidates = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered_candidates.append(c)

    errors = []
    for candidate in ordered_candidates:
        client = None
        try:
            client = libsql_client.create_client_sync(candidate, auth_token=token)
            # Probe once so bad handshakes fail here, not in later business logic.
            client.execute('SELECT 1')
            return _LibsqlCompatConnection(client)
        except Exception as e:
            errors.append(f'{candidate} -> {e}')
            if client and hasattr(client, 'close'):
                try:
                    client.close()
                except Exception:
                    pass

    raise RuntimeError('all cloud connection attempts failed: ' + ' | '.join(errors))

def _is_cloud_connection(conn: Any) -> bool:
    """判断连接是否为 libsql 云端连接（避免依赖 __str__ 输出格式）。"""
    try:
        return conn.__class__.__name__ == '_LibsqlCompatConnection'
    except Exception:
        return False

def _normalize_turso_url(hostname: str) -> str:
    """Normalize Turso endpoint to libsql://host form expected by libsql client."""
    if not hostname:
        return ''
    raw = hostname.strip()
    if raw.startswith('libsql://'):
        return raw
    if raw.startswith('wss://') or raw.startswith('ws://') or raw.startswith('https://') or raw.startswith('http://'):
        parsed = urlparse(raw)
        host = parsed.netloc or parsed.path
        return f'libsql://{host}'
    return f'libsql://{raw}'

def _get_conn(db_path: str, max_retries: int = 3, retry_delay: float = 1.0) -> Any:
    """获取数据库连接（优先云端 Turso，无配置则回退本地 SQLite）

    Args:
        db_path: 数据库路径
        max_retries: 最大重试次数（默认 3 次）
        retry_delay: 每次重试的延迟秒数（默认 1.0 秒）
    """
    # 如果 db_path 为 None，使用默认路径
    if db_path is None:
        db_path = DB_PATH

    target_abs = os.path.abspath(db_path)
    main_abs = os.path.abspath(DB_PATH)
    is_test = 'test_' in os.path.basename(db_path)
    url = TURSO_TEST_DB_URL if is_test else TURSO_DB_URL
    token = TURSO_TEST_AUTH_TOKEN if is_test else TURSO_AUTH_TOKEN

    if not url:
        hostname = TURSO_TEST_DB_HOSTNAME if is_test else TURSO_DB_HOSTNAME
        if hostname:
            url = _normalize_turso_url(hostname)

    # 强制云端模式检查
    from config import get_force_cloud_mode
    if get_force_cloud_mode() and not url:
        raise RuntimeError("强制云端模式已启用，但未配置 TURSO_DB_URL 或 TURSO_DB_HOSTNAME")

    # 判断是否为主数据库（需要连接云端）
    is_main_db = target_abs == main_abs

    if (is_main_db or is_test) and url and token and HAS_LIBSQL:
        last_error = None
        for attempt in range(max_retries):
            try:
                _debug_log_throttled(
                    key=f"cloud-connect-attempt:{'test' if is_test else 'main'}",
                    msg=f"尝试连接云端数据库 (第 {attempt + 1}/{max_retries} 次)",
                    interval_seconds=30.0,
                )
                return _get_cloud_conn(url, token)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:  # 不是最后一次尝试
                    _debug_log(f"云端连接失败 (尝试 {attempt + 1})，{retry_delay} 秒后重试: {e}")
                    time.sleep(retry_delay)
                else:
                    _debug_log(f"云端连接失败 (已尝试 {max_retries} 次)，回退本地: {e}")

        # 若主配置连接失败，尝试通过 Turso 管理 API 发现当前用户目标库并重连
        if not is_test:
            try:
                preferred_db_name = f"history-{(ACTIVE_USER or '').lower()}"
                for candidate_url, candidate_token, source_label in _get_cached_turso_cloud_targets():
                    if preferred_db_name not in source_label:
                        continue
                    _debug_log(f"尝试 API 发现的用户库连接: {source_label}")
                    return _get_cloud_conn(candidate_url, candidate_token)
            except Exception as fallback_error:
                _debug_log(f"API 发现用户库重连失败: {fallback_error}")

        if get_force_cloud_mode():
            # 强制模式下，连接失败直接抛出异常
            raise RuntimeError(f"强制云端模式连接失败 (已尝试 {max_retries} 次): {last_error}")

    # 非强制模式或测试模式下允许回退本地
    if not get_force_cloud_mode() or is_test:
        _debug_log(f"回退到本地数据库: {db_path}")
        return _get_local_conn(db_path)

    # 强制模式下如果到这里说明配置有问题
    raise RuntimeError("强制云端模式已启用，但无法连接到云端数据库")

def _create_tables(cur, skip_migrations=False):
    """
    创建数据库表结构

    Args:
        cur: 数据库游标
        skip_migrations: 是否跳过迁移操作（列添加、数据更新）
                        用于云端数据库初始化，避免重复执行耗时操作
    """
    # 创建表（如果不存在）
    cur.execute('CREATE TABLE IF NOT EXISTS processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS ai_word_notes (voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, ielts_focus TEXT, collocations TEXT, traps TEXT, synonyms TEXT, discrimination TEXT, example_sentences TEXT, memory_aid TEXT, word_ratings TEXT, raw_full_text TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, batch_id TEXT, original_meanings TEXT, maimemo_context TEXT, content_origin TEXT, content_source_db TEXT, content_source_scope TEXT, it_level INTEGER DEFAULT 0, it_history TEXT, sync_status INTEGER DEFAULT 0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS ai_word_iterations (id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT NOT NULL, spelling TEXT, stage TEXT, it_level INTEGER, score REAL, justification TEXT, tags TEXT, refined_content TEXT, candidate_notes TEXT, raw_response TEXT, maimemo_context TEXT, batch_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(voc_id) REFERENCES ai_word_notes(voc_id))')
    cur.execute('CREATE TABLE IF NOT EXISTS word_progress_history (id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT, familiarity_short REAL, familiarity_long REAL, review_count INTEGER, it_level INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    # 添加联合唯一约束，避免历史记录冗余同步
    try: cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_progress_unique ON word_progress_history (voc_id, created_at, review_count)')
    except: pass
    cur.execute('CREATE TABLE IF NOT EXISTS ai_batches (batch_id TEXT PRIMARY KEY, request_id TEXT, ai_provider TEXT, model_name TEXT, prompt_version TEXT, batch_size INTEGER, total_latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, finish_reason TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS test_run_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, total_count INTEGER, sample_count INTEGER, sample_words TEXT, ai_calls INTEGER, success_parsed INTEGER, is_dry_run BOOLEAN, error_msg TEXT, ai_results_json TEXT)')

    # 添加缺失的列（云端也需要，避免旧库缺少新字段）
    for t, c, d in [
        ('ai_word_notes', 'it_level',          'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'it_history',         'TEXT'),
        ('ai_word_notes', 'prompt_tokens',      'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'completion_tokens',  'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'total_tokens',       'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'batch_id',           'TEXT'),
        ('ai_word_notes', 'original_meanings',  'TEXT'),
        ('ai_word_notes', 'maimemo_context',    'TEXT'),
        ('ai_word_notes', 'content_origin',     'TEXT'),
        ('ai_word_notes', 'content_source_db',  'TEXT'),
        ('ai_word_notes', 'content_source_scope','TEXT'),
        ('ai_word_notes', 'raw_full_text',      'TEXT'),
        ('ai_word_notes', 'word_ratings',       'TEXT'),
        ('ai_word_notes', 'sync_status',        'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'updated_at',         'TIMESTAMP'),
        ('processed_words', 'updated_at',      'TIMESTAMP'),
    ]:
        try:
            cur.execute(f'ALTER TABLE {t} ADD COLUMN {c} {d}')
            _debug_log(f"  列添加成功: {t}.{c}")
        except Exception as e:
            if "duplicate column name" not in str(e).lower():
                _debug_log(f"  列添加失败: {t}.{c} -> {e}")

    try:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS ai_word_iterations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voc_id TEXT NOT NULL,
                spelling TEXT,
                stage TEXT,
                it_level INTEGER,
                score REAL,
                justification TEXT,
                tags TEXT,
                refined_content TEXT,
                candidate_notes TEXT,
                raw_response TEXT,
                maimemo_context TEXT,
                batch_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(voc_id) REFERENCES ai_word_notes(voc_id)
            )
        ''')
    except Exception as e:
        _debug_log(f"  ai_word_iterations 创建/校验失败: {e}")

    # 跳过旧数据回填操作（用于云端数据库初始化）
    if skip_migrations:
        return

    # 手动为旧数据补齐时间戳，确保同步逻辑能正常运行
    try:
        cur.execute("UPDATE ai_word_notes SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
        cur.execute("UPDATE processed_words SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")

        # 为历史笔记补齐来源字段：
        # - 有 batch_id 的旧记录，默认视为历史 AI 生成
        # - 没有任何来源线索的旧记录，标记为 legacy_unknown
        cur.execute("UPDATE ai_word_notes SET content_origin = 'ai_generated', content_source_scope = 'ai_batch' WHERE content_origin IS NULL AND batch_id IS NOT NULL")
        cur.execute("UPDATE ai_word_notes SET content_origin = 'legacy_unknown', content_source_scope = 'legacy' WHERE content_origin IS NULL AND batch_id IS NULL")
    except: pass

@log_performance(lambda: ContextLogger(logging.getLogger(__name__)))
def init_db(db_path: str = None):
    """初始化数据库，确保本地和云端 schema 一致。"""
    path = db_path or DB_PATH
    start_time = time.time()

    # 1. 首先确保本地数据库 schema 是最新的
    try:
        lc = _get_local_conn(path)
        lcur = lc.cursor()
        _create_tables(lcur)
        lc.commit()
        lc.close()
        _debug_log("本地数据库初始化/迁移完成", start_time)
    except Exception as e:
        _debug_log(f"本地数据库初始化失败: {e}", start_time)

    # 2. 如果配置了云端，尝试初始化云端（跳过耗时的迁移操作）
    if HAS_LIBSQL and TURSO_DB_URL and TURSO_AUTH_TOKEN:
        try:
            main_fp = _main_db_fingerprint(path)
            # 检查是否已经初始化过（通过本地标记文件）
            if _is_db_initialized("main", main_fp):
                _debug_log("云端数据库已初始化（通过标记文件），跳过检查")
            else:
                cloud_start = time.time()
                cc = _get_cloud_conn(TURSO_DB_URL, TURSO_AUTH_TOKEN)
                _debug_log("云端数据库连接完成", cloud_start)

                ccur = cc.cursor()

                # 检查表是否已存在（避免重复执行耗时的 CREATE TABLE 操作）
                check_start = time.time()
                table_exists = _check_table_exists(ccur, "processed_words", "main", cache_scope=main_fp)
                _debug_log(f"表存在检查完成 (存在: {table_exists})", check_start)

                if table_exists:
                    _debug_log("云端数据库表已存在，跳过初始化")
                else:
                    create_start = time.time()
                    _create_tables(ccur, skip_migrations=True)  # 跳过迁移操作，提高启动速度
                    _debug_log("云端数据库存储初始化完成（跳过迁移）", create_start)

                # 标记数据库已初始化
                _mark_db_initialized("main", main_fp)
                cc.commit()
                cc.close()
        except Exception as e:
            _debug_log(f"云端数据库初始化失败 (可能网络不通): {e}")

    # 3. 确保 Hub 数据库表结构完整
    hub_start = time.time()
    init_users_hub_tables()
    _debug_log("Hub 数据库初始化完成", hub_start)

@log_performance(lambda: ContextLogger(logging.getLogger(__name__)))
def get_processed_ids_in_batch(voc_ids: list, db_path: str = None) -> set:
    if not voc_ids: return set()
    s = time.time()
    c = _get_conn(db_path or DB_PATH); cur = c.cursor()
    vs = [str(v) for v in voc_ids]; ph = ','.join(['?']*len(vs))
    cur.execute(f'SELECT voc_id FROM processed_words WHERE voc_id IN ({ph})', vs)
    res = {str(r[0] if isinstance(r, (tuple,list)) else r['voc_id']) for r in cur.fetchall()}
    c.close(); _debug_log(f'批量查询 ({len(voc_ids)} 词)', s)
    return res

def is_processed(voc_id: str, db_path: str = None) -> bool:
    c = _get_conn(db_path or DB_PATH); cur = c.cursor(); cur.execute('SELECT 1 FROM processed_words WHERE voc_id = ?', (str(voc_id),))
    res = cur.fetchone() is not None; c.close(); return res

def mark_processed(voc_id: str, spelling: str, db_path: str = None, conn: Any = None):
    """支持连接复用的标记处理函数"""
    def _do_sql(cn):
        cur = cn.cursor()
        cur.execute('INSERT OR REPLACE INTO processed_words (voc_id, spelling, updated_at) VALUES (?, ?, ?)', (str(voc_id), spelling, get_timestamp_with_tz()))
        if not conn: cn.commit(); cn.close()

    if conn:
        _do_sql(conn)
    else:
        path = db_path or DB_PATH
        # 优先写入云端
        try:
            cloud_conn = _get_conn(path)
            if _is_cloud_connection(cloud_conn):
                _do_sql(cloud_conn)
                # 同步到本地缓存
                try:
                    _do_sql(_get_local_conn(path))
                except Exception as local_sync_error:
                    _debug_log(f"mark_processed 本地缓存同步失败: {local_sync_error}")
            else:
                # 本地连接，写入本地
                _do_sql(cloud_conn)
        except Exception as cloud_write_error:
            _debug_log(f"mark_processed 云端写入失败，回退本地: {cloud_write_error}")
            # 云端失败，写入本地
            _do_sql(_get_local_conn(path))

def log_progress_snapshots(words: List[dict], db_path: str = None):
    if not words: return 0
    s_all = time.time()
    c = _get_conn(db_path or DB_PATH); cur = c.cursor()
    vids = [str(w['voc_id']) for w in words]; ph = ','.join(['?']*len(vids))
    cur.execute(f'SELECT voc_id, it_level FROM ai_word_notes WHERE voc_id IN ({ph})', vids)
    itm = {str(r[0]): r[1] for r in cur.fetchall()}
    cur.execute(f'SELECT voc_id, familiarity_short, review_count FROM word_progress_history WHERE voc_id IN ({ph}) ORDER BY created_at DESC', vids)
    lh = {}
    for r in cur.fetchall():
        v = str(r[0]); 
        if v not in lh: lh[v] = (r[1], r[2])
    ins = []
    for w in words:
        v = str(w['voc_id']); nf = w.get('short_term_familiarity', 0) or w.get('voc_familiarity', 0); nr = w.get('review_count', 0); l = lh.get(v)
        if not l or abs(l[0]-float(nf))>0.01 or l[1]!=int(nr):
            ins.append((v, nf, w.get('long_term_familiarity',0), nr, itm.get(v,0)))
    if ins:
        cur.executemany('INSERT INTO word_progress_history (voc_id, familiarity_short, familiarity_long, review_count, it_level) VALUES (?, ?, ?, ?, ?)', ins)
        c.commit()
    c.close(); _debug_log(f'进度同步 ({len(ins)} 条)', s_all)
    return len(ins)

@log_performance(lambda: ContextLogger(logging.getLogger(__name__)))
def save_ai_word_note(voc_id: str, payload: dict, db_path: str = None, metadata: dict = None, conn: Any = None):
    """支持连接复用的笔记保存函数"""
    s = payload.get('spelling', '')
    # raw_full_text 应为该词条自身原始 AI 输出的 JSON 字符串（由客户端设置）；
    # fallback 时序列化整个 payload（去掉 raw_full_text 自身，避免循环）以保留完整信息
    _raw_candidate = {k: v for k, v in payload.items() if k != 'raw_full_text'}
    t = payload.get('raw_full_text') or json.dumps(_raw_candidate, ensure_ascii=False)
    m_ctx = json.dumps(metadata.get('maimemo_context', {}), ensure_ascii=False) if metadata and metadata.get('maimemo_context') else None
    def _c(f): return clean_for_maimemo(payload.get(f, ''))
    original_meanings = metadata.get('original_meanings') if metadata else None
    if not original_meanings:
        original_meanings = payload.get('original_meanings')
    content_origin = (metadata.get('content_origin') if metadata else None) or payload.get('content_origin') or 'ai_generated'
    content_source_db = (metadata.get('content_source_db') if metadata else None) or payload.get('content_source_db')
    content_source_scope = (metadata.get('content_source_scope') if metadata else None) or payload.get('content_source_scope')
    args = (str(voc_id), s, _c('basic_meanings'), _c('ielts_focus'), _c('collocations'), _c('traps'), _c('synonyms'), _c('discrimination'), _c('example_sentences'), _c('memory_aid'), _c('word_ratings'), t, payload.get('prompt_tokens', 0), payload.get('completion_tokens', 0), payload.get('total_tokens', 0), metadata.get('batch_id') if metadata else None, original_meanings, m_ctx, content_origin, content_source_db, content_source_scope, 0, get_timestamp_with_tz())
    sql = 'INSERT OR REPLACE INTO ai_word_notes (voc_id, spelling, basic_meanings, ielts_focus, collocations, traps, synonyms, discrimination, example_sentences, memory_aid, word_ratings, raw_full_text, prompt_tokens, completion_tokens, total_tokens, batch_id, original_meanings, maimemo_context, content_origin, content_source_db, content_source_scope, sync_status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'

    def _do_sql(cn):
        cur = cn.cursor(); cur.execute(sql, args)
        if not conn: cn.commit(); cn.close()

    if conn:
        _do_sql(conn)
    else:
        path = db_path or DB_PATH
        # 优先写入云端
        try:
            cloud_conn = _get_conn(path)
            if _is_cloud_connection(cloud_conn):
                _do_sql(cloud_conn)
                # 同步到本地缓存
                try:
                    _do_sql(_get_local_conn(path))
                except Exception as local_sync_error:
                    _debug_log(f"save_ai_word_note 本地缓存同步失败: {local_sync_error}")
            else:
                # 本地连接，写入本地
                _do_sql(cloud_conn)
        except Exception as cloud_write_error:
            _debug_log(f"save_ai_word_note 云端写入失败，回退本地: {cloud_write_error}")
            # 云端失败，写入本地
            _do_sql(_get_local_conn(path))


def save_ai_word_notes_batch(notes_data: List[Dict[str, Any]], db_path: str = None, conn: Any = None) -> bool:
    """批量保存 AI 笔记到本地数据库（后台同步到云端）

    Args:
        notes_data: 笔记数据列表，每个元素包含 voc_id, payload, metadata
        db_path: 数据库路径
        conn: 可选的数据库连接（用于复用连接）

    Returns:
        是否保存成功
    """
    if not notes_data:
        return True

    need_close = False
    try:
        if conn:
            target_conn = conn
        else:
            # 直接使用本地数据库连接，避免云端连接延迟
            # 后台同步机制会自动将数据同步到云端
            target_conn = _get_local_conn(db_path or DB_PATH)
            need_close = True

        cur = target_conn.cursor()
        sql = 'INSERT OR REPLACE INTO ai_word_notes (voc_id, spelling, basic_meanings, ielts_focus, collocations, traps, synonyms, discrimination, example_sentences, memory_aid, word_ratings, raw_full_text, prompt_tokens, completion_tokens, total_tokens, batch_id, original_meanings, maimemo_context, content_origin, content_source_db, content_source_scope, sync_status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'

        batch_args = []
        for data in notes_data:
            voc_id = data.get('voc_id')
            payload = data.get('payload', {})
            metadata = data.get('metadata', {})

            s = payload.get('spelling', '')
            _raw_candidate = {k: v for k, v in payload.items() if k != 'raw_full_text'}
            t = payload.get('raw_full_text') or json.dumps(_raw_candidate, ensure_ascii=False)
            m_ctx = json.dumps(metadata.get('maimemo_context', {}), ensure_ascii=False) if metadata and metadata.get('maimemo_context') else None
            def _c(f): return clean_for_maimemo(payload.get(f, ''))

            original_meanings = metadata.get('original_meanings') if metadata else None
            if not original_meanings:
                original_meanings = payload.get('original_meanings')
            content_origin = (metadata.get('content_origin') if metadata else None) or payload.get('content_origin') or 'ai_generated'
            content_source_db = (metadata.get('content_source_db') if metadata else None) or payload.get('content_source_db')
            content_source_scope = (metadata.get('content_source_scope') if metadata else None) or payload.get('content_source_scope')
            
            # 根据 content_origin 决定初始同步状态
            # - ai_generated: 需要同步 (sync_status=0)
            # - 其他: 已从云端/历史查到，无须当前用户同步 (sync_status=1)
            if content_origin == 'ai_generated':
                initial_sync_status = 0
            elif content_origin in ('community_reused', 'current_db_reused', 'history_reused'):
                initial_sync_status = 1  # 这些内容已在云端，标记为已同步
            else:
                # legacy_unknown 或其他未知来源，保守处理为待同步
                initial_sync_status = 0
            
            args = (str(voc_id), s, _c('basic_meanings'), _c('ielts_focus'), _c('collocations'), _c('traps'), _c('synonyms'), _c('discrimination'), _c('example_sentences'), _c('memory_aid'), _c('word_ratings'), t, payload.get('prompt_tokens', 0), payload.get('completion_tokens', 0), payload.get('total_tokens', 0), metadata.get('batch_id') if metadata else None, original_meanings, m_ctx, content_origin, content_source_db, content_source_scope, initial_sync_status, get_timestamp_with_tz())
            batch_args.append(args)

        cur.executemany(sql, batch_args)

        if need_close:
            target_conn.commit()
            target_conn.close()

        _debug_log(f"批量保存 AI 笔记完成：{len(notes_data)} 个单词（本地数据库）")
        return True

    except Exception as e:
        _debug_log(f"批量保存 AI 笔记失败: {e}")
        return False

def save_ai_word_iteration(voc_id: str, payload: dict, db_path: str = None, metadata: dict = None, conn: Any = None) -> bool:
    """保存单次迭代结果到独立历史表。"""
    if not voc_id:
        return False

    try:
        data = payload or {}
        meta = metadata or {}
        batch_id = meta.get('batch_id')
        m_ctx = json.dumps(meta.get('maimemo_context', {}), ensure_ascii=False) if meta.get('maimemo_context') else None
        tags = data.get('tags')
        tags_json = json.dumps(tags, ensure_ascii=False) if tags is not None else None
        raw_response = data.get('raw_response') or data.get('raw_full_text') or json.dumps(data, ensure_ascii=False)

        args = (
            str(voc_id),
            data.get('spelling'),
            data.get('stage'),
            data.get('it_level'),
            data.get('score'),
            data.get('justification'),
            tags_json,
            data.get('refined_content'),
            data.get('candidate_notes'),
            raw_response,
            m_ctx,
            batch_id,
        )

        sql = '''
            INSERT INTO ai_word_iterations (
                voc_id, spelling, stage, it_level, score, justification, tags,
                refined_content, candidate_notes, raw_response, maimemo_context, batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''

        def _do_sql(cn):
            cur = cn.cursor()
            cur.execute(sql, args)
            if not conn:
                cn.commit()
                cn.close()

        if conn:
            _do_sql(conn)
        else:
            path = db_path or DB_PATH
            try:
                cloud_conn = _get_conn(path)
                if _is_cloud_connection(cloud_conn):
                    _do_sql(cloud_conn)
                    try:
                        _do_sql(_get_local_conn(path))
                    except Exception as local_sync_error:
                        _debug_log(f"save_ai_word_iteration 本地缓存同步失败: {local_sync_error}")
                else:
                    _do_sql(cloud_conn)
            except Exception as cloud_write_error:
                _debug_log(f"save_ai_word_iteration 云端写入失败，回退本地: {cloud_write_error}")
                _do_sql(_get_local_conn(path))

        return True
    except Exception as e:
        _debug_log(f"保存迭代历史失败: {e}")
        return False

def set_note_sync_status(voc_id: str, sync_status: int, db_path: str = None) -> bool:
    """
    更新指定单词笔记的同步状态。

    sync_status 约定：
    - 0: 云端未检出自己的释义
    - 1: 云端释义与数据库内容一致
    - 2: 云端已存在自己的释义，但内容与数据库不一致
    
    在双库模式（云端+本地缓存）下，确保两库同步。
    """
    def _status_text(value: int) -> str:
        mapping = {
            0: "待同步（未检出墨墨已创建释义）",
            1: "已同步（墨墨已创建释义与本地一致）",
            2: "冲突（墨墨已创建释义与本地不一致）",
        }
        return mapping.get(int(value), "未知状态")

    target_status = int(sync_status)
    target_status_text = _status_text(target_status)

    def _update_local_only(target_path: str) -> bool:
        try:
            local_conn = _get_local_conn(target_path)
            local_cur = local_conn.cursor()
            local_cur.execute(
                'UPDATE ai_word_notes SET sync_status = ?, updated_at = ? WHERE voc_id = ?',
                (target_status, get_timestamp_with_tz(), str(voc_id))
            )
            local_conn.commit()
            updated = local_cur.rowcount
            local_conn.close()
            if updated > 0:
                _debug_log(
                    f"本地回退写入成功: sync_status={target_status}（{target_status_text}）"
                )
                return True
            _debug_log(
                f"本地回退写入未命中记录: voc_id={voc_id}, 目标sync_status={target_status}（{target_status_text}）",
                level="WARNING",
            )
            return False
        except Exception as local_error:
            _debug_log(
                f"本地回退写入失败: voc_id={voc_id}, 目标sync_status={target_status}（{target_status_text}）, error={local_error}"
            )
            return False

    try:
        path = db_path or DB_PATH
        conn = _get_conn(path)
        cur = conn.cursor()

        cur.execute(
            'UPDATE ai_word_notes SET sync_status = ?, updated_at = ? WHERE voc_id = ?',
            (target_status, get_timestamp_with_tz(), str(voc_id))
        )

        conn.commit()
        updated = cur.rowcount
        
        # 如果是云端连接，同时更新本地缓存库，确保双库一致
        if _is_cloud_connection(conn):
            try:
                local_conn = _get_local_conn(path)
                local_cur = local_conn.cursor()
                local_cur.execute(
                    'UPDATE ai_word_notes SET sync_status = ?, updated_at = ? WHERE voc_id = ?',
                    (target_status, get_timestamp_with_tz(), str(voc_id))
                )
                local_conn.commit()
                local_conn.close()
                _debug_log(
                    f"本地缓存库写入成功: sync_status={target_status}（{target_status_text}）"
                )
            except Exception as local_sync_error:
                _debug_log(
                    f"本地缓存库写入失败: voc_id={voc_id}, 目标sync_status={target_status}（{target_status_text}）, error={local_sync_error}"
                )
        
        conn.close()

        if updated <= 0:
            _debug_log(
                f"主库写入未命中记录: voc_id={voc_id}, 目标sync_status={target_status}（{target_status_text}）",
                level="WARNING",
            )
            return False

        _debug_log(
            f"主库写入成功: sync_status={target_status}（{target_status_text}）"
        )
        return True

    except Exception as e:
        _debug_log(
            f"主库写入失败，准备回退本地: voc_id={voc_id}, 目标sync_status={target_status}（{target_status_text}）, error={e}"
        )
        # resumption 依赖本地队列状态；云端异常时回退更新本地，避免重复续传。
        return _update_local_only(db_path or DB_PATH)


def mark_note_synced(voc_id: str, db_path: str = None) -> bool:
    """标记指定单词笔记为已同步（sync_status = 1）"""
    return set_note_sync_status(voc_id, 1, db_path=db_path)


def mark_note_sync_conflict(voc_id: str, db_path: str = None) -> bool:
    """标记指定单词笔记为冲突状态（sync_status = 2）"""
    return set_note_sync_status(voc_id, 2, db_path=db_path)

def get_unsynced_notes(db_path: str = None) -> list:
    """
    获取所有未同步的笔记（sync_status = 0 AND content_origin = 'ai_generated'）
    
    仅返回当前用户需要同步的笔记。对于 co_origin 笔记（社区/历史/多库查询命中），
    已在初始保存时标记为 sync_status=1，不再进入此队列。
    
    Args:
        db_path: 数据库路径（可选）
    
    Returns:
        包含 voc_id, spelling, basic_meanings, ielts_focus 等字段的字典列表
    """
    try:
        path = db_path or DB_PATH
        # 断点续传只需要读取本地队列状态，避免在云端模式下误走远程连接。
        conn = _get_local_conn(path)
        cur = conn.cursor()
        
        cur.execute(
            '''SELECT voc_id, spelling, basic_meanings, ielts_focus, collocations, 
                      traps, synonyms, discrimination, example_sentences, memory_aid, 
                      word_ratings, raw_full_text, batch_id, original_meanings, 
                      maimemo_context, it_level, updated_at, content_origin
               FROM ai_word_notes 
               WHERE sync_status = 0 AND content_origin = 'ai_generated'
               ORDER BY updated_at ASC'''
        )
        
        rows = cur.fetchall()
        conn.close()
        
        # 将行转换为字典列表
        result = [_row_to_dict(cur, row) for row in rows]
        
        _debug_log(f"获取未同步笔记完成: {len(result)} 条 (仅 ai_generated)")
        return result
        
    except Exception as e:
        _debug_log(f"获取未同步笔记失败: {e}")
        return []

def get_word_note(voc_id: str, db_path: str = None) -> Optional[dict]:
    c = _get_conn(db_path or DB_PATH); cur = c.cursor(); cur.execute('SELECT * FROM ai_word_notes WHERE voc_id = ?', (str(voc_id),)); r = cur.fetchone(); c.close(); return _row_to_dict(cur, r) if r else None


def get_local_word_note(voc_id: str, db_path: str = None) -> Optional[dict]:
    """仅从本地数据库读取单词笔记，避免热路径触发云端连接。"""
    c = _get_local_conn(db_path or DB_PATH)
    cur = c.cursor()
    cur.execute('SELECT * FROM ai_word_notes WHERE voc_id = ?', (str(voc_id),))
    r = cur.fetchone()
    c.close()
    return _row_to_dict(cur, r) if r else None

def _matches_ai_generation_context(note_row: Dict[str, Any], ai_provider: Optional[str] = None, prompt_version: Optional[str] = None) -> bool:
    """判断笔记是否与当前 AI 生成上下文一致。"""
    current_provider = (ai_provider or "").strip().lower()
    current_prompt_version = (prompt_version or "").strip()

    batch_provider = str(
        note_row.get("batch_ai_provider")
        or note_row.get("ai_provider")
        or ""
    ).strip().lower()
    batch_prompt_version = str(
        note_row.get("batch_prompt_version")
        or note_row.get("prompt_version")
        or ""
    ).strip()

    if not current_provider or not current_prompt_version:
        return False

    if current_provider and batch_provider != current_provider:
        return False

    if current_prompt_version and batch_prompt_version != current_prompt_version:
        return False

    return bool(batch_provider and batch_prompt_version)


def find_word_in_community(voc_id: str, ai_provider: str = None, prompt_version: str = None) -> Optional[Tuple[dict, str]]:
    """在社区数据库中查找单词笔记（优先云端，回退本地历史，最后查当前数据库）。"""
    # 1. 优先查询云端数据库
    if TURSO_DB_URL and TURSO_AUTH_TOKEN and HAS_LIBSQL:
        try:
            cloud_conn = _get_cloud_conn(TURSO_DB_URL, TURSO_AUTH_TOKEN)
            cloud_cur = cloud_conn.cursor()
            cloud_cur.execute(
                '''
                SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                FROM ai_word_notes n
                LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                WHERE n.voc_id = ?
                ''',
                (str(voc_id),)
            )
            r = cloud_cur.fetchone()
            cloud_conn.close()
            if r:
                note_dict = _row_to_dict(cloud_cur, r)
                if _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                    return note_dict, "云端数据库"
        except Exception as e:
            _debug_log(f"云端社区查询失败: {e}")

    # 2. 回退查询本地历史数据库文件
    cdb = os.path.basename(DB_PATH)
    dr = os.path.dirname(DB_PATH)
    dfs = sorted([f for f in os.listdir(dr) if (f.startswith('history_') or f.startswith('history-')) and f.endswith('.db')],
                 key=lambda x: os.path.getmtime(os.path.join(dr, x)), reverse=True)

    for df in dfs:
        if df == cdb: continue
        try:
            c = _get_local_conn(os.path.join(dr, df))
            cur = c.cursor()
            cur.execute(
                '''
                SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                FROM ai_word_notes n
                LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                WHERE n.voc_id = ?
                ''',
                (str(voc_id),)
            )
            r = cur.fetchone()
            c.close()
            if r:
                note_dict = _row_to_dict(cur, r)
                if _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                    return note_dict, df
        except: continue

    # 3. 最后查询当前数据库
    try:
        c = _get_local_conn(DB_PATH)
        cur = c.cursor()
        cur.execute(
            '''
            SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
            FROM ai_word_notes n
            LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
            WHERE n.voc_id = ?
            ''',
            (str(voc_id),)
        )
        r = cur.fetchone()
        c.close()
        if r:
            note_dict = _row_to_dict(cur, r)
            if _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                return note_dict, "当前数据库"
    except: pass

    return None


def find_words_in_community_batch(
    voc_ids: List[str],
    skip_cloud: bool = False,
    ai_provider: str = None,
    prompt_version: str = None,
) -> Dict[str, Tuple[dict, str]]:
    """批量在社区数据库中查找单词笔记（优先本地历史/当前库，云端只补查剩余项）

    Args:
        voc_ids: 单词 ID 列表
        skip_cloud: 是否跳过云端查询（如果用户已合并数据，可设为 True）

    Returns:
        字典：voc_id -> (笔记数据, 来源)
    """
    if not voc_ids:
        return {}

    result = {}

    remaining_ids = [str(vid) for vid in voc_ids]

    # 1. 先查询本地历史数据库文件（只查未找到的单词）
    if remaining_ids:
        cdb = os.path.basename(DB_PATH)
        dr = os.path.dirname(DB_PATH)
        dfs = sorted([f for f in os.listdir(dr) if (f.startswith('history_') or f.startswith('history-')) and f.endswith('.db')],
                     key=lambda x: os.path.getmtime(os.path.join(dr, x)), reverse=True)

        for df in dfs:
            if df == cdb:
                continue
            try:
                c = _get_local_conn(os.path.join(dr, df))
                cur = c.cursor()
                placeholders = ','.join(['?'] * len(remaining_ids))
                cur.execute(
                    f'''
                    SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                    FROM ai_word_notes n
                    LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                    WHERE n.voc_id IN ({placeholders})
                    ''',
                    remaining_ids,
                )
                rows = cur.fetchall()
                c.close()

                if rows:
                    for row in rows:
                        note_dict = _row_to_dict(cur, row)
                        voc_id = note_dict.get('voc_id')
                        if voc_id and voc_id not in result and _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                            result[voc_id] = (note_dict, df)
                            if voc_id in remaining_ids:
                                remaining_ids.remove(voc_id)

                if not remaining_ids:
                    break
            except:
                continue

    # 2. 再查询当前数据库（只查未找到的单词）
    if remaining_ids:
        try:
            c = _get_local_conn(DB_PATH)
            cur = c.cursor()
            placeholders = ','.join(['?'] * len(remaining_ids))
            cur.execute(
                f'''
                SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                FROM ai_word_notes n
                LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                WHERE n.voc_id IN ({placeholders})
                ''',
                remaining_ids,
            )
            rows = cur.fetchall()
            c.close()

            if rows:
                for row in rows:
                    note_dict = _row_to_dict(cur, row)
                    voc_id = note_dict.get('voc_id')
                    if voc_id and voc_id not in result and _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                        result[voc_id] = (note_dict, "当前数据库")
                        if voc_id in remaining_ids:
                            remaining_ids.remove(voc_id)
        except:
            pass

    # 3. 云端只补查本地未命中的剩余单词
    if not skip_cloud and HAS_LIBSQL and remaining_ids:
        cloud_targets = _collect_cloud_lookup_targets()

        for cloud_url, cloud_token, source_label in cloud_targets:
            if not remaining_ids:
                break
            cloud_conn = None
            try:
                cloud_conn = _get_cloud_conn(cloud_url, cloud_token)
                cloud_cur = cloud_conn.cursor()

                placeholders = ','.join(['?'] * len(remaining_ids))
                cloud_cur.execute(
                    f'''
                    SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                    FROM ai_word_notes n
                    LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                    WHERE n.voc_id IN ({placeholders})
                    ''',
                    remaining_ids,
                )
                rows = cloud_cur.fetchall()

                if rows:
                    columns = [col[0] for col in cloud_cur.description]
                    found_count = 0
                    for row in rows:
                        note_dict = dict(zip(columns, row))
                        voc_id = note_dict.get('voc_id')
                        if voc_id and voc_id not in result and _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                            result[voc_id] = (note_dict, source_label)
                            found_count += 1

                    if found_count:
                        remaining_ids = [vid for vid in remaining_ids if vid not in result]

                _debug_log(f"{source_label} 批量查询完成：累计找到 {len(result)} 个单词的笔记")
            except Exception as e:
                _debug_log(f"{source_label} 批量查询失败: {e}")
            finally:
                if cloud_conn:
                    try:
                        cloud_conn.close()
                    except Exception:
                        pass

    return result

def save_ai_batch(batch_data: dict, db_path: str = None):
    c = _get_conn(db_path or DB_PATH)
    cur = c.cursor()
    cur.execute(
        'INSERT OR REPLACE INTO ai_batches (batch_id, request_id, ai_provider, model_name, prompt_version, batch_size, total_latency_ms, prompt_tokens, completion_tokens, total_tokens, finish_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            batch_data.get('batch_id'),
            batch_data.get('request_id'),
            batch_data.get('ai_provider'),
            batch_data.get('model_name'),
            batch_data.get('prompt_version'),
            batch_data.get('batch_size', 1),
            batch_data.get('total_latency_ms', 0),
            batch_data.get('prompt_tokens', 0),
            batch_data.get('completion_tokens', 0),
            batch_data.get('total_tokens', 0),
            batch_data.get('finish_reason'),
            get_timestamp_with_tz(),
        ),
    )
    c.commit()
    c.close()

def get_file_hash(file_path):
    if not os.path.exists(file_path): return '00000000'
    with open(file_path, 'rb') as f: return hashlib.md5(f.read()).hexdigest()[:8]

def archive_prompt_file(source_path, prompt_hash, prompt_type='main'):
    ad = os.path.join(DATA_DIR, 'prompts'); os.makedirs(ad, exist_ok=True); tp = os.path.join(ad, f'prompt_{prompt_type}_{prompt_hash}.md')
    if not os.path.exists(tp): shutil.copy2(source_path, tp)

def get_latest_progress(voc_id, db_path=None):
    c = _get_conn(db_path or DB_PATH); cur = c.cursor(); cur.execute('SELECT familiarity_short, review_count FROM word_progress_history WHERE voc_id = ? ORDER BY created_at DESC LIMIT 1', (str(voc_id),)); r = cur.fetchone(); c.close(); return _row_to_dict(cur, r) if r else None

def set_config(k,v,db=None): c = _get_conn(db or DB_PATH); cur = c.cursor(); cur.execute('INSERT OR REPLACE INTO system_config (key, value, updated_at) VALUES (?, ?, ?)', (k, v, get_timestamp_with_tz())); c.commit(); c.close()
def get_config(k,db=None): c = _get_conn(db or DB_PATH); cur = c.cursor(); cur.execute('SELECT value FROM system_config WHERE key = ?', (k,)); r = cur.fetchone(); c.close(); return r[0] if r else None
def log_progress_snapshots_bulk(w): return log_progress_snapshots(w)
def save_test_word_note(v, p): save_ai_word_note(v, p, db_path=TEST_DB_PATH)
def log_test_run(t, s, w, a, sp, d=True, e="", res=None):
    c = _get_conn(TEST_DB_PATH); cur = c.cursor(); aj = json.dumps(res, ensure_ascii=False) if res else ""; cur.execute('INSERT INTO test_run_logs (total_count, sample_count, sample_words, ai_calls, success_parsed, is_dry_run, error_msg, ai_results_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (t, s, ",".join(w), a, sp, d, e, aj)); c.commit(); rid = cur.lastrowid; c.close(); return rid


def _emit_sync_progress(progress_callback, stage: str, current: int, total: int, message: str, **extra):
    """统一同步进度事件出口，避免回调异常影响主流程。"""
    if not progress_callback:
        return
    payload = {
        "stage": stage,
        "current": current,
        "total": total,
        "message": message,
    }
    if extra:
        payload.update(extra)
    try:
        progress_callback(payload)
    except Exception:
        pass

@log_performance(lambda: ContextLogger(logging.getLogger(__name__)))
def sync_databases(
    db_path: str = None,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, int]:
    """
    双向同步云端和本地数据库，确保数据一致性。
    支持 dry_run 模式，仅返回需要上传和下载的记录数。
    返回格式: {'upload': X, 'download': Y, 'status': 'ok|skipped|error', 'reason': str}
    """
    path = db_path or DB_PATH
    stats = {'upload': 0, 'download': 0, 'status': 'ok', 'reason': ''}
    if not TURSO_DB_URL or not TURSO_AUTH_TOKEN or not HAS_LIBSQL:
        stats['status'] = 'skipped'
        if not TURSO_DB_URL or not TURSO_AUTH_TOKEN:
            stats['reason'] = 'missing-cloud-credentials'
        else:
            stats['reason'] = 'libsql-unavailable'
        _debug_log(f"云端未配置或不可用，跳过同步: {stats['reason']}")
        _emit_sync_progress(progress_callback, 'skipped', 0, 0, f"跳过同步: {stats['reason']}", status='skipped', reason=stats['reason'])
        return stats
    
    sync_start = time.time()
    if not dry_run: _debug_log("开始数据库同步...")
    cloud_conn = None
    local_conn = None
    
    try:
        sync_targets = [
            ('ai_word_notes', 'voc_id', _sync_table),
            ('processed_words', 'voc_id', _sync_table),
            ('word_progress_history', None, _sync_progress_history),
            ('ai_batches', 'batch_id', _sync_table),
            ('system_config', 'key', _sync_table),
        ]
        total_steps = len(sync_targets) + 2
        step = 1
        _emit_sync_progress(progress_callback, 'connect', step, total_steps, '连接本地和云端数据库')

        # 获取连接
        cloud_conn = _get_cloud_conn(TURSO_DB_URL, TURSO_AUTH_TOKEN)
        local_conn = _get_local_conn(path)
        
        # 注意：libsql 不支持 sqlite3.Row row_factory，选择器内部会用 cursor.description 手动转 dict
        local_conn.row_factory = sqlite3.Row  # 本地 sqlite3 支持
        
        cloud_cur = cloud_conn.cursor()
        local_cur = local_conn.cursor()

        step += 1
        for table_name, primary_key, sync_fn in sync_targets:
            table_started_at = time.time()
            _emit_sync_progress(progress_callback, 'table', step, total_steps, f"同步表 {table_name}", table=table_name)
            if primary_key:
                u, d = sync_fn(cloud_conn, local_conn, table_name, primary_key, dry_run)
            else:
                u, d = sync_fn(cloud_conn, local_conn, dry_run)
            stats['upload'] += u
            stats['download'] += d
            table_elapsed_ms = int((time.time() - table_started_at) * 1000)
            _emit_sync_progress(
                progress_callback,
                'table-done',
                step,
                total_steps,
                f"{table_name}: 上传 {u}, 下载 {d}",
                table=table_name,
                upload=u,
                download=d,
                duration_ms=table_elapsed_ms,
            )
            step += 1
        
        if not dry_run:
            cloud_conn.commit()
            local_conn.commit()
        _emit_sync_progress(progress_callback, 'finalize', total_steps, total_steps, '提交并关闭连接', upload=stats['upload'], download=stats['download'])
        
        total_time = int((time.time() - sync_start) * 1000)
        stats['duration_ms'] = total_time
        if not dry_run: _debug_log(f"数据库同步完成 | 总耗时: {total_time}ms")
        return stats
        
    except Exception as e:
        _debug_log(f"数据库同步失败: {e}")
        stats['status'] = 'error'
        stats['reason'] = str(e)
        _emit_sync_progress(progress_callback, 'error', 0, 0, f"同步失败: {e}", status='error', reason=str(e))
        return stats
    finally:
        if cloud_conn:
            try:
                cloud_conn.close()
            except Exception:
                pass
        if local_conn:
            try:
                local_conn.close()
            except Exception:
                pass

def _row_to_dict(cursor, row) -> dict:
    """将任意 row 对象（sqlite3.Row 或 libsql tuple）安全转换为 dict。"""
    if isinstance(row, dict):
        return row
    if hasattr(row, 'asdict'):
        try:
            return row.asdict()
        except Exception:
            pass

    try:
        # sqlite3.Row: keys() 方法
        return dict(zip(row.keys(), tuple(row)))
    except AttributeError:
        if hasattr(row, 'astuple') and hasattr(cursor, 'description') and cursor.description:
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row.astuple()))
        # libsql 返回 tuple，用 cursor.description 获取列名
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))

def _sync_table(cloud_conn, local_conn, table_name: str, primary_key: str, dry_run: bool = False):
    """优化后的轻量化同步：元数据优先 + 按需拉取"""
    cloud_cur = cloud_conn.cursor()
    local_cur = local_conn.cursor()
    
    # 自动识别时间戳列
    ts_col = 'updated_at'
    if table_name == 'ai_batches': ts_col = 'created_at'
    if table_name == 'admin_logs': ts_col = 'timestamp'

    # 1. 快速路径检测 (Fast Path)
    try:
        cloud_cur.execute(f'SELECT COUNT(*), MAX({ts_col}) FROM {table_name}')
        c_count, c_max_ts = cloud_cur.fetchone()
        local_cur.execute(f'SELECT COUNT(*), MAX({ts_col}) FROM {table_name}')
        l_count, l_max_ts = local_cur.fetchone()
        
        if c_count == l_count and str(c_max_ts) == str(l_max_ts):
            if not dry_run: _debug_log(f"  {table_name}: 数据一致，跳过对比")
            return 0, 0
    except Exception as e:
        _debug_log(f"  {table_name}: 快速路径检测异常，执行全量对比: {e}")

    # 2. 元数据拉取 (只拉取 ID 和 时间戳)
    cloud_cur.execute(f'SELECT {primary_key}, {ts_col} FROM {table_name}')
    cloud_meta = {r[0]: r[1] for r in cloud_cur.fetchall()}
    
    local_cur.execute(f'SELECT {primary_key}, {ts_col} FROM {table_name}')
    local_meta = {r[0]: r[1] for r in local_cur.fetchall()}

    def _clean_ts(ts):
        if not ts: return ""
        return str(ts).split('.')[0].replace('T', ' ')

    keys_to_upload = []
    keys_to_download = []

    for k, l_ts in local_meta.items():
        c_ts = cloud_meta.get(k)
        if not c_ts or _clean_ts(l_ts) > _clean_ts(c_ts):
            keys_to_upload.append(k)
            
    for k, c_ts in cloud_meta.items():
        l_ts = local_meta.get(k)
        if not l_ts or _clean_ts(c_ts) > _clean_ts(l_ts):
            keys_to_download.append(k)

    if not dry_run: _debug_log(f"  {table_name}: 需上传 {len(keys_to_upload)}, 需下载 {len(keys_to_download)}")
    if dry_run: return len(keys_to_upload), len(keys_to_download)

    # 3. 按需批量拉取并写入
    def _fetch_and_apply(src_conn, src_cur, dest_conn, dest_cur, keys, action_name):
        if not keys: return 0
        total_count = 0
        CHUNK_SIZE = 50

        # 获取目标表的列定义
        dest_cur.execute(f"PRAGMA table_info({table_name})")
        dest_cols = {row[1] for row in dest_cur.fetchall()}

        for i in range(0, len(keys), CHUNK_SIZE):
            chunk_keys = keys[i:i + CHUNK_SIZE]
            placeholders = ', '.join(['?'] * len(chunk_keys))
            src_cur.execute(f'SELECT * FROM {table_name} WHERE {primary_key} IN ({placeholders})', chunk_keys)
            rows = src_cur.fetchall()

            if not rows: continue

            data = [_row_to_dict(src_cur, row) for row in rows]

            # 只选择目标表中存在的列
            valid_cols = [col for col in data[0].keys() if col in dest_cols]
            if not valid_cols:
                continue

            cols = ', '.join(valid_cols)
            vals = ', '.join(['?'] * len(valid_cols))
            sql = f'INSERT OR REPLACE INTO {table_name} ({cols}) VALUES ({vals})'

            # 只选择有效列的值
            valid_data = [tuple(r[col] for col in valid_cols) for r in data]
            dest_cur.executemany(sql, valid_data)
            dest_conn.commit()
            total_count += len(data)
            if len(keys) > CHUNK_SIZE:
                _debug_log(f"  {table_name} {action_name} 进度: {total_count}/{len(keys)}")

        return total_count

    up = _fetch_and_apply(local_conn, local_cur, cloud_conn, cloud_cur, keys_to_upload, "上传")
    down = _fetch_and_apply(cloud_conn, cloud_cur, local_conn, local_cur, keys_to_download, "下载")
    
    return up, down


def _sync_progress_history(cloud_conn, local_conn, dry_run=False):
    """重构后的大表同步逻辑：基于最后更新时间戳的增量同步"""
    cloud_cur = cloud_conn.cursor()
    local_cur = local_conn.cursor()
    
    # 1. 快速路径：对齐计数和最大时间戳
    try:
        cloud_cur.execute('SELECT COUNT(*), MAX(created_at) FROM word_progress_history')
        c_count, c_max_ts = cloud_cur.fetchone()
        local_cur.execute('SELECT COUNT(*), MAX(created_at) FROM word_progress_history')
        l_count, l_max_ts = local_cur.fetchone()
        
        if c_count == l_count and str(c_max_ts) == str(l_max_ts) and c_max_ts is not None:
            return 0, 0
    except: pass

    # 2. 增量同步逻辑
    to_upload = []
    to_download = []
    
    # 本地 -> 云端 (上传最新)
    if l_max_ts and (not c_max_ts or str(l_max_ts) > str(c_max_ts)):
        limit_ts = str(c_max_ts) if c_max_ts else '0000-00-00'
        local_cur.execute('SELECT * FROM word_progress_history WHERE created_at > ?', (limit_ts,))
        for r in local_cur.fetchall():
            d = _row_to_dict(local_cur, r)
            to_upload.append({k: v for k, v in d.items() if k != 'id'})
            
    # 云端 -> 本地 (下载最新)
    if c_max_ts and (not l_max_ts or str(c_max_ts) > str(l_max_ts)):
        limit_ts = str(l_max_ts) if l_max_ts else '0000-00-00'
        cloud_cur.execute('SELECT * FROM word_progress_history WHERE created_at > ?', (limit_ts,))
        for r in cloud_cur.fetchall():
            d = _row_to_dict(cloud_cur, r)
            to_download.append({k: v for k, v in d.items() if k != 'id'})

    if dry_run: return len(to_upload), len(to_download)

    def _apply_history(conn, cur, data, name):
        if not data: return 0

        # 获取目标表的列定义
        cur.execute("PRAGMA table_info(word_progress_history)")
        dest_cols = {row[1] for row in cur.fetchall()}

        # 只选择目标表中存在的列
        valid_cols = [col for col in data[0].keys() if col in dest_cols]
        if not valid_cols:
            return 0

        cols = ', '.join(valid_cols)
        vals = ', '.join(['?'] * len(valid_cols))
        params = [tuple(r[col] for col in valid_cols) for r in data]

        try:
            # INSERT OR IGNORE 配合唯一约束
            cur.executemany(f'INSERT OR IGNORE INTO word_progress_history ({cols}) VALUES ({vals})', params)
            conn.commit()
            _debug_log(f"  word_progress_history {name} 完成: {len(data)} 条")
        except Exception as e:
            _debug_log(f"  word_progress_history {name} 失败: {e}")
        return len(data)

    u = _apply_history(cloud_conn, cloud_cur, to_upload, "上传")
    d = _apply_history(local_conn, local_cur, to_download, "下载")
    return (u, d)


# ============================================================================
# 中央用户数据库（Users Hub）相关函数
# ============================================================================

def is_hub_configured() -> bool:
    """检查中央 Hub 数据库是否配置了云端凭据"""
    return bool(TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN)

def _get_hub_conn(max_retries: int = 3, retry_delay: float = 1.0) -> Any:
    """获取中央用户 Hub 数据库连接（优先云端 Turso，无配置则回退本地 SQLite）

    Args:
        max_retries: 最大重试次数（默认 3 次）
        retry_delay: 每次重试的延迟秒数（默认 1.0 秒）
    """
    # 强制云端模式检查
    from config import get_force_cloud_mode
    if get_force_cloud_mode() and not is_hub_configured():
        raise RuntimeError("强制云端模式已启用，但未配置 TURSO_HUB_DB_URL 或 TURSO_HUB_AUTH_TOKEN。请在 .env 文件中配置，或将 FORCE_CLOUD_MODE 设置为 False 以允许本地运行。")

    # 优先尝试云端（带重试机制）
    if TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN and HAS_LIBSQL:
        last_error = None
        for attempt in range(max_retries):
            try:
                _debug_log(f"尝试连接云端 Hub (第 {attempt + 1}/{max_retries} 次)")
                return _get_cloud_conn(TURSO_HUB_DB_URL, TURSO_HUB_AUTH_TOKEN)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:  # 不是最后一次尝试
                    _debug_log(f"云端连接失败 (尝试 {attempt + 1})，{retry_delay} 秒后重试: {e}")
                    time.sleep(retry_delay)
                else:
                    _debug_log(f"云端连接失败 (已尝试 {max_retries} 次)，回退本地: {e}")

        if get_force_cloud_mode():
            # 强制模式下，连接失败直接抛出异常
            raise RuntimeError(f"强制云端模式连接 Hub 失败 (已尝试 {max_retries} 次): {last_error}")

    # 非强制模式下，无配置或失败时回退到本地
    if not get_force_cloud_mode():
        _debug_log("回退到本地 Hub 数据库")
        os.makedirs(os.path.dirname(os.path.abspath(HUB_DB_PATH)), exist_ok=True)
        conn = sqlite3.connect(HUB_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    # 强制模式下如果到这里说明配置有问题
    raise RuntimeError("强制云端模式已启用，但无法连接到云端 Hub 数据库")

def init_users_hub_tables() -> bool:
    """初始化中央用户 Hub 数据库的6个表"""
    try:
        hub_fp = _hub_db_fingerprint()
        # 命中近期成功的初始化状态时，直接短路，避免每次启动都重复做 Hub 握手和 schema 校验
        if _hub_init_state_is_fresh(hub_fp):
            _debug_log("Hub 数据库已在有效缓存窗口内初始化，跳过重复 schema 校验")
            return True

        # 即使存在旧式初始化标记，也继续执行 CREATE IF NOT EXISTS，确保新增表/列能自动补齐
        if _is_db_initialized("hub", hub_fp):
            _debug_log("Hub 数据库已初始化（通过旧标记文件），执行轻量 schema 校验")

        hub_start = time.time()
        hub_conn = _get_hub_conn()
        _debug_log("Hub 数据库连接完成", hub_start)

        cur = hub_conn.cursor()

        # 检查表是否已存在（避免重复执行耗时的 CREATE TABLE 操作）
        check_start = time.time()
        table_exists = _check_table_exists(cur, "users", "hub", cache_scope=hub_fp)
        _debug_log(f"Hub 表存在检查完成 (存在: {table_exists})", check_start)

        if table_exists:
            _debug_log("中央 Hub users 表已存在，将执行增量 schema 校验")

        # 1. users 表：基本用户信息及角色/状态
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                first_login_at TEXT,
                last_login_at TEXT,
                status TEXT DEFAULT 'active',
                role TEXT DEFAULT 'user',
                notes TEXT,
                updated_at TEXT
            )
        ''')
        
        try:
            cur.execute("ALTER TABLE users ADD COLUMN updated_at TEXT")
        except: pass
        
        # 2. user_api_keys 表：用户 API 密钥（加密存储）
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                api_key_encrypted TEXT NOT NULL,
                api_key_name TEXT,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                revoked_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        
        # 3. user_sync_history 表：用户数据同步历史
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_sync_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                sync_type TEXT NOT NULL,
                source TEXT,
                target TEXT,
                record_count INTEGER,
                sync_status TEXT,
                error_msg TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        
        # 4. user_stats 表：用户统计信息（缓存）
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id TEXT PRIMARY KEY,
                total_words_processed INTEGER DEFAULT 0,
                total_ai_calls INTEGER DEFAULT 0,
                total_prompt_tokens INTEGER DEFAULT 0,
                total_completion_tokens INTEGER DEFAULT 0,
                total_sync_count INTEGER DEFAULT 0,
                last_activity_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        
        # 5. user_sessions 表：用户会话跟踪
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_id TEXT UNIQUE NOT NULL,
                client_info TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                login_at TEXT NOT NULL,
                logout_at TEXT,
                last_activity_at TEXT,
                session_status TEXT DEFAULT 'active',
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        
        # 6. admin_logs 表：管理员操作日志
        cur.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                action_detail TEXT,
                admin_username TEXT,
                target_user_id TEXT,
                timestamp TEXT NOT NULL,
                result TEXT DEFAULT 'success'
            )
        ''')

        # 7. user_credentials 表：用户敏感配置（加密存储）
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_credentials (
                user_id TEXT PRIMARY KEY,
                turso_db_url_enc TEXT,
                turso_auth_token_enc TEXT,
                momo_token_enc TEXT,
                mimo_api_key_enc TEXT,
                gemini_api_key_enc TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')

        hub_conn.commit()
        hub_conn.close()
        _debug_log("中央 Hub 数据库表初始化完成")
        # 标记数据库已初始化
        _mark_db_initialized("hub", hub_fp)
        _save_hub_init_state({
            "hub_fp": hub_fp,
            "schema_version": _HUB_SCHEMA_VERSION,
            "last_success_at": time.time(),
            "last_checked_at": time.time(),
            "mode": "cloud" if TURSO_HUB_DB_URL else "local",
        })
        return True
        
    except Exception as e:
        _debug_log(f"初始化中央 Hub 表失败: {e}")
        return False

def save_user_info_to_hub(user_id: str, username: str, email: str, user_notes: str = "", role: str = "user", conn: Any = None) -> bool:
    """
    保存用户信息到中央 Hub 数据库

    Args:
        user_id: 唯一用户 ID (通常为 UUID)
        username: 用户名
        email: 邮箱
        user_notes: 可选的用户备注
        role: 用户角色（默认 user，Asher 自动成为 admin）
        conn: 可选的数据库连接（用于复用连接）
    """
    need_close = False
    try:
        if conn:
            hub_conn = conn
        else:
            hub_conn = _get_hub_conn()
            need_close = True

        cur = hub_conn.cursor()

        timestamp = get_timestamp_with_tz()
        normalized_username = username.strip().lower()
        if normalized_username.lower() == 'asher':
            role = 'admin'

        existing = None
        if user_id:
            cur.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            existing = cur.fetchone()
        if not existing:
            cur.execute('SELECT * FROM users WHERE lower(username) = ?', (normalized_username,))
            existing = cur.fetchone()

        existing_data = _row_to_dict(cur, existing) if existing else {}
        inserted_user_id = existing_data.get('user_id', user_id)
        created_at = existing_data.get('created_at', timestamp)
        first_login_at = existing_data.get('first_login_at')
        last_login_at = existing_data.get('last_login_at')
        existing_role = existing_data.get('role')
        if existing_role and existing_role.lower() == 'admin':
            role = 'admin'
        status = existing_data.get('status', 'active')

        cur.execute('''
            INSERT OR REPLACE INTO users (user_id, username, email, created_at, first_login_at, last_login_at, status, role, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            inserted_user_id,
            normalized_username,
            email,
            created_at,
            first_login_at,
            last_login_at,
            status,
            role,
            user_notes,
            timestamp
        ))

        if need_close:
            hub_conn.commit()
            hub_conn.close()

        _debug_log(f"用户信息已保存到 Hub: {normalized_username} ({inserted_user_id})")
        return True

    except Exception as e:
        _debug_log(f"保存用户信息到 Hub 失败: {e}")
        return False

def save_user_credentials_to_hub(user_id: str, credentials: Dict[str, str], conn: Any = None) -> bool:
    """保存用户敏感凭据到 Hub（字段加密后落库）。"""
    if not user_id:
        return False
    if not credentials:
        return True

    key_bytes = _get_secret_key_bytes()
    if not key_bytes:
        _debug_log("跳过保存 Hub 凭据：ENCRYPTION_KEY 未配置", level="WARNING")
        return False

    field_map = {
        "turso_db_url": "turso_db_url_enc",
        "turso_auth_token": "turso_auth_token_enc",
        "momo_token": "momo_token_enc",
        "mimo_api_key": "mimo_api_key_enc",
        "gemini_api_key": "gemini_api_key_enc",
    }

    need_close = False
    try:
        if conn:
            hub_conn = conn
        else:
            hub_conn = _get_hub_conn()
            need_close = True

        cur = hub_conn.cursor()
        cur.execute('SELECT * FROM user_credentials WHERE user_id = ?', (user_id,))
        existing = cur.fetchone()
        existing_data = _row_to_dict(cur, existing) if existing else {}

        now = get_timestamp_with_tz()
        created_at = existing_data.get('created_at', now)

        row_values = {
            "user_id": user_id,
            "created_at": created_at,
            "updated_at": now,
        }

        for src_key, db_col in field_map.items():
            candidate = credentials.get(src_key)
            if candidate:
                row_values[db_col] = _encrypt_secret_value(str(candidate))
            else:
                row_values[db_col] = existing_data.get(db_col)

        cur.execute('''
            INSERT OR REPLACE INTO user_credentials (
                user_id, turso_db_url_enc, turso_auth_token_enc, momo_token_enc,
                mimo_api_key_enc, gemini_api_key_enc, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            row_values["user_id"],
            row_values.get("turso_db_url_enc"),
            row_values.get("turso_auth_token_enc"),
            row_values.get("momo_token_enc"),
            row_values.get("mimo_api_key_enc"),
            row_values.get("gemini_api_key_enc"),
            row_values["created_at"],
            row_values["updated_at"],
        ))

        if need_close:
            hub_conn.commit()
            hub_conn.close()

        _debug_log(f"用户凭据已更新到 Hub: {user_id}")
        return True
    except Exception as e:
        _debug_log(f"保存用户凭据到 Hub 失败: {e}")
        return False

def get_user_credentials_from_hub(user_id: str, decrypt_values: bool = False) -> Optional[dict]:
    """读取 Hub 中的用户凭据；可选解密返回明文。"""
    if not user_id:
        return None
    try:
        hub_conn = _get_hub_conn()
        cur = hub_conn.cursor()
        cur.execute('SELECT * FROM user_credentials WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        hub_conn.close()
        if not row:
            return None

        data = _row_to_dict(cur, row)
        if not decrypt_values:
            return data

        out = {
            "user_id": data.get("user_id"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }
        decrypt_map = {
            "turso_db_url": data.get("turso_db_url_enc"),
            "turso_auth_token": data.get("turso_auth_token_enc"),
            "momo_token": data.get("momo_token_enc"),
            "mimo_api_key": data.get("mimo_api_key_enc"),
            "gemini_api_key": data.get("gemini_api_key_enc"),
        }
        for k, v in decrypt_map.items():
            out[k] = _decrypt_secret_value(v) if v else ""
        return out
    except Exception as e:
        _debug_log(f"读取用户凭据失败: {e}")
        return None

def get_user_by_username(username: str) -> Optional[dict]:
    """从 Hub 按 username 查询用户记录。"""
    try:
        hub_conn = _get_hub_conn()
        cur = hub_conn.cursor()
        cur.execute('SELECT * FROM users WHERE lower(username) = ?', (username.strip().lower(),))
        row = cur.fetchone()
        hub_conn.close()
        return _row_to_dict(cur, row) if row else None
    except Exception as e:
        _debug_log(f"从 Hub 按用户名查询失败: {e}")
        return None

def is_admin_username(username: str) -> bool:
    """判断指定用户名是否具有管理员角色。"""
    if not username:
        return False
    normalized = username.strip().lower()
    if normalized == 'asher':
        return True
    user = get_user_by_username(username)
    return bool(user and user.get('role', '').lower() == 'admin')

def list_hub_users(limit: int = 50) -> List[dict]:
    """列出 Hub 中的用户信息。"""
    try:
        hub_conn = _get_hub_conn()
        cur = hub_conn.cursor()
        cur.execute('SELECT user_id, username, email, role, status, created_at, last_login_at FROM users ORDER BY created_at ASC LIMIT ?', (limit,))
        rows = cur.fetchall()
        hub_conn.close()
        return [_row_to_dict(cur, row) for row in rows]
    except Exception as e:
        _debug_log(f"获取 Hub 用户列表失败: {e}")
        return []

def set_user_status(user_id: str, status: str = 'active') -> bool:
    """修改 Hub 中用户的状态。"""
    if status not in ('active', 'disabled', 'suspended'):
        raise ValueError('非法状态值')
    try:
        hub_conn = _get_hub_conn()
        cur = hub_conn.cursor()
        cur.execute('UPDATE users SET status = ? WHERE user_id = ?', (status, user_id))
        updated = cur.rowcount
        hub_conn.commit()
        hub_conn.close()
        _debug_log(f"用户状态已修改: {user_id} -> {status}")
        return updated > 0
    except Exception as e:
        _debug_log(f"修改用户状态失败: {e}")
        return False

def list_admin_logs(limit: int = 25) -> List[dict]:
    """获取最近的管理员操作日志。"""
    try:
        hub_conn = _get_hub_conn()
        cur = hub_conn.cursor()
        cur.execute('SELECT * FROM admin_logs ORDER BY id DESC LIMIT ?', (limit,))
        rows = cur.fetchall()
        hub_conn.close()
        return [_row_to_dict(cur, row) for row in rows]
    except Exception as e:
        _debug_log(f"获取管理员日志失败: {e}")
        return []

def save_user_session(user_id: str, session_id: str, client_info: str, ip_address: str, conn: Any = None) -> bool:
    """
    记录用户登录会话

    Args:
        user_id: 用户 ID
        session_id: 会话 ID
        client_info: 客户端信息（JSON 格式）
        ip_address: 用户 IP 地址
        conn: 可选的数据库连接（用于复用连接）
    """
    need_close = False
    try:
        if conn:
            hub_conn = conn
        else:
            hub_conn = _get_hub_conn()
            need_close = True

        cur = hub_conn.cursor()

        login_at = get_timestamp_with_tz()

        cur.execute('''
            INSERT INTO user_sessions (user_id, session_id, client_info, ip_address, login_at, last_activity_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, session_id, client_info, ip_address, login_at, login_at))

        if need_close:
            hub_conn.commit()
            hub_conn.close()

        _debug_log(f"用户会话已记录: {user_id} from {ip_address}")
        return True

    except Exception as e:
        _debug_log(f"保存用户会话失败: {e}")
        return False

def update_user_stats(user_id: str, words_count: int = 0, ai_calls: int = 0, 
                     prompt_tokens: int = 0, completion_tokens: int = 0) -> bool:
    """
    更新用户统计信息（累加）
    
    Args:
        user_id: 用户 ID
        words_count: 处理的词汇数
        ai_calls: AI 调用次数
        prompt_tokens: Prompt token 数量
        completion_tokens: Completion token 数量
    """
    try:
        hub_conn = _get_hub_conn()
        cur = hub_conn.cursor()
        
        updated_at = get_timestamp_with_tz()
        
        # 先查询现有数据
        cur.execute('SELECT * FROM user_stats WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        
        if row:
            # 更新（累加）
            row_dict = _row_to_dict(cur, row)
            new_words = row_dict.get('total_words_processed', 0) + words_count
            new_calls = row_dict.get('total_ai_calls', 0) + ai_calls
            new_prompt = row_dict.get('total_prompt_tokens', 0) + prompt_tokens
            new_completion = row_dict.get('total_completion_tokens', 0) + completion_tokens
            
            cur.execute('''
                UPDATE user_stats
                SET total_words_processed = ?,
                    total_ai_calls = ?,
                    total_prompt_tokens = ?,
                    total_completion_tokens = ?,
                    last_activity_at = ?,
                    updated_at = ?
                WHERE user_id = ?
            ''', (new_words, new_calls, new_prompt, new_completion, updated_at, updated_at, user_id))
        else:
            # 新增
            cur.execute('''
                INSERT INTO user_stats (user_id, total_words_processed, total_ai_calls, 
                                       total_prompt_tokens, total_completion_tokens, 
                                       last_activity_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, words_count, ai_calls, prompt_tokens, completion_tokens, updated_at, updated_at))
        
        hub_conn.commit()
        hub_conn.close()
        _debug_log(f"用户统计已更新: {user_id}")
        return True
        
    except Exception as e:
        _debug_log(f"更新用户统计失败: {e}")
        return False

def log_admin_action(action_type: str, action_detail: str = "", admin_username: str = "",
                    target_user_id: str = "", result: str = "success", conn: Any = None) -> bool:
    """
    记录管理员操作日志

    Args:
        action_type: 操作类型（如 'create_database', 'verify_password', 'user_created'）
        action_detail: 操作详情
        admin_username: 管理员用户名
        target_user_id: 目标用户 ID（如果有）
        result: 操作结果（'success' 或 'failure'）
        conn: 可选的数据库连接（用于复用连接）
    """
    need_close = False
    try:
        if conn:
            hub_conn = conn
        else:
            hub_conn = _get_hub_conn()
            need_close = True

        cur = hub_conn.cursor()

        timestamp = get_timestamp_with_tz()

        cur.execute('''
            INSERT INTO admin_logs (action_type, action_detail, admin_username, target_user_id, timestamp, result)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (action_type, action_detail, admin_username, target_user_id, timestamp, result))

        if need_close:
            hub_conn.commit()
            hub_conn.close()

        _debug_log(f"管理员操作已记录: {action_type}")
        return True

    except Exception as e:
        _debug_log(f"记录管理员操作失败: {e}")
        return False

def update_user_login_time(user_id: str, conn: Any = None) -> bool:
    """更新用户最后登录时间"""
    need_close = False
    try:
        if conn:
            hub_conn = conn
        else:
            hub_conn = _get_hub_conn()
            need_close = True

        cur = hub_conn.cursor()

        login_time = get_timestamp_with_tz()

        cur.execute('''
            UPDATE users
            SET last_login_at = ?, first_login_at = COALESCE(first_login_at, ?)
            WHERE user_id = ?
        ''', (login_time, login_time, user_id))

        if need_close:
            hub_conn.commit()
            hub_conn.close()

        return True

    except Exception as e:
        _debug_log(f"更新用户登录时间失败: {e}")
        return False

def get_user_from_hub(user_id: str) -> Optional[dict]:
    """从中央 Hub 获取用户信息"""
    try:
        hub_conn = _get_hub_conn()
        cur = hub_conn.cursor()
        
        cur.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        hub_conn.close()
        
        return _row_to_dict(cur, row) if row else None
        
    except Exception as e:
        _debug_log(f"从 Hub 获取用户信息失败: {e}")
        return None

def sync_hub_databases(
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """同步中央 Hub 数据库（本地与云端双向同步）"""
    stats = {'upload': 0, 'download': 0, 'status': 'ok', 'reason': ''}
    sync_start = time.time()
    if not TURSO_HUB_DB_URL or not TURSO_HUB_AUTH_TOKEN or not HAS_LIBSQL:
        stats['status'] = 'skipped'
        if not TURSO_HUB_DB_URL or not TURSO_HUB_AUTH_TOKEN:
            stats['reason'] = 'missing-hub-cloud-credentials'
        else:
            stats['reason'] = 'libsql-unavailable'
        _emit_sync_progress(progress_callback, 'skipped', 0, 0, '跳过 Hub 同步: 云端凭据或 libsql 不可用', status='skipped')
        return stats
    
    _curr_logger = get_logger()
    if not dry_run: _curr_logger.debug("正在同步中央 Hub 数据库...", module="db_manager")
    cloud_conn = None
    local_conn = None
    
    try:
        cloud_conn = _get_cloud_conn(TURSO_HUB_DB_URL, TURSO_HUB_AUTH_TOKEN)
        local_conn = sqlite3.connect(HUB_DB_PATH)
        local_conn.row_factory = sqlite3.Row

        # 先确保本地 Hub schema 完整，避免同步时出现 no such table
        local_cur = local_conn.cursor()
        local_cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                first_login_at TEXT,
                last_login_at TEXT,
                status TEXT DEFAULT 'active',
                role TEXT DEFAULT 'user',
                notes TEXT,
                updated_at TEXT
            )
        ''')
        local_cur.execute('''
            CREATE TABLE IF NOT EXISTS user_auth (
                user_id TEXT PRIMARY KEY,
                password_hash TEXT,
                auth_type TEXT DEFAULT 'local',
                failed_attempts INTEGER DEFAULT 0,
                last_failed_at TEXT,
                last_password_change TEXT,
                must_change_password INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        local_cur.execute('''
            CREATE TABLE IF NOT EXISTS user_sync_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                sync_type TEXT NOT NULL,
                source TEXT,
                target TEXT,
                record_count INTEGER,
                sync_status TEXT,
                error_msg TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        local_cur.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id TEXT PRIMARY KEY,
                total_words_processed INTEGER DEFAULT 0,
                total_ai_calls INTEGER DEFAULT 0,
                total_prompt_tokens INTEGER DEFAULT 0,
                total_completion_tokens INTEGER DEFAULT 0,
                total_sync_count INTEGER DEFAULT 0,
                last_activity_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        local_cur.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_id TEXT UNIQUE NOT NULL,
                client_info TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                login_at TEXT NOT NULL,
                logout_at TEXT,
                last_activity_at TEXT,
                session_status TEXT DEFAULT 'active',
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        local_cur.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                action_detail TEXT,
                admin_username TEXT,
                target_user_id TEXT,
                timestamp TEXT NOT NULL,
                result TEXT DEFAULT 'success'
            )
        ''')
        local_cur.execute('''
            CREATE TABLE IF NOT EXISTS user_credentials (
                user_id TEXT PRIMARY KEY,
                turso_db_url_enc TEXT,
                turso_auth_token_enc TEXT,
                momo_token_enc TEXT,
                mimo_api_key_enc TEXT,
                gemini_api_key_enc TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        local_conn.commit()
        
        sync_targets = [
            ('users', 'user_id'),
            ('user_stats', 'user_id'),
            ('user_auth', 'user_id'),
            ('user_sessions', 'session_id'),
            ('user_sync_history', 'id'),
            ('admin_logs', 'id'),
            ('user_credentials', 'user_id'),
        ]

        total_steps = len(sync_targets) + 2
        step = 1
        _emit_sync_progress(progress_callback, 'connect', step, total_steps, '连接 Hub 本地和云端数据库')

        step += 1

        table_errors: List[str] = []

        for table_name, primary_key in sync_targets:
            try:
                table_started_at = time.time()
                _emit_sync_progress(progress_callback, 'table', step, total_steps, f"同步 Hub 表 {table_name}", table=table_name)
                u, d = _sync_hub_table(cloud_conn, local_conn, table_name, primary_key, dry_run)
                stats['upload'] += u
                stats['download'] += d
                table_elapsed_ms = int((time.time() - table_started_at) * 1000)
                _emit_sync_progress(
                    progress_callback,
                    'table-done',
                    step,
                    total_steps,
                    f"Hub {table_name}: 上传 {u}, 下载 {d}",
                    table=table_name,
                    upload=u,
                    download=d,
                    duration_ms=table_elapsed_ms,
                )
            except Exception as table_error:
                error_kind = type(table_error).__name__
                error_text = f"{table_name}:{error_kind}:{table_error}"
                table_errors.append(error_text)
                _debug_log(f"Hub 表同步跳过: {table_name} -> [{error_kind}] {table_error}")
                _emit_sync_progress(
                    progress_callback,
                    'table-error',
                    step,
                    total_steps,
                    f"Hub {table_name} 跳过: [{error_kind}] {table_error}",
                    table=table_name,
                    status='partial',
                )
            step += 1

        if table_errors and stats['status'] == 'ok':
            stats['status'] = 'partial'
            stats['reason'] = '; '.join(table_errors[:3])

        _emit_sync_progress(
            progress_callback,
            'finalize',
            total_steps,
            total_steps,
            '完成 Hub 同步',
            upload=stats['upload'],
            download=stats['download'],
            status=stats['status'],
            reason=stats['reason'],
        )
        
        total_elapsed_ms = int((time.time() - sync_start) * 1000)
        stats['duration_ms'] = total_elapsed_ms
        if not dry_run: _curr_logger.debug(f"Hub 同步完成: 上传 {stats['upload']}, 下载 {stats['download']} | 耗时 {total_elapsed_ms}ms", module="db_manager")
        return stats
    except Exception as e:
        _debug_log(f"Hub 同步失败: {e}")
        stats['status'] = 'error'
        stats['reason'] = str(e)
        _emit_sync_progress(progress_callback, 'error', 0, 0, f"Hub 同步失败: {e}", status='error', reason=str(e))
        return stats
    finally:
        if cloud_conn:
            try:
                cloud_conn.close()
            except Exception:
                pass
        if local_conn:
            try:
                local_conn.close()
            except Exception:
                pass

def _sync_hub_table(cloud_conn, local_conn, table_name: str, primary_key: str, dry_run: bool = False):
    """优化后的 Hub 同步：处理空时间戳并采用轻量化模式"""
    cloud_cur = cloud_conn.cursor()
    local_cur = local_conn.cursor()

    def _extract_pair(cursor_obj, row_obj):
        if row_obj is None:
            return None, None
        if isinstance(row_obj, (tuple, list)) and len(row_obj) >= 2:
            return row_obj[0], row_obj[1]
        try:
            return row_obj[0], row_obj[1]
        except Exception:
            row_dict = _row_to_dict(cursor_obj, row_obj)
            values = list(row_dict.values())
            if len(values) >= 2:
                return values[0], values[1]
            raise ValueError(f"unexpected metadata row format for table {table_name}: {row_obj}")

    ts_col_map = {
        'admin_logs': 'timestamp',
        'user_sync_history': 'timestamp',
        'user_sessions': 'last_activity_at',
        'users': 'last_login_at',
    }
    ts_col = ts_col_map.get(table_name, 'updated_at')

    # 1. 快速路径检测
    try:
        cloud_cur.execute(f'SELECT COUNT(*), MAX({ts_col}) FROM {table_name}')
        c_count, c_max_ts = _extract_pair(cloud_cur, cloud_cur.fetchone())
        local_cur.execute(f'SELECT COUNT(*), MAX({ts_col}) FROM {table_name}')
        l_count, l_max_ts = _extract_pair(local_cur, local_cur.fetchone())
        
        if c_count == l_count and str(c_max_ts) == str(l_max_ts) and c_max_ts is not None:
            return 0, 0
    except Exception:
        pass

    # 2. 元数据拉取
    cloud_cur.execute(f'SELECT {primary_key}, {ts_col} FROM {table_name}')
    cloud_meta = {}
    for r in cloud_cur.fetchall():
        key, ts = _extract_pair(cloud_cur, r)
        cloud_meta[key] = ts
    
    local_cur.execute(f'SELECT {primary_key}, {ts_col} FROM {table_name}')
    local_meta = {}
    for r in local_cur.fetchall():
        key, ts = _extract_pair(local_cur, r)
        local_meta[key] = ts

    def _clean_ts(ts):
        if not ts: return "0000-00-00" # 给空值一个极小的时间戳
        return str(ts).split('.')[0].replace('T', ' ')

    keys_to_upload = []
    keys_to_download = []

    for k, l_ts in local_meta.items():
        c_ts = cloud_meta.get(k)
        # 如果云端没有，或者本地更亲（包括本地有时间戳而云端没有的情况）
        if k not in cloud_meta or _clean_ts(l_ts) > _clean_ts(c_ts):
            keys_to_upload.append(k)
            
    for k, c_ts in cloud_meta.items():
        l_ts = local_meta.get(k)
        if k not in local_meta or _clean_ts(c_ts) > _clean_ts(l_ts):
            keys_to_download.append(k)

    # Hub 中 users 以云端为权威，避免本地脏记录反向覆盖并导致同步失败
    if table_name == 'users':
        keys_to_upload = []

    if dry_run: return len(keys_to_upload), len(keys_to_download)

    # 3. 按需拉取并应用
    def _fetch_and_apply_hub(src_conn, src_cur, dest_conn, dest_cur, keys, action_name):
        if not keys: return 0
        total_count = 0
        CHUNK_SIZE = 40
        for i in range(0, len(keys), CHUNK_SIZE):
            chunk_keys = keys[i:i + CHUNK_SIZE]
            placeholders = ', '.join(['?'] * len(chunk_keys))
            src_cur.execute(f'SELECT * FROM {table_name} WHERE {primary_key} IN ({placeholders})', chunk_keys)
            rows = src_cur.fetchall()
            if not rows: continue
            
            data = [_row_to_dict(src_cur, r) for r in rows]
            cols = ', '.join(data[0].keys())
            vals = ', '.join(['?'] * len(data[0]))
            sql = f'INSERT OR REPLACE INTO {table_name} ({cols}) VALUES ({vals})'
            
            dest_cur.executemany(sql, [tuple(r.values()) for r in data])
            dest_conn.commit()
            total_count += len(data)
        return total_count

    up = _fetch_and_apply_hub(local_conn, local_cur, cloud_conn, cloud_cur, keys_to_upload, "上传")
    down = _fetch_and_apply_hub(cloud_conn, cloud_cur, local_conn, local_cur, keys_to_download, "下载")

    return up, down

