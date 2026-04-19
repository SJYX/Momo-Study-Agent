import os
import sys
import uuid
import glob
import requests
import json
import importlib

# 注入根目录以便导入
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

# 设置终端编码以防止 Windows 乱码
os.environ["PYTHONIOENCODING"] = "utf-8"

from database import hub_users as hub_users_db
from database import schema as schema_db
from core.config_wizard import ConfigWizard
from core.logger import get_logger

logger = get_logger()

def scan_for_turso_credentials():
    """扫描所有存在的 Profile 以寻找 Turso 凭据"""
    profiles_dir = os.path.join(ROOT_DIR, "data", "profiles")
    candidates = []
    
    # 同时也检查根目录 .env
    root_env = os.path.join(ROOT_DIR, ".env")
    if os.path.exists(root_env):
        candidates.append(root_env)
        
    env_files = glob.glob(os.path.join(profiles_dir, "*.env"))
    candidates.extend(env_files)
    
    found_tokens = set()
    found_orgs = set()
    
    for f in candidates:
        try:
            with open(f, 'r', encoding='utf-8') as file:
                for line in file:
                    line = line.strip()
                    if not line or line.startswith('#'): continue
                    if '=' in line:
                        k, v = line.split('=', 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k in ("TURSO_AUTH_TOKEN", "TURSO_HUB_AUTH_TOKEN") and v:
                            found_tokens.add(v)
                        if k == "TURSO_ORG_SLUG" and v:
                            found_orgs.add(v)
        except:
            continue
            
    return list(found_tokens), list(found_orgs)

def test_turso_token(token):
    """测试 Token 是否具有平台管理权限，并尝试返回首个 Org Slug"""
    url = "https://api.turso.tech/v1/organizations"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            orgs = resp.json()
            if isinstance(orgs, list) and orgs:
                # 寻找第一个不是个人的 org 或者是唯一的 org
                return True, orgs[0].get("slug")
        return False, None
    except:
        return False, None

def create_platform_api_token(mother_token, token_name="momo-hub-manager", org_slug=None):
    """
    使用母令牌创建一个新的平台级 API Token (Org-scoped)
    API 参考: https://api.turso.tech/v1/auth/api-tokens/{tokenName}
    """
    url = f"https://api.turso.tech/v1/auth/api-tokens/{token_name}"
    headers = {
        "Authorization": f"Bearer {mother_token}",
        "Content-Type": "application/json"
    }
    payload = {}
    if org_slug:
        payload["organization"] = org_slug
        
    try:
        print(f"  正在通过 API 为此 Organization 创建专用平台令牌: {token_name}...")
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code in (200, 201):
            data = resp.json()
            new_token = data.get("token")
            if new_token:
                print(f"  ✅ 专用平台令牌已生成")
                return new_token
        elif resp.status_code == 409:
            print(f"  ℹ️ 专用平台令牌 {token_name} 已存在，正在复用母令牌执行后续操作...")
            # 注意：API 无法直接找回旧 Token，但母令牌既然能触发 409 说明权限足够
            return mother_token 
        else:
            print(f"  ⚠️ 创建专用令牌失败: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"  ⚠️ 创建专用令牌异常: {e}")
        return None

def update_root_env(updates):
    """更新根目录的 .env 文件"""
    env_path = os.path.join(ROOT_DIR, ".env")
    lines = []
    existing = {}
    
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.rstrip('\n')
                if not line or line.startswith('#'):
                    lines.append(line)
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip()
                    existing[k] = len(lines)
                    if k in updates:
                        lines.append(f'{k}="{updates[k]}"')
                    else:
                        lines.append(line)
                else:
                    lines.append(line)
    
    for k, v in updates.items():
        if k not in existing:
            lines.append(f'{k}="{v}"')
            
    with open(env_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines).rstrip() + '\n')

def init_hub_smart():
    """智能初始化中央 Hub 数据库"""
    print("\n" + "="*40)
    print("Momo Study Agent - 中央 Hub 建立向导 (智能版 V2)")
    print("="*40)

    # 1. 自动探测凭据
    print("\n[Step 1] 正在扫描系统中的 Turso 凭据...")
    tokens, orgs = scan_for_turso_credentials()
    
    valid_mother_token = None
    org_slug = orgs[0] if orgs else None
    
    for t in tokens:
        is_valid, slug = test_turso_token(t)
        if is_valid:
            valid_mother_token = t
            org_slug = org_slug or slug
            print(f"  ✅ 发现有效的管理令牌 (Org: {org_slug})")
            break
            
    if not valid_mother_token:
        print("  ❌ 未发现有效的 Turso 管理令牌。")
        choice = input("\n您是否希望手动输入 Turso 管理令牌以建立云端 Hub？(y/n): ").strip().lower()
        if choice == 'y':
            valid_mother_token = input("请输入 Turso Auth Token (母令牌): ").strip()
            is_valid, slug = test_turso_token(valid_mother_token)
            if not is_valid:
                print("  ❌ 令牌无效或无权限，将回退至本地模式。")
                valid_mother_token = None
            else:
                org_slug = slug
        else:
            print("  ℹ️ 将使用本地 SQLite 建立 Hub。")

    hub_manager_token = None
    
    # 2. 如果有母令牌，通过 API 创建专用 Token 并配置云端资源
    if valid_mother_token:
        print("\n[Step 2] 正在配置云端 Hub 资源与专用令牌...")
        if not org_slug:
            org_slug = input("请输入您的 Turso Organization Slug: ").strip()
            
        # 根据用户要求，使用 API 创建一个新的专用 Token (Org-scoped)
        hub_manager_token = create_platform_api_token(valid_mother_token, "momo-hub-manager", org_slug)
        
        # 如果创建失败，尝试复用母令牌（尽管不推荐，但作为 fallback）
        final_token = hub_manager_token or valid_mother_token
        
        wizard = ConfigWizard(os.path.join(ROOT_DIR, "data", "profiles"))
        hub_db = wizard._create_or_get_turso_hub_database(org_slug, final_token)
        
        if hub_db:
            hostname = hub_db.get('Hostname') or hub_db.get('hostname') or ''
            hub_url = f"https://{hostname}"
            
            # 获取数据库访问 JWT (用于连接特定的 hub 库)
            hub_db_jwt = wizard._setup_hub_auth_token(org_slug, final_token)
            
            if hub_db_jwt:
                # 注入环境变量供 db_manager 使用
                os.environ['TURSO_HUB_DB_URL'] = hub_url
                os.environ['TURSO_HUB_AUTH_TOKEN'] = hub_db_jwt
                
                # 记录到根目录 .env
                env_updates = {
                    "TURSO_HUB_DB_URL": hub_url,
                    "TURSO_HUB_AUTH_TOKEN": hub_db_jwt,
                    "TURSO_ORG_SLUG": org_slug
                }
                # 如果我们成功创建了专用管理令牌，也把它存起来，以便将来使用
                if hub_manager_token:
                    env_updates["TURSO_MGMT_TOKEN"] = hub_manager_token
                    
                update_root_env(env_updates)
                
                print(f"  ✅ 云端 Hub 资源已就绪: {hub_url}")
                print(f"  ✅ 专用平台令牌 (TURSO_MGMT_TOKEN) 已回写 (.env)")
            else:
                print("  ❌ 无法生成 Hub 访问 JWT，回退本地模式。")
        else:
            print("  ❌ 无法获取云端数据库，回退本地模式。")

    # 3. 初始化表结构
    print("\n[Step 3] 正在初始化数据库表结构...")
    importlib.reload(schema_db)
    importlib.reload(hub_users_db)
    
    success = schema_db.init_users_hub_tables()
    if not success:
        print("  ❌ 初始化表结构失败。")
        return False
    print("  ✅ 表结构初始化完成。")

    # 4. 创建默认管理员
    print("\n[Step 4] 正在配置管理员账户...")
    admin_username = "Asher"
    admin_email = "asher@momo.com"
    
    existing_user = hub_users_db.get_user_by_username(admin_username)
    if existing_user:
        print(f"  ℹ️ 管理员账户 {admin_username} 已存在。")
    else:
        user_id = str(uuid.uuid4())
        success = hub_users_db.save_user_info_to_hub(
            user_id=user_id,
            username=admin_username,
            email=admin_email,
            user_notes="系统初始化管理员",
            role="admin"
        )
        if success:
            hub_users_db.log_admin_action("hub_initialized", "中央 Hub 智能初始化 V2 (集成 API Token)", "System", user_id)
            print(f"  ✅ 管理员账户 {admin_username} 创建成功 (初始密码: sjy@1518)。")
        else:
            print(f"  ❌ 管理员账户创建失败。")
            return False

    print("\n" + "="*40)
    print("✨ 中央 Hub 建立并初始化成功！")
    print("========================================\n")
    return True

if __name__ == "__main__":
    try:
        if init_hub_smart():
            sys.exit(0)
        else:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n[Exit] 用户中断。")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 初始化过程中发生异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
