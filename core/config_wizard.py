import os
import sys
import requests
import json
from typing import Optional, Tuple

# 注入根目录以便导入
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from core.maimemo_api import MaiMemoAPI

# 强制 UTF-8 编码避免 Windows 终端乱码
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

class ConfigWizard:
    def __init__(self, profiles_dir: str):
        self.profiles_dir = profiles_dir
        os.makedirs(self.profiles_dir, exist_ok=True)

    def validate_momo(self, token: str) -> bool:
        """联网验证墨墨 Token"""
        print("  正在验证墨墨 Token...")
        api = MaiMemoAPI(token)
        # 尝试拉取一个小数据，如果 401 会由 MaiMemoAPI 打印错误
        res = api.get_today_items(limit=1)
        return res is not None and res.get("success") is True

    def validate_mimo(self, api_key: str) -> bool:
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
                return True
            else:
                print(f"  ❌ Mimo API 报错: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"  ❌ Mimo 网络请求失败: {e}")
            return False

    def validate_gemini(self, api_key: str) -> bool:
        """联网验证 Gemini API Key"""
        print("  正在验证 Gemini API Key...")
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            client.models.generate_content(
                model="gemini-2.0-flash",
                contents="ping"
            )
            return True
        except Exception as e:
            print(f"  ❌ Gemini API 验证失败: {e}")
            return False

    def run_setup(self) -> str:
        """执行完整的设置向导，返回成功创建的用户名"""
        print("\n" + "*"*30)
        print("🌟  Momo Study Agent - 新用户初始化向导")
        print("*"*30)

        username = input("1. 请输入用户名 (唯一标识，如 Ashi): ").strip()
        while not username:
            username = input("❌ 用户名不能为空，请重新输入: ").strip()

        # 墨墨 Token 引导
        momo_token = input("2. 请输入墨墨 Access Token (获取地址: https://open.maimemo.com): ").strip()
        while not self.validate_momo(momo_token):
            momo_token = input("❌ 验证失败，请重新检查并输入正确的墨墨 Token: ").strip()
        print("  ✅ 墨墨验证成功！")

        # AI 提供商选择
        print("\n3. 请选择 AI 引擎:")
        print("   1: 小米 Mimo (mimo-v2-flash)")
        print("   2: Google Gemini (gemini-2.0-flash)")
        ai_choice = input("请输入选项 (1/2): ").strip()
        
        provider = "mimo" if ai_choice == "1" else "gemini"
        ai_key = ""
        
        if provider == "mimo":
            ai_key = input("4. 请输入 Mimo API Key (获取地址: https://api.xiaomimimo.com): ").strip()
            while not self.validate_mimo(ai_key):
                ai_key = input("❌ 验证失败，请重新检查并输入正确的 Mimo Key: ").strip()
        else:
            ai_key = input("4. 请输入 Gemini API Key (获取地址: https://aistudio.google.com): ").strip()
            while not self.validate_gemini(ai_key):
                ai_key = input("❌ 验证失败，请重新检查并输入正确的 Gemini Key: ").strip()
        print(f"  ✅ {provider.capitalize()} 验证成功！")

        # 保存配置
        env_content = f"""# Momo Study Agent - User Config for {username}
MOMO_TOKEN="{momo_token}"
AI_PROVIDER="{provider}"
{"MIMO_API_KEY" if provider == "mimo" else "GEMINI_API_KEY"}="{ai_key}"
"""
        env_path = os.path.join(self.profiles_dir, f"{username}.env")
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(env_content)
        
        print(f"\n✨ [Success] 账号 '{username}' 已创建成功并验证！")
        return username

if __name__ == "__main__":
    # 单元测试
    wizard = ConfigWizard(os.path.join(ROOT_DIR, "data", "profiles"))
    # wizard.run_setup()
