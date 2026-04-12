import os
import sys
import glob
from typing import Optional, List

# 移除可能会导致 stdin 阻塞的强制编码重配置

class ProfileManager:
    def __init__(self, profiles_dir):
        self.profiles_dir = profiles_dir
        os.makedirs(self.profiles_dir, exist_ok=True)

    def list_profiles(self):
        """扫描 profiles 目录，返回用户名列表。"""
        files = glob.glob(os.path.join(self.profiles_dir, "*.env"))
        return [os.path.basename(f).replace(".env", "") for f in files]

    def pick_profile(self) -> Optional[str]:
        """展示菜单供用户选择、创建或退出。"""
        import msvcrt
        while True:
            profiles = self.list_profiles()
            print("\n" + "="*30)
            print("👤  Momo Study Agent - 用户选择")
            print("="*30)
            
            for i, p in enumerate(profiles, 1):
                print(f"  {i}. {p}")
            
            create_idx = len(profiles) + 1
            print(f"  {create_idx}. [创建新用户]")
            print("-" * 30)
            # 回退到标准 input 以确保跨终端兼容性 (避免 msvcrt 与 input() 冲突)
            try:
                choice = input(f"请输入序号 (1-{create_idx})，或按 Ctrl+C 退出: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n[Exit] 用户取消选择，程序退出。")
                sys.exit(0)
            if not choice:
                continue

            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(profiles):
                    username = profiles[idx-1]
                    from core.config_wizard import ConfigWizard
                    wizard = ConfigWizard(self.profiles_dir)
                    wizard.ensure_cloud_database_for_profile(username)
                    return username
                elif idx == create_idx:
                    from core.config_wizard import ConfigWizard
                    wizard = ConfigWizard(self.profiles_dir)
                    return wizard.run_setup()
            
            print("❌ 无效的选择，请重新输入。")

def get_active_profile(profiles_dir):
    """助手函数：获取当前活跃用户。"""
    pm = ProfileManager(profiles_dir)
    return pm.pick_profile()
