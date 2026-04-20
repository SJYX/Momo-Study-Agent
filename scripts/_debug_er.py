# -*- coding: utf-8 -*-
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'profiles', 'asher.env'), override=True)

url = os.getenv('TURSO_DB_URL', '')
token = os.getenv('TURSO_AUTH_TOKEN', '')
print(f"URL present: {bool(url)}, starts: {url[:30]}...")
print(f"Token present: {bool(token)}, len: {len(token)}")

import libsql
print(f"libsql public API: {[x for x in dir(libsql) if not x.startswith('_')]}")

# Test 1: check if connect accepts sync_url
import inspect
sig = inspect.signature(libsql.connect)
print(f"libsql.connect signature: {sig}")

# Test 2: try ER connect with timeout
local_path = os.path.join(tempfile.gettempdir(), "er_debug.db")
print(f"\nAttempting ER connect to: {local_path}")
print(f"sync_url: {url[:40]}...")
t0 = time.time()
try:
    conn = libsql.connect(local_path, sync_url=url, auth_token=token)
    elapsed = time.time() - t0
    print(f"OK connect() returned in {elapsed:.1f}s")
    
    print("Attempting sync()...")
    t1 = time.time()
    conn.sync()
    elapsed2 = time.time() - t1
    print(f"OK sync() completed in {elapsed2:.1f}s")
    
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"Tables found: {[t[0] for t in tables]}")
    
    conn.close()
    print("PASS - all checks passed")
except Exception as e:
    elapsed = time.time() - t0
    print(f"FAIL after {elapsed:.1f}s: {type(e).__name__}: {e}")
finally:
    for ext in ("", "-wal", "-shm"):
        try:
            os.remove(local_path + ext)
        except:
            pass
