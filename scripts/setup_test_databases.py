import os
import requests
import json
import time

# 从 .env 手动读取凭据（避免依赖未完全加载的 config.py）
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
MGMT_TOKEN = ENV.get("TURSO_MGMT_TOKEN")
ORG_SLUG = ENV.get("TURSO_ORG_SLUG")
API_BASE = "https://api.turso.tech/v1"

if not MGMT_TOKEN or not ORG_SLUG:
    print("❌ 错误: .env 中缺少 TURSO_MGMT_TOKEN 或 TURSO_ORG_SLUG")
    exit(1)

HEADERS = {
    "Authorization": f"Bearer {MGMT_TOKEN}",
    "Content-Type": "application/json"
}

# 迁移至 group 123
TARGET_GROUP = "123"

def delete_db(db_name):
    print(f"[DELETE] Removing database {db_name} (preparing for group migration)...")
    url = f"{API_BASE}/organizations/{ORG_SLUG}/databases/{db_name}"
    res = requests.delete(url, headers=HEADERS)
    if res.status_code in [200, 202, 204]:
        print(f"[SUCCESS] Database {db_name} deleted.")
        return True
    else:
        print(f"[ERROR] Delete failed: {res.status_code} - {res.text}")
        return False

def get_or_create_db(db_name):
    print(f"[CHECK] Checking database {db_name}...")
    # 1. 检查是否存在及所属组
    url = f"{API_BASE}/organizations/{ORG_SLUG}/databases"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        dbs = res.json().get("databases", [])
        for db in dbs:
            db_name_remote = db.get("Name") or db.get("name")
            if db_name_remote == db_name:
                group = db.get("group") or db.get("Group") or "default"
                if group == TARGET_GROUP:
                    hostname = db.get("Hostname") or db.get("hostname")
                    print(f"[OK] Database {db_name} already in group {TARGET_GROUP}.")
                    return hostname
                else:
                    print(f"[MIGRATE] Database {db_name} is in group '{group}', but needs to be in '{TARGET_GROUP}'.")
                    if delete_db(db_name):
                        # 删除后给 API 一点同步时间
                        time.sleep(3)
                        break # 跳出循环去创建
                    else:
                        return None

    # 2. 创建新库
    print(f"[CREATE] Creating database {db_name} in group {TARGET_GROUP}...")
    create_url = f"{API_BASE}/organizations/default/databases" # 注意：虽然 org 是 slug，但有的 API 路由可能默认使用 default
    # 修正：url 应该保持 consistent
    create_url = f"{API_BASE}/organizations/{ORG_SLUG}/databases"
    
    payload = {
        "name": db_name,
        "group": TARGET_GROUP,
        "location": "hkg"
    }
    res = requests.post(create_url, headers=HEADERS, json=payload)
    if res.status_code in [200, 201, 202]:
        data = res.json().get("database", {})
        print(f"[SUCCESS] Database {db_name} created in group {TARGET_GROUP}.")
        
        # 同步等待 hostname 生效
        hostname = data.get("Hostname") or data.get("hostname")
        if not hostname:
            print(f"[WAIT] Hostname not in response, polling...")
            for _ in range(5):
                time.sleep(2)
                # 重新检查
                url_check = f"{API_BASE}/organizations/{ORG_SLUG}/databases"
                r = requests.get(url_check, headers=HEADERS)
                if r.status_code == 200:
                    for d in r.json().get("databases", []):
                        if (d.get("Name") or d.get("name")) == db_name:
                            return d.get("Hostname") or d.get("hostname")
        return hostname
    else:
        print(f"[ERROR] Create failed: {res.status_code} - {res.text}")
        return None

def generate_token(db_name):
    print(f"[AUTH] Generating Auth Token for {db_name}...")
    url = f"{API_BASE}/organizations/{ORG_SLUG}/databases/{db_name}/auth/tokens"
    payload = {
        "expiration": "never",
        "authorization": "full-access"
    }
    res = requests.post(url, headers=HEADERS, json=payload)
    if res.status_code == 200:
        return res.json().get("jwt")
    else:
        print(f"[RETRY] 404/Error found, trying alternative path...")
        alt_url = f"{API_BASE}/organizations/{ORG_SLUG}/databases/{db_name}/tokens"
        res = requests.post(alt_url, headers=HEADERS)
        if res.status_code == 200:
            return res.json().get("jwt")
        
        print(f"[ERROR] Token generation failed: {res.status_code} - {res.text}")
        return None

def update_env(updates):
    if not os.path.exists(".env"):
        print("[ERROR] .env file not found")
        return

    with open(".env", "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    keys_updated = set()
    
    # 更新已有行
    for line in lines:
        matched = False
        for k, v in updates.items():
            if line.startswith(f"{k}=") or line.startswith(f'#{k}='):
                new_lines.append(f'{k}="{v}"\n')
                keys_updated.add(k)
                matched = True
                break
        if not matched:
            new_lines.append(line)
            
    # 追加新行
    for k, v in updates.items():
        if k not in keys_updated:
            new_lines.append(f'{k}="{v}"\n')

    with open(".env", "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print("[CONFIG] .env updated.")

def main():
    results = {}
    
    # 1. 建立 User 测试库
    user_host = get_or_create_db("momo-test-user")
    if user_host:
        user_token = generate_token("momo-test-user")
        if user_token:
            results["TURSO_TEST_DB_URL"] = f"libsql://{user_host}"
            results["TURSO_TEST_AUTH_TOKEN"] = user_token
            
    # 2. 建立 Hub 测试库
    hub_host = get_or_create_db("momo-test-hub")
    if hub_host:
        hub_token = generate_token("momo-test-hub")
        if hub_token:
            results["TURSO_TEST_HUB_DB_URL"] = f"libsql://{hub_host}"
            results["TURSO_TEST_HUB_AUTH_TOKEN"] = hub_token

    if results:
        update_env(results)
        print("\nAll test infrastructure ready in Group 123!")
        for k, v in results.items():
            display_v = v[:15] + "..." if len(v) > 20 else v
            print(f"  {k}: {display_v}")
    else:
        print("[SKIP] No infrastructure changes made.")

if __name__ == "__main__":
    main()

