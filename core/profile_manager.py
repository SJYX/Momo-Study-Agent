import os
import sys
import glob

# 强制 UTF-8 编码避免 Windows 终端乱码
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

class ProfileManager:
    def __init__(self, profiles_dir):
        self.profiles_dir = profiles_dir
        os.makedirs(self.profiles_dir, exist_ok=True)

    def list_profiles(self):
        """扫描 profiles 目录，返回用户名列表。"""
        files = glob.glob(os.path.join(self.profiles_dir, "*.env"))
        return [os.path.basename(f).replace(".env", "") for f in files]

    def select_profile(self):
        """交互式选择用户 Profile。"""
        profiles = self.list_profiles()
        
        print("\n" + "="*30)
        print("👤  Momo Study Agent - 用户选择")
        print("="*30)
        
        if not profiles:
            print("  [Note] 未发现已有用户。")
            return "NEW_USER"

        for i, username in enumerate(profiles, 1):
            print(f"  {i}. {username}")
        print(f"  {len(profiles)+1}. [创建新用户]")
        
        try:
            choice = input(f"\n请选择用户序号 (1-{len(profiles)+1}): ").strip()
            if not choice:
                # 默认选第一个
                return profiles[0]
            
            idx = int(choice)
            if 1 <= idx <= len(profiles):
                return profiles[idx-1]
            elif idx == len(profiles) + 1:
                return "NEW_USER"
            else:
                print("❌ 无效选择，请重试。")
                return self.select_profile()
        except ValueError:
            print("❌ 请输入数字。")
            return self.select_profile()

def get_active_profile(profiles_dir):
    """助手函数：获取当前活跃用户。"""
    pm = ProfileManager(profiles_dir)
    return pm.select_profile()
