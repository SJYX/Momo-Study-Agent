"""scripts/validate_pyturso_compat.py: Validate pyturso compatibility before P6 migration."""
import sys


def check_import():
    try:
        import turso.sync
        print("[OK] turso.sync importable")
        return True
    except ImportError as e:
        print(f"[FAIL] Cannot import turso.sync: {e}")
        return False


def check_connect():
    try:
        import turso.sync
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        db = turso.sync.connect(path)
        db.close()
        os.unlink(path)
        print("[OK] turso.sync.connect() works")
        return True
    except Exception as e:
        print(f"[FAIL] turso.sync.connect() failed: {e}")
        return False


def check_pragma():
    try:
        import turso.sync
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        db = turso.sync.connect(path)
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA synchronous=NORMAL")
        db.close()
        os.unlink(path)
        print("[OK] PRAGMA syntax compatible")
        return True
    except Exception as e:
        print(f"[FAIL] PRAGMA failed: {e}")
        return False


def check_vacuum_into():
    try:
        import turso.sync
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        db = turso.sync.connect(path)
        db.execute("CREATE TABLE t(x)")
        backup = path + ".bak"
        db.execute(f"VACUUM INTO '{backup}'")
        db.close()
        os.unlink(path)
        os.unlink(backup)
        print("[OK] VACUUM INTO supported")
        return True
    except Exception as e:
        print(f"[FAIL] VACUUM INTO failed: {e}")
        return False


def check_libsql_open():
    """尝试用 pyturso 打开现有 libSQL 格式 .db 文件。"""
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not db_path:
        print("[SKIP] libSQL open test (pass db path as argument)")
        return True
    try:
        import turso.sync
        db = turso.sync.connect(db_path)
        db.close()
        print(f"[OK] pyturso can open libSQL file: {db_path}")
        return True
    except Exception as e:
        print(f"[FAIL] Cannot open libSQL file: {e}")
        return False


if __name__ == "__main__":
    results = [check_import(), check_connect(), check_pragma(), check_vacuum_into(), check_libsql_open()]
    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} checks passed")
    sys.exit(0 if all(results) else 1)
