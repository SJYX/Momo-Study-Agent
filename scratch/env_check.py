import sqlite3
import json
import os

db_path = 'data/history_test_user.db'
if not os.path.exists('data'): os.makedirs('data')

conn = sqlite3.connect(':memory:')
cur = conn.cursor()
cur.execute('SELECT sqlite_version()')
version = cur.fetchone()[0]
print(f"SQLite Version: {version}")

try:
    cur.execute('SELECT json_extract(\'{"a": 1}\', "$.a")')
    print(f"JSON Support: {cur.fetchone()[0]}")
except Exception as e:
    print(f"JSON Support: Failed ({e})")

conn.close()
