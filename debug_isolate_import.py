"""逐个 import 找出 libsql 冲突的对象。"""
import os
os.environ['MOMO_USER'] = 'asher'
import threading, time, sys

print(f"[main] start; ident={threading.get_ident()}", flush=True)

# 启动 libsql conn
import config as cfg
print(f"[main] DB={cfg.DB_PATH}", flush=True)
from database.connection import _get_main_write_conn_singleton, init_concurrent_system
from database.schema import init_db
init_db()
conn = _get_main_write_conn_singleton(do_sync=False)
init_concurrent_system()
print(f"[main] libsql conn ready id={id(conn)}", flush=True)


def probe(label: str) -> None:
    print(f"\n=== probe @ {label} ===", flush=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ai_word_notes WHERE sync_status = 0")
        rows = cur.fetchall()
        cur.close()
        print(f"[probe {label}] OK {rows}", flush=True)
    except BaseException as e:
        print(f"[probe {label}] FAIL {type(e).__name__}: {e}", flush=True)
        raise


# 基线
probe("baseline")

# 按顺序 import，每个之后探测
imports_to_test = [
    ("h11", "import h11"),
    ("httptools", "import httptools"),
    ("websockets", "import websockets"),
    ("wsproto", "import wsproto"),
    ("anyio", "import anyio"),
    ("starlette", "import starlette"),
    ("starlette.applications", "import starlette.applications"),
    ("starlette.routing", "import starlette.routing"),
    ("fastapi", "import fastapi"),
    ("uvicorn", "import uvicorn"),
    ("uvicorn.protocols.http.httptools_impl", "import uvicorn.protocols.http.httptools_impl"),
    ("pydantic", "import pydantic"),
]

for name, stmt in imports_to_test:
    print(f"\n--- importing {name} ---", flush=True)
    try:
        exec(stmt)
    except BaseException as e:
        print(f"[import {name}] FAIL {type(e).__name__}: {e}", flush=True)
        continue
    try:
        probe(name)
    except BaseException:
        print(f"!!! 崩溃在 {name} import 之后 !!!", flush=True)
        sys.exit(1)

print("\n所有 import 都通过了。问题不在单纯 import 上。", flush=True)
