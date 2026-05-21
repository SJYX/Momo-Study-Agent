"""隔离测试：把 DB 文件移到非 OneDrive 路径，验证是否是 OneDrive 导致的崩溃。"""
import os, sys, time

os.environ['MOMO_USER'] = 'asher'

import config as cfg

# 把 DB 路径指向非 OneDrive 位置
alt_data = r'C:\momo_test_data'
os.makedirs(alt_data, exist_ok=True)
alt_db = os.path.join(alt_data, 'history-asher.db')

print(f'Original DB: {cfg.DB_PATH}')
print(f'Test DB:     {alt_db}')
print(f'Original In OneDrive: {"OneDrive" in cfg.DB_PATH}')
print(f'Test In OneDrive:     {"OneDrive" in alt_db}')

# 覆盖所有 DB_PATH 引用
cfg.DB_PATH = alt_db
import database.connection as db_conn
db_conn.DB_PATH = alt_db

# 清除残留
for s in ['', '-info', '-wal', '-shm']:
    try:
        os.remove(alt_db + s)
    except:
        pass
print(f'DB exists before: {os.path.exists(alt_db)}')

from database.connection import _get_main_write_conn_singleton

t0 = time.time()
try:
    conn = _get_main_write_conn_singleton(do_sync=False)
    elapsed = time.time() - t0
    size_mb = os.path.getsize(alt_db) / 1024 / 1024
    print(f'RESULT: OK in {elapsed:.1f}s, size: {size_mb:.1f}MB')
except Exception as e:
    elapsed = time.time() - t0
    print(f'RESULT: FAIL after {elapsed:.1f}s: {type(e).__name__}: {e}')
except BaseException as e:
    elapsed = time.time() - t0
    print(f'RESULT: CRASH after {elapsed:.1f}s: {type(e).__name__}: {e}')

# 清理
from database.connection import _close_main_write_conn_singleton
_close_main_write_conn_singleton()
for s in ['', '-info', '-wal', '-shm']:
    try:
        os.remove(alt_db + s)
    except:
        pass
