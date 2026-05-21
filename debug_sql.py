"""复制 web warmup_sync 完整路径：init_db + init_concurrent_system + 跨线程 SELECT"""
import os
os.environ['MOMO_USER'] = 'asher'

import threading
import time
print(f"[main/{threading.get_ident()}] start")

import config as cfg
print(f"[main/{threading.get_ident()}] DB_PATH={cfg.DB_PATH}")

# 步骤 1: 初始化数据库 schema + 迁移
print(f"[main/{threading.get_ident()}] step 1: init_db()...")
from database.schema import init_db
init_db()
print(f"[main/{threading.get_ident()}] step 1 done")

# 步骤 2: 拿到单例连接（warmup_sync 也做这个）
print(f"[main/{threading.get_ident()}] step 2: _get_main_write_conn_singleton()...")
from database.connection import _get_main_write_conn_singleton
conn = _get_main_write_conn_singleton(do_sync=False)
print(f"[main/{threading.get_ident()}] step 2 done; conn id={id(conn)}")

# 步骤 3: 启动并发系统
print(f"[main/{threading.get_ident()}] step 3: init_concurrent_system()...")
from database.connection import init_concurrent_system
init_concurrent_system()
print(f"[main/{threading.get_ident()}] step 3 done")

# 步骤 4: 等 1 秒，让 daemon 跑起来
print(f"[main/{threading.get_ident()}] step 4: sleep 1s...")
time.sleep(1)

# 步骤 5: 在 worker 线程跑 SELECT —— 模拟 _warmup_async
from database.sql_constants import UNSYNCED_NOTES_SELECT_SQL


def worker():
    tid = threading.get_ident()
    print(f"[worker/{tid}] start; conn id={id(conn)}", flush=True)
    try:
        cur = conn.cursor()
        print(f"[worker/{tid}] cursor created", flush=True)
        cur.execute(UNSYNCED_NOTES_SELECT_SQL)
        rows = cur.fetchall()
        cur.close()
        print(f"[worker/{tid}] OK rows={len(rows)}", flush=True)
    except BaseException as e:
        print(f"[worker/{tid}] FAIL: {type(e).__name__}: {e}", flush=True)


print(f"[main/{threading.get_ident()}] step 5: spawn worker...")
t = threading.Thread(target=worker, name="fake-warmup-async")
t.start()
t.join(timeout=30)
print(f"[main/{threading.get_ident()}] step 5 done; alive={t.is_alive()}")

# 步骤 6: 关闭
print(f"[main/{threading.get_ident()}] step 6: cleanup")
from database.connection import cleanup_concurrent_system
cleanup_concurrent_system()
print(f"[main/{threading.get_ident()}] done")
