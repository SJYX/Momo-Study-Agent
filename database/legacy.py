"""database/legacy.py — 兼容旧版 db_manager 风格接口，转发到新分层实现。

This module intentionally re-exports symbols from the new database package
without requiring any `core.db_manager` imports. Legacy callers migrating
from `from core.db_manager import X` can switch to `from database.legacy import X`
as a drop-in replacement; new code should depend on the specific database
submodules directly.
"""
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import shutil
import sqlite3

from config import DB_PATH, HUB_DB_PATH, TEST_DB_PATH, TURSO_HUB_AUTH_TOKEN, TURSO_HUB_DB_URL

from . import connection
from .connection import *  # noqa: F401,F403
from .hub_users import *  # noqa: F401,F403
from .momo_words import *  # noqa: F401,F403
from .schema import *  # noqa: F401,F403
from .utils import *  # noqa: F401,F403

try:
    import libsql
except Exception:
    libsql = None


HAS_LIBSQL = connection.HAS_LIBSQL
TURSO_DB_URL = connection.TURSO_DB_URL
TURSO_AUTH_TOKEN = connection.TURSO_AUTH_TOKEN


def init_test_db() -> None:
    init_db(TEST_DB_PATH)
