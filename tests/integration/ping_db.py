import os
import asyncio
from libsql_client import create_client

def load_env():
    env = {}
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env

async def test_connection(name, url, token):
    # 尝试使用 https:// 强制走 HTTP 协议，避开 WebSocket 握手问题
    url = url.replace("libsql://", "https://")
    print(f"[PING] Testing connection to {name} via {url}...")
    if not url or not token:
        print(f"[FAIL] Missing credentials for {name}")
        return False
    try:
        async with create_client(url=url, auth_token=token) as client:
            res = await client.execute("SELECT 1")
            print(f"[SUCCESS] {name} connected! Result: {res.rows[0][0]}")
            return True
    except Exception as e:
        print(f"[FAIL] {name} failed: {e}")
        return False

async def main():
    ENV = load_env()
    u_url = ENV.get("TURSO_TEST_DB_URL")
    u_token = ENV.get("TURSO_TEST_AUTH_TOKEN")
    h_url = ENV.get("TURSO_TEST_HUB_DB_URL")
    h_token = ENV.get("TURSO_TEST_HUB_AUTH_TOKEN")
    
    await asyncio.gather(
        test_connection("User Test DB", u_url, u_token),
        test_connection("Hub Test DB", h_url, h_token)
    )

if __name__ == "__main__":
    asyncio.run(main())
