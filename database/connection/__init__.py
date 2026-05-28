from __future__ import annotations
"""database/connection — 连接管理包 (拆自原 single-file connection.py)。

子模块职责:
- context.py   纯助手 (路径谓词、上下文解析、日志、backend 获取)
- factory.py   连接工厂 (本地/云端/Hub 连接打开 + 读路径分发)
- singleton.py 写单例 (主库与 Hub 的长期持有连接)

外部 import 兼容:`from database.connection import _get_local_conn` 等原有
写法继续可用,本 __init__ 透明 re-export。**例外**:
`_main_write_conn_singleton` / `_main_write_conn_singleton_path` /
`_hub_write_conn_singleton` 是模块级可变 globals,Python `from … import`
会拿快照,故 **不在此处 re-export**;直接读它们的位置(如
`web/backend/routers/ops.py`)必须 `from database.connection.singleton
import _main_write_conn_singleton`。
"""

# 纯助手与谓词
from .context import (
    HAS_PYTURSO,
    HUB_DB_PATH,
    TURSO_HUB_AUTH_TOKEN,
    TURSO_HUB_DB_URL,
    TURSO_TEST_AUTH_TOKEN,
    TURSO_TEST_DB_HOSTNAME,
    TURSO_TEST_DB_URL,
    _debug_log,
    _get_backend,
    _is_hub_db_path,
    _is_main_db_path,
    _is_replica_metadata_missing_error,
    _resolve_conn_context,
    _row_to_dict,
    _schema_init_callbacks,
    get_logger,
    register_schema_initializers,
)

# 连接工厂与读路径
from .factory import (
    _close_read_conn_pool,
    _get_conn,
    _get_hub_conn,
    _get_hub_local_conn,
    _get_local_conn,
    _get_local_read_conn,
    _get_read_conn,
    _get_read_conn_impl,
    _hub_fetch_all_dicts,
    _hub_fetch_one_dict,
    _invalidate_read_conn_pool,
    _run_with_managed_connection,
    _should_use_local_only_connection,
    _wrap_and_track_connection,
    is_hub_configured,
    set_runtime_cloud_credentials,
)

# 写单例 — 仅函数;模块级可变 globals 故意不 re-export (见上方注释)
from .singleton import (
    _close_hub_write_conn_singleton,
    _close_main_write_conn_singleton,
    _get_dedicated_write_conn,
    _get_hub_write_conn_singleton,
    _get_main_write_conn_singleton,
)

# 转发自 database.execution_engine — 维持原 connection.py 末尾的 re-export 行为
# 消费者:
#   - database/_repo_helpers.py 访问 2 个 _execute_* 名
#   - core/study_flow.py 访问 init_db_session_resources / cleanup_db_session_resources
from database.execution_engine import (
    _execute_batch_write_sql_sync,
    _execute_write_sql_sync,
    cleanup_db_session_resources,
    init_db_session_resources,
)
