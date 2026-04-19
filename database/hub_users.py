# -*- coding: utf-8 -*-
"""Hub database business logic (users/sessions/stats/admin logs)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import connection
from .schema import init_users_hub_tables
from .utils import (
    _debug_log,
    _decrypt_secret_value,
    _encrypt_secret_value,
    _get_secret_key_bytes,
    get_timestamp_with_tz,
)


def save_user_info_to_hub(
    user_id: str,
    username: str,
    email: str,
    user_notes: str = "",
    role: str = "user",
    conn: Any = None,
) -> bool:
    """Upsert user profile row into hub users table."""
    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()

            timestamp = get_timestamp_with_tz()
            normalized_username = (username or "").strip().lower()
            final_role = role
            if normalized_username == "asher":
                final_role = "admin"

            existing = None
            if user_id:
                cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                existing = cur.fetchone()
            if not existing:
                cur.execute("SELECT * FROM users WHERE lower(username) = ?", (normalized_username,))
                existing = cur.fetchone()

            existing_data = connection._row_to_dict(cur, existing) if existing else {}
            inserted_user_id = existing_data.get("user_id", user_id)
            created_at = existing_data.get("created_at", timestamp)
            first_login_at = existing_data.get("first_login_at")
            last_login_at = existing_data.get("last_login_at")
            existing_role = existing_data.get("role")
            if existing_role and str(existing_role).lower() == "admin":
                final_role = "admin"
            status = existing_data.get("status", "active")

            cur.execute(
                """
                INSERT OR REPLACE INTO users (user_id, username, email, created_at, first_login_at, last_login_at, status, role, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inserted_user_id,
                    normalized_username,
                    email,
                    created_at,
                    first_login_at,
                    last_login_at,
                    status,
                    final_role,
                    user_notes,
                    timestamp,
                ),
            )
            return normalized_username, inserted_user_id

        normalized_username, inserted_user_id = connection._run_with_managed_connection(conn, connection._get_hub_conn, _do_sql)
        _debug_log(f"用户信息已保存到 Hub: {normalized_username} ({inserted_user_id})", module="database.hub_users")
        return True
    except Exception as e:
        _debug_log(f"保存用户信息到 Hub 失败: {e}", level="WARNING", module="database.hub_users")
        return False


def save_user_credentials_to_hub(user_id: str, credentials: Dict[str, str], conn: Any = None) -> bool:
    """Save encrypted user credentials to hub."""
    if not user_id:
        return False
    if not credentials:
        return True

    key_bytes = _get_secret_key_bytes()
    if not key_bytes:
        _debug_log("跳过保存 Hub 凭据：ENCRYPTION_KEY 未配置", level="WARNING", module="database.hub_users")
        return False

    field_map = {
        "turso_db_url": "turso_db_url_enc",
        "turso_auth_token": "turso_auth_token_enc",
        "momo_token": "momo_token_enc",
        "mimo_api_key": "mimo_api_key_enc",
        "gemini_api_key": "gemini_api_key_enc",
    }

    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()
            cur.execute("SELECT * FROM user_credentials WHERE user_id = ?", (user_id,))
            existing = cur.fetchone()
            existing_data = connection._row_to_dict(cur, existing) if existing else {}

            now = get_timestamp_with_tz()
            created_at = existing_data.get("created_at", now)

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

            cur.execute(
                """
                INSERT OR REPLACE INTO user_credentials (
                    user_id, turso_db_url_enc, turso_auth_token_enc, momo_token_enc,
                    mimo_api_key_enc, gemini_api_key_enc, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_values["user_id"],
                    row_values.get("turso_db_url_enc"),
                    row_values.get("turso_auth_token_enc"),
                    row_values.get("momo_token_enc"),
                    row_values.get("mimo_api_key_enc"),
                    row_values.get("gemini_api_key_enc"),
                    row_values["created_at"],
                    row_values["updated_at"],
                ),
            )

        connection._run_with_managed_connection(conn, connection._get_hub_conn, _do_sql)
        _debug_log(f"用户凭据已更新到 Hub: {user_id}", module="database.hub_users")
        return True
    except Exception as e:
        _debug_log(f"保存用户凭据到 Hub 失败: {e}", level="WARNING", module="database.hub_users")
        return False


def get_user_credentials_from_hub(user_id: str, decrypt_values: bool = False) -> Optional[dict]:
    """Fetch user credentials from hub; optionally return decrypted values."""
    if not user_id:
        return None
    try:
        data = connection._hub_fetch_one_dict("SELECT * FROM user_credentials WHERE user_id = ?", (user_id,))
        if not data:
            return None

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
        _debug_log(f"读取用户凭据失败: {e}", level="WARNING", module="database.hub_users")
        return None


def get_user_by_username(username: str) -> Optional[dict]:
    try:
        return connection._hub_fetch_one_dict("SELECT * FROM users WHERE lower(username) = ?", ((username or "").strip().lower(),))
    except Exception as e:
        _debug_log(f"从 Hub 按用户名查询失败: {e}", level="WARNING", module="database.hub_users")
        return None


def get_user_from_hub(user_id: str) -> Optional[dict]:
    try:
        return connection._hub_fetch_one_dict("SELECT * FROM users WHERE user_id = ?", (user_id,))
    except Exception as e:
        _debug_log(f"从 Hub 获取用户信息失败: {e}", level="WARNING", module="database.hub_users")
        return None


def is_admin_username(username: str) -> bool:
    if not username:
        return False
    normalized = username.strip().lower()
    if normalized == "asher":
        return True
    user = get_user_by_username(username)
    return bool(user and str(user.get("role", "")).lower() == "admin")


def list_hub_users(limit: int = 50) -> List[dict]:
    try:
        return connection._hub_fetch_all_dicts(
            "SELECT user_id, username, email, role, status, created_at, last_login_at FROM users ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )
    except Exception as e:
        _debug_log(f"获取 Hub 用户列表失败: {e}", level="WARNING", module="database.hub_users")
        return []


def set_user_status(user_id: str, status: str = "active") -> bool:
    if status not in ("active", "disabled", "suspended"):
        raise ValueError("非法状态值")

    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()
            cur.execute("UPDATE users SET status = ? WHERE user_id = ?", (status, user_id))
            return cur.rowcount

        updated = connection._run_with_managed_connection(None, connection._get_hub_conn, _do_sql)
        _debug_log(f"用户状态已修改: {user_id} -> {status}", module="database.hub_users")
        return updated > 0
    except Exception as e:
        _debug_log(f"修改用户状态失败: {e}", level="WARNING", module="database.hub_users")
        return False


def save_user_session(user_id: str, session_id: str, client_info: str, ip_address: str, conn: Any = None) -> bool:
    """Record user login session."""
    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()
            login_at = get_timestamp_with_tz()
            cur.execute(
                """
                INSERT INTO user_sessions (user_id, session_id, client_info, ip_address, login_at, last_activity_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, session_id, client_info, ip_address, login_at, login_at),
            )

        connection._run_with_managed_connection(conn, connection._get_hub_conn, _do_sql)
        _debug_log(f"用户会话已记录: {user_id} from {ip_address}", module="database.hub_users")
        return True
    except Exception as e:
        _debug_log(f"保存用户会话失败: {e}", level="WARNING", module="database.hub_users")
        return False


