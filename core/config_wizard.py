import os
import sys
import sqlite3
import requests
import getpass
from typing import Optional, Dict

# 注入根目录以便导入
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from core.maimemo_api import MaiMemoAPI
from core.preflight import run_preflight
from core.utils import mask_sensitive

class ConfigWizard:
    MAX_VALIDATE_RETRIES = 2

    def __init__(self, profiles_dir: str):
        self.profiles_dir = profiles_dir
        os.makedirs(self.profiles_dir, exist_ok=True)

    def validate_momo(self, token: str) -> Dict[str, str]:
        """联网验证墨墨 Token"""
        print("  正在验证墨墨 Token...")
        try:
            api = MaiMemoAPI(token)
            res = api.get_study_progress()
            ok = res is not None and res.get("success") is True
            if ok:
                return {"ok": True, "category": "ok", "detail": "Token 可用"}
            return {"ok": False, "category": "auth", "detail": "鉴权失败或返回异常"}
        except requests.exceptions.Timeout:
            return {"ok": False, "category": "network", "detail": "请求超时"}
        except requests.exceptions.ConnectionError:
            return {"ok": False, "category": "network", "detail": "网络不可达"}
        except Exception as exc:
            return {"ok": False, "category": "unknown", "detail": str(exc)}

    def validate_mimo(self, api_key: str) -> Dict[str, str]:
        """联网验证 Mimo API Key"""
        print("  正在验证 Mimo API Key...")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "mimo-v2-flash",
            "messages": [{"role": "user", "content": "ping"}],
            "max_completion_tokens": 5,
            "thinking": {"type": "disabled"}
        }
        try:
            response = requests.post(
                "https://api.xiaomimimo.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=10
            )
            if response.status_code == 200:
                return {"ok": True, "category": "ok", "detail": "API Key 可用"}
            if response.status_code in (401, 403):
                return {"ok": False, "category": "auth", "detail": f"认证失败: HTTP {response.status_code}"}
            if response.status_code >= 500:
                return {"ok": False, "category": "server", "detail": f"服务端异常: HTTP {response.status_code}"}
            return {"ok": False, "category": "unknown", "detail": f"请求失败: HTTP {response.status_code}"}
        except requests.exceptions.Timeout:
            return {"ok": False, "category": "network", "detail": "请求超时"}
        except requests.exceptions.ConnectionError:
            return {"ok": False, "category": "network", "detail": "网络不可达"}
        except Exception as exc:
            return {"ok": False, "category": "unknown", "detail": str(exc)}

    def validate_gemini(self, api_key: str) -> Dict[str, str]:
        """联网验证 Gemini API Key"""
        print("  正在验证 Gemini API Key...")
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            client.models.generate_content(model="gemini-2.0-flash", contents="ping")
            return {"ok": True, "category": "ok", "detail": "API Key 可用"}
        except ImportError:
            return {"ok": False, "category": "dependency", "detail": "缺少 google-genai 依赖"}
        except Exception as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg:
                return {"ok": False, "category": "auth", "detail": msg}
            return {"ok": False, "category": "unknown", "detail": msg}

    def _normalize_turso_db_url(self, hostname: str) -> str:
        if not hostname: return ''
        hostname = hostname.strip()
        if hostname.startswith('http://') or hostname.startswith('https://'):
            return hostname
        return f'https://{hostname}'

    def _read_profile_env(self, username: str) -> dict:
        path = os.path.join(self.profiles_dir, f"{username}.env")
        result = {}
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            k, v = parts
                            result[k.strip()] = v.strip().strip('"').strip("'")
        return result

    def _write_profile_env(self, username: str, updates: dict):
        path = os.path.join(self.profiles_dir, f"{username}.env")
        lines = []
        existing = {}
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                for raw in f:
                    line = raw.rstrip('\n')
                    if line and not line.strip().startswith('#') and '=' in line:
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            k, _ = parts
                            existing[k.strip()] = len(lines)
                    lines.append(line)

        for k, v in updates.items():
            if k in existing:
                lines[existing[k]] = f'{k}="{v}"'
            else:
                lines.append(f'{k}="{v}"')
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines).rstrip() + '\n')

    def _configure_cloud_for_user(self, username: str, turso_token: str, org_slug: str, group: str) -> dict:
        db_name = f'history-{username.lower()}'
        database = self._create_turso_database(org_slug, db_name, turso_token, group)
        hostname = database.get('Hostname') or database.get('hostname') or ''
        db_url = self._normalize_turso_db_url(hostname)

        # 生成数据库专用的连接令牌
        db_auth_token = self._generate_db_auth_token(org_slug, turso_token, db_name)
        if not db_auth_token:
            db_auth_token = turso_token
            print("  ⚠️  警告: 无法生成数据库专用令牌，使用管理令牌回退。")

        env_data = {
            'TURSO_DB_NAME': db_name,
            'TURSO_DB_HOSTNAME': hostname,
            'TURSO_DB_URL': db_url,
            'TURSO_AUTH_TOKEN': db_auth_token,
        }
        
        # 记录到 Hub
        try:
            from core import db_manager
            user_id = db_manager.generate_user_id(username)
            profile = self._read_profile_env(username)
            user_email = profile.get('USER_EMAIL') or f"{username}@momo-local"
            db_manager.save_user_info_to_hub(user_id, username, user_email, "自动配置云端")
            db_manager.log_admin_action("user_created", f"用户 {username} 已启用云数据库", "wizard", user_id)
        except: pass
        
        return env_data

    def ensure_cloud_database_for_profile(self, username: str):
        """确保用户的云端数据库已就绪 (Smart 模式)"""
        profile = self._read_profile_env(username)
        if profile.get('TURSO_DB_URL'): return

        if not self._confirm(f'\n用户 {username} 当前未启用云数据库，是否现在自动开启？(Y/N): ', default=False):
            return

        # 开源模式：仅从管理令牌读取（禁止回退到 TURSO_AUTH_TOKEN）
        mgmt_token = os.getenv('TURSO_MGMT_TOKEN')
        org_slug = os.getenv('TURSO_ORG_SLUG')
        group = os.getenv('TURSO_GROUP') or 'default'
        
        if not mgmt_token or not org_slug:
            print("  ❌ 缺少关键配置 (TURSO_MGMT_TOKEN 或 TURSO_ORG_SLUG)，无法自动创建。")
            if os.getenv('TURSO_AUTH_TOKEN') and not mgmt_token:
                print("  ℹ️ 检测到 TURSO_AUTH_TOKEN，但它是数据库连接令牌，不具备组织级建库权限。")
            return

        print(f'  🚀 正在利用管理权限自动配置云端资源 (Org: {org_slug})...')
        env_data = self._configure_cloud_for_user(username, mgmt_token, org_slug, group)
        self._write_profile_env(username, env_data)
        print(f'  ✅ {username} 的云资源已就绪。')

    def _create_turso_database(self, organization_slug: str, database_name: str, auth_token: str, group: str = 'default') -> dict:
        if not auth_token:
            raise ValueError('缺少 TURSO_MGMT_TOKEN，无法调用组织级数据库创建接口。')

        retrieve_url = f'https://api.turso.tech/v1/organizations/{organization_slug}/databases/{database_name}'
        list_url = f'https://api.turso.tech/v1/organizations/{organization_slug}/databases'
        headers = {'Authorization': f'Bearer {auth_token}', 'Content-Type': 'application/json'}

        # 先检查目标数据库是否已存在（单库查询，避免全量列表开销）
        retrieve_resp = requests.get(retrieve_url, headers=headers, timeout=20)
        if retrieve_resp.status_code == 200:
            payload = retrieve_resp.json() if retrieve_resp.text else {}
            existing = payload.get('database') if isinstance(payload, dict) else None
            if isinstance(existing, dict):
                return existing
            # 兼容部分响应直接返回数据库对象
            if isinstance(payload, dict):
                return payload

        url = list_url
        payload = {'name': database_name, 'group': group}
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        
        if resp.status_code == 409: # Already exists
            retrieve_resp = requests.get(retrieve_url, headers=headers, timeout=20)
            if retrieve_resp.status_code == 200:
                payload = retrieve_resp.json() if retrieve_resp.text else {}
                existing = payload.get('database') if isinstance(payload, dict) else None
                if isinstance(existing, dict):
                    return existing
                if isinstance(payload, dict):
                    return payload

            # 极端兼容：若单库查询不支持，再退回全量列表
            list_resp = requests.get(list_url, headers=headers, timeout=20)
            if list_resp.status_code == 200:
                for db in list_resp.json().get('databases', []):
                    if (db.get('Name') or db.get('name')) == database_name:
                        return db
        
        if resp.status_code not in (200, 201):
            if resp.status_code == 401:
                raise ValueError(
                    f'创建 Turso 数据库失败: 401 {resp.text}。'
                    ' 这通常表示你传入的是数据库 JWT，而不是 Turso 管理员令牌，'
                    '或者该 token 没有组织级创建权限。'
                )
            raise ValueError(f'创建 Turso 数据库失败: {resp.status_code} {resp.text}')
        
        data = resp.json()
        if 'database' not in data: raise ValueError('Turso 响应缺少 database 字段')
        return data['database']

    def _create_or_get_turso_hub_database(self, organization_slug: str, auth_token: str) -> Optional[dict]:
        """创建或获取中央 Hub 数据库信息"""
        hub_db_name = 'momo-users-hub'
        try:
            return self._create_turso_database(organization_slug, hub_db_name, auth_token)
        except: return None

    def _generate_db_auth_token(self, organization_slug: str, auth_token: str, db_name: str) -> Optional[str]:
        """生成指定数据库的认证令牌"""
        try:
            url = f'https://api.turso.tech/v1/organizations/{organization_slug}/databases/{db_name}/auth/tokens'
            headers = {'Authorization': f'Bearer {auth_token}', 'Content-Type': 'application/json'}
            resp = requests.post(url, headers=headers, json={}, timeout=20)
            if resp.status_code in (200, 201):
                data = resp.json()
                return data.get('jwt') or data.get('token')
        except: pass
        return None

    def _setup_hub_auth_token(self, organization_slug: str, auth_token: str) -> Optional[str]:
        """生成或获取 Hub 数据库的认证令牌"""
        return self._generate_db_auth_token(organization_slug, auth_token, 'momo-users-hub')

    def _is_hub_configured(self) -> bool:
        return bool(os.getenv('TURSO_HUB_DB_URL') and os.getenv('TURSO_HUB_AUTH_TOKEN'))

    def _save_hub_config_to_global_env(self, hub_url: str, hub_token: str) -> bool:
        try:
            global_env_path = os.path.join(ROOT_DIR, '.env')
            lines = []
            if os.path.exists(global_env_path):
                with open(global_env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.startswith('TURSO_HUB_DB_URL') and not line.startswith('TURSO_HUB_AUTH_TOKEN'):
                            lines.append(line.rstrip())
            lines.append(f'TURSO_HUB_DB_URL="{hub_url}"')
            lines.append(f'TURSO_HUB_AUTH_TOKEN="{hub_token}"')
            with open(global_env_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
            return True
        except: return False

    def _ensure_hub_initialized(self, org_slug: str, turso_token: str, env_lines: list) -> bool:
        if self._is_hub_configured(): return True
        hub_db = self._create_or_get_turso_hub_database(org_slug, turso_token)
        if hub_db:
            hub_hostname = hub_db.get('Hostname') or hub_db.get('hostname') or ''
            hub_url = self._normalize_turso_db_url(hub_hostname)
            hub_token = self._setup_hub_auth_token(org_slug, turso_token)
            if hub_token:
                self._save_hub_config_to_global_env(hub_url, hub_token)
                try:
                    from core import db_manager
                    db_manager.init_users_hub_tables()
                    return True
                except: return True
        return False

    def _init_local_db(self, username: str):
        db_dir = os.path.join(ROOT_DIR, 'data')
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, f'history-{username.lower()}.db')
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        cur.execute('CREATE TABLE IF NOT EXISTS ai_word_notes (voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, ielts_focus TEXT, collocations TEXT, traps TEXT, synonyms TEXT, discrimination TEXT, example_sentences TEXT, memory_aid TEXT, word_ratings TEXT, raw_full_text TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, batch_id TEXT, original_meanings TEXT, maimemo_context TEXT, it_level INTEGER DEFAULT 0, it_history TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        cur.execute('CREATE TABLE IF NOT EXISTS ai_word_iterations (id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT NOT NULL, spelling TEXT, stage TEXT, it_level INTEGER, score REAL, justification TEXT, tags TEXT, refined_content TEXT, candidate_notes TEXT, raw_response TEXT, maimemo_context TEXT, batch_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(voc_id) REFERENCES ai_word_notes(voc_id))')
        cur.execute('CREATE TABLE IF NOT EXISTS word_progress_history (id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT, familiarity_short REAL, familiarity_long REAL, review_count INTEGER, it_level INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        cur.execute('CREATE TABLE IF NOT EXISTS ai_batches (batch_id TEXT PRIMARY KEY, request_id TEXT, ai_provider TEXT, model_name TEXT, prompt_version TEXT, batch_size INTEGER, total_latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, finish_reason TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        cur.execute('CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        conn.commit()
        conn.close()

    def _confirm(self, prompt: str, default: bool = False) -> bool:
        answer = input(prompt).strip().lower()
        if not answer: return default
        return answer in ('y', 'yes')

    def _prompt_value(self, prompt: str, sensitive: bool = False, allow_skip: bool = True) -> str:
        skip_tip = " (输入 s 跳过)" if allow_skip else ""
        if sensitive:
            value = getpass.getpass(f"{prompt}{skip_tip}: ").strip()
        else:
            value = input(f"{prompt}{skip_tip}: ").strip()

        if allow_skip and value.lower() in ("s", "skip"):
            return ""
        return value

    def _maybe_validate(self, label: str, value: str, validator) -> None:
        if not value:
            return
        if not self._confirm(f"  是否立即联网校验 {label}？(Y/N, 默认 N): ", default=False):
            return

        current = value
        for attempt in range(1, self.MAX_VALIDATE_RETRIES + 1):
            result = validator(current)
            if result.get("ok"):
                print(f"  ✅ {label} 校验通过")
                return

            print(
                f"  ❌ {label} 校验失败 | category={result.get('category')} | detail={result.get('detail')}"
            )
            if attempt < self.MAX_VALIDATE_RETRIES and self._confirm("  是否重新输入并重试？(Y/N, 默认 N): ", default=False):
                current = self._prompt_value(f"  重新输入 {label}", sensitive=True, allow_skip=True)
                if not current:
                    print("  ℹ️ 已跳过，保留待校验状态。")
                    return
            else:
                print("  ℹ️ 已保留当前值，后续可通过 preflight 统一检查。")
                return

    def _print_setup_summary(self, username: str, env_data: Dict[str, str]) -> None:
        missing = []
        if not env_data.get("MOMO_TOKEN"):
            missing.append("MOMO_TOKEN")

        provider = (env_data.get("AI_PROVIDER") or "").lower()
        if provider not in ("mimo", "gemini"):
            missing.append("AI_PROVIDER")
        elif provider == "mimo" and not env_data.get("MIMO_API_KEY"):
            missing.append("MIMO_API_KEY")
        elif provider == "gemini" and not env_data.get("GEMINI_API_KEY"):
            missing.append("GEMINI_API_KEY")

        print("\n" + "-" * 45)
        print("🧾 配置摘要")
        print(f"用户: {username}")
        print(f"MOMO_TOKEN: {mask_sensitive(env_data.get('MOMO_TOKEN')) or '(未配置)'}")
        print(f"AI_PROVIDER: {env_data.get('AI_PROVIDER') or '(未配置)'}")
        if env_data.get("MIMO_API_KEY"):
            print(f"MIMO_API_KEY: {mask_sensitive(env_data.get('MIMO_API_KEY'))}")
        if env_data.get("GEMINI_API_KEY"):
            print(f"GEMINI_API_KEY: {mask_sensitive(env_data.get('GEMINI_API_KEY'))}")

        if missing:
            print(f"\n⚠️ 待配置项: {', '.join(missing)}")
        else:
            print("\n✅ 关键项已填写，可继续使用。")

        print("下一步建议:")
        print(f"  1) 运行体检: python tools/preflight_check.py --user {username}")
        print("  2) 再启动主程序: python main.py")
        print("-" * 45)

    def run_setup(self) -> str:
        """运行新用户向导 - 所有用户共享全局 Turso 数据库"""
        print("\n" + "*"*35)
        print("🌟  Momo Study Agent - 新用户初始化")
        print("*"*35)
        print("默认模式: 先保存后校验（可在每一步选择跳过）")

        username = ""
        for _ in range(3):
            username = input("1. 请输入用户名 (唯一标识，不区分大小写): ").strip().lower()
            if username:
                break
            print("❌ 用户名不能为空")
        if not username:
            raise ValueError("用户名输入失败次数过多")

        momo_token = self._prompt_value("2. 请输入墨墨 Token", sensitive=True, allow_skip=True)
        self._maybe_validate("MOMO_TOKEN", momo_token, self.validate_momo)

        print("\n3. 请选择 AI 引擎: 1) Mimo  2) Gemini  s) 跳过")
        provider = ""
        choice = input("请输入选择: ").strip().lower()
        if choice == "1":
            provider = "mimo"
        elif choice == "2":
            provider = "gemini"
        elif choice in ("s", "skip", ""):
            provider = ""
        else:
            print("  ⚠️ 无效输入，已按跳过处理。")
            provider = ""

        ai_key = ""
        if provider:
            ai_key = self._prompt_value(f"4. 请输入 {provider.upper()} API Key", sensitive=True, allow_skip=True)
            if provider == "mimo":
                self._maybe_validate("MIMO_API_KEY", ai_key, self.validate_mimo)
            else:
                self._maybe_validate("GEMINI_API_KEY", ai_key, self.validate_gemini)
        else:
            print("4. 已跳过 AI_PROVIDER，API Key 同步跳过。")

        # 步骤 5: 使用全局管理令牌为用户创建 Turso 数据库
        env_lines = [
            f'MOMO_TOKEN="{momo_token}"',
            f'AI_PROVIDER="{provider}"',
            f'{"MIMO_API_KEY" if provider == "mimo" else "GEMINI_API_KEY"}="{ai_key}"',
        ]

        # 先复用该用户现有 profile 中的数据库凭证；如果没有，再决定是创建还是手动填写
        existing_profile = self._read_profile_env(username)
        existing_db_url = existing_profile.get('TURSO_DB_URL')
        existing_db_token = existing_profile.get('TURSO_AUTH_TOKEN')
        mgmt_token = os.getenv('TURSO_MGMT_TOKEN')
        org_slug = os.getenv('TURSO_ORG_SLUG')
        group = os.getenv('TURSO_GROUP') or 'default'

        if existing_db_url and existing_db_token:
            print(f"\n  ✅ 检测到现有 Turso 数据库配置，直接复用，不再创建。")
            env_lines.extend([
                f'TURSO_DB_URL="{existing_db_url}"',
                f'TURSO_AUTH_TOKEN="{existing_db_token}"',
            ])
        elif mgmt_token and org_slug:
            print(f"\n  🚀 使用管理凭证为用户创建专属数据库...")
            try:
                db_name = f'history-{username.lower()}'
                try:
                    database = self._create_turso_database(org_slug, db_name, mgmt_token, group)
                except ValueError as create_error:
                    if 'already exists' in str(create_error).lower() or '409' in str(create_error):
                        print(f"  ℹ️ 数据库 {db_name} 已存在，尝试直接复用现有配置。")
                        database = {'Name': db_name}
                    else:
                        raise

                hostname = database.get('Hostname') or database.get('hostname') or ''
                db_url = self._normalize_turso_db_url(hostname)

                # 生成数据库专用令牌
                db_auth_token = self._generate_db_auth_token(org_slug, mgmt_token, db_name)
                if not db_auth_token:
                    db_auth_token = mgmt_token
                    print("  ⚠️  警告: 无法生成数据库专用令牌，使用管理令牌回退。")

                env_lines.extend([
                    f'TURSO_DB_NAME="{db_name}"',
                    f'TURSO_DB_HOSTNAME="{hostname}"',
                    f'TURSO_DB_URL="{db_url}"',
                    f'TURSO_AUTH_TOKEN="{db_auth_token}"',
                ])
                print(f'  ✅ Turso 云端数据库已为 {username} 就绪。')

                # 初始化 Hub
                self._ensure_hub_initialized(org_slug, mgmt_token, env_lines)

            except Exception as e:
                print(f'  ⚠️ 云端配置失败: {e}')
                print(f'  ⚠️ 用户将使用本地数据库模式')
        else:
            print(f"\n  ⚠️ 未检测到可用的 Turso 管理凭证或现有数据库配置。")
            if os.getenv('TURSO_AUTH_TOKEN') and not mgmt_token:
                print("  ℹ️ 当前只有 TURSO_AUTH_TOKEN（数据库令牌），不能用于创建数据库。")
                print("  ℹ️ 如需自动创建，请在全局 .env 中配置 TURSO_MGMT_TOKEN 和 TURSO_ORG_SLUG。")
            print(f"  ✅ 如果你已经有 history-{username.lower()}.db，请手动输入现有 Turso 数据库 URL 和 Token。")
            manual_db_url = input("  请输入现有 TURSO_DB_URL (留空则跳过): ").strip()
            if manual_db_url:
                manual_db_token = getpass.getpass("  请输入现有 TURSO_AUTH_TOKEN: ").strip()
                if manual_db_token:
                    env_lines.extend([
                        f'TURSO_DB_URL="{manual_db_url}"',
                        f'TURSO_AUTH_TOKEN="{manual_db_token}"',
                    ])

        # 记录用户邮箱到 profile，Hub 信息在主流程启动后再同步，避免初始化期循环导入
        user_email = input("6. 请输入用户邮箱 (可选): ").strip() or f"{username}@momo-local"
        env_lines.append(f'USER_EMAIL="{user_email}"')

        print("\n⚠️ 风险提醒: profile 文件为本地明文存储，请勿在不可信设备共享。")
        if not self._confirm("确认写入以上配置并创建用户？(Y/N, 默认 Y): ", default=True):
            raise KeyboardInterrupt("用户取消写入")

        # 写入用户的 .env 文件
        profile_path = os.path.join(self.profiles_dir, f"{username}.env")
        with open(profile_path, "w", encoding="utf-8") as f:
            f.write('\n'.join(env_lines) + '\n')

        self._init_local_db(username)
        current_profile = self._read_profile_env(username)
        self._print_setup_summary(username, current_profile)

        preflight = run_preflight(ROOT_DIR, username)
        if not preflight.get("ok"):
            print("\n⚠️ preflight 检测到阻断项，请先按建议修复。")

        print(f"\n✨ 用户 '{username}' 已创建成功！")
        return username

if __name__ == "__main__":
    wizard = ConfigWizard(os.path.join(ROOT_DIR, "data", "profiles"))
