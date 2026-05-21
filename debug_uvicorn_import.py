"""验证：import uvicorn 是否就能复现崩溃。"""
import os
os.environ['MOMO_USER'] = 'asher'

import threading
import time

print(f"[main/{threading.get_ident()}] importing uvicorn/fastapi...")
import uvicorn
import fastapi
import starlette
print(f"[main/{threading.get_ident()}] imports done")

import config as cfg
print(f"[main/{threading.get_ident()}] DB_PATH={cfg.DB_PATH}")

from database.schema import init_db
init_db()
print(f"[main/{threading.get_ident()}] init_db done")

from database.connection import _get_main_write_conn_singleton, init_concurrent_system
conn = _get_main_write_conn_singleton(do_sync=False)
init_concurrent_system()
print(f"[main/{threading.get_ident()}] concurrent system started; conn id={id(conn)}")

time.sleep(1)

from database.sql_constants import UNSYNCED_NOTES_SELECT_SQL


def run_probes():
    tid = threading.get_ident()
    for sql in (
        "SELECT 1",
        "SELECT COUNT(*) FROM ai_word_notes",
        "SELECT COUNT(*) FROM ai_word_notes WHERE sync_status = 0",
        UNSYNCED_NOTES_SELECT_SQL,
    ):
        print(f"[probe/{tid}] {sql[:80]}", flush=True)
        try:
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            cur.close()
            print(f"[probe/{tid}]   -> {len(rows)} rows", flush=True)
        except BaseException as e:
            print(f"[probe/{tid}]   FAIL: {type(e).__name__}: {e}", flush=True)
            return


print(f"[main/{threading.get_ident()}] running probes in worker thread...")
t = threading.Thread(target=run_probes, name="probe-thread")
t.start()
t.join()
print(f"[main/{threading.get_ident()}] done")