def update_user_stats(
    user_id: str,
    words_count: int = 0,
    ai_calls: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> bool:
    """Incremental update for user statistics."""
    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()
            updated_at = get_timestamp_with_tz()

            cur.execute("SELECT * FROM user_stats WHERE user_id = ?", (user_id,))
            row = cur.fetchone()

            if row:
                row_dict = connection._row_to_dict(cur, row)
                new_words = int(row_dict.get("total_words_processed", 0) or 0) + int(words_count or 0)
                new_calls = int(row_dict.get("total_ai_calls", 0) or 0) + int(ai_calls or 0)
                new_prompt = int(row_dict.get("total_prompt_tokens", 0) or 0) + int(prompt_tokens or 0)
                new_completion = int(row_dict.get("total_completion_tokens", 0) or 0) + int(completion_tokens or 0)

                cur.execute(
                    """
                    UPDATE user_stats
                    SET total_words_processed = ?,
                        total_ai_calls = ?,
                        total_prompt_tokens = ?,
                        total_completion_tokens = ?,
                        last_activity_at = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (new_words, new_calls, new_prompt, new_completion, updated_at, updated_at, user_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO user_stats (user_id, total_words_processed, total_ai_calls,
                                           total_prompt_tokens, total_completion_tokens,
                                           last_activity_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, words_count, ai_calls, prompt_tokens, completion_tokens, updated_at, updated_at),
                )

        connection._run_with_managed_connection(None, connection._get_hub_conn, _do_sql)
        _debug_log(f"用户统计已更新: {user_id}", module="database.hub_users")
        return True
    except Exception as e:
        _debug_log(f"更新用户统计失败: {e}", level="WARNING", module="database.hub_users")
        return False


def log_admin_action(
    action_type: str,
    action_detail: str = "",
    admin_username: str = "",
    target_user_id: str = "",
    result: str = "success",
    conn: Any = None,
) -> bool:
    """Write an admin action log row."""
    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()
            timestamp = get_timestamp_with_tz()
            cur.execute(
                """
                INSERT INTO admin_logs (action_type, action_detail, admin_username, target_user_id, timestamp, result)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (action_type, action_detail, admin_username, target_user_id, timestamp, result),
            )

        connection._run_with_managed_connection(conn, connection._get_hub_conn, _do_sql)
        _debug_log(f"管理员操作已记录: {action_type}", module="database.hub_users")
        return True
    except Exception as e:
        _debug_log(f"记录管理员操作失败: {e}", level="WARNING", module="database.hub_users")
        return False


def list_admin_logs(limit: int = 25) -> List[dict]:
    try:
        return connection._hub_fetch_all_dicts("SELECT * FROM admin_logs ORDER BY id DESC LIMIT ?", (limit,))
    except Exception as e:
        _debug_log(f"获取管理员日志失败: {e}", level="WARNING", module="database.hub_users")
        return []


def update_user_login_time(user_id: str, conn: Any = None) -> bool:
    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()
            login_time = get_timestamp_with_tz()
            cur.execute(
                """
                UPDATE users
                SET last_login_at = ?, first_login_at = COALESCE(first_login_at, ?)
                WHERE user_id = ?
                """,
                (login_time, login_time, user_id),
            )

        connection._run_with_managed_connection(conn, connection._get_hub_conn, _do_sql)
        return True
    except Exception as e:
        _debug_log(f"更新用户登录时间失败: {e}", level="WARNING", module="database.hub_users")
        return False


__all__ = [
    "init_users_hub_tables",
    "save_user_info_to_hub",
    "save_user_credentials_to_hub",
    "get_user_credentials_from_hub",
    "get_user_by_username",
    "get_user_from_hub",
    "is_admin_username",
    "list_hub_users",
    "set_user_status",
    "save_user_session",
    "update_user_stats",
    "log_admin_action",
    "list_admin_logs",
    "update_user_login_time",
]
