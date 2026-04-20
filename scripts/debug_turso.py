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
HEADERS = {"Authorization": f"Bearer {ENV.get('TURSO_MGMT_TOKEN')}"}
res = requests.get(f"https://api.turso.tech/v1/organizations/{ENV.get('TURSO_ORG_SLUG')}/databases", headers=HEADERS)
print(json.dumps(res.json(), indent=2))
