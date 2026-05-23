import os
import turso

def load_env():
    env = {}
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def test_connection(name, url, token):
    if not url or not token:
        print(f"[FAIL] Missing credentials for {name}")
        return False
    print(f"[PING] Testing connection to {name} via {url}...")
    
    db_path = f"test_ping_{name.replace(' ', '_')}.db"
    
    def _cleanup():
        for path in (db_path, db_path + "-info", db_path + "-wal", db_path + "-shm"):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    _cleanup()
    
    try:
        db = turso.sync.connect(
            db_path,
            remote_url=url,
            auth_token=token,
        )
        res = db.execute("SELECT 1")
        row = res.fetchone()
        val = row[0] if row else None
        print(f"[SUCCESS] {name} connected! Result: {val}")
        db.close()
        return True
    except Exception as e:
        print(f"[FAIL] {name} failed: {e}")
        return False
    finally:
        _cleanup()

def main():
    ENV = load_env()
    u_url = ENV.get("TURSO_TEST_DB_URL")
    u_token = ENV.get("TURSO_TEST_AUTH_TOKEN")
    h_url = ENV.get("TURSO_TEST_HUB_DB_URL")
    h_token = ENV.get("TURSO_TEST_HUB_AUTH_TOKEN")
    
    test_connection("User Test DB", u_url, u_token)
    test_connection("Hub Test DB", h_url, h_token)

if __name__ == "__main__":
    main()
