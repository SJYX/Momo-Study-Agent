import os
import requests
import json

def load_env():
    env = {}
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env

ENV = load_env()

def test_http(name, url, token):
    print(f"Testing HTTP access for {name}...")
    # Convert libsql:// to https://
    http_url = url.replace("libsql://", "https://") + "/v1/execute"
    payload = {"statements": ["SELECT 1"]}
    headers = {"Authorization": f"Bearer {token}"}
    
    res = requests.post(http_url, headers=headers, json=payload)
    print(f"Status: {res.status_code}")
    print(f"Response: {res.text}")

def main():
    u_url = ENV.get("TURSO_TEST_DB_URL")
    u_token = ENV.get("TURSO_TEST_AUTH_TOKEN")
    test_http("User Test DB", u_url, u_token)

if __name__ == "__main__":
    main()
