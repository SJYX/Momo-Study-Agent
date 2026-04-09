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
            print(f"提示: 请输入序号 (1-{create_idx})，或按 [Esc] 键直接退出程序")

            # 监听键盘输入
            input_str = ""
            while True:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ord(ch) == 27:  # Esc
                        print("\n[Exit] 用户取消选择，程序退出。")
                        sys.exit(0)
                    elif ch == b'\r':  # Enter
                        print() # 换行
                        break
                    elif ch.isdigit():
                        digit = ch.decode('utf-8')
                        input_str += digit
                        print(digit, end='', flush=True)
                    elif ord(ch) == 8: # Backspace
                        if input_str:
                            input_str = input_str[:-1]
                            print('\b \b', end='', flush=True)

            choice = input_str.strip()
            if not choice:
                continue

            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(profiles):
                    return profiles[idx-1]
                elif idx == create_idx:
                    from core.config_wizard import ConfigWizard
                    wizard = ConfigWizard(self.profiles_dir)
                    return wizard.run_setup()
            
            print("❌ 无效的选择，请重新输入。")

def get_active_profile(profiles_dir):
    """助手函数：获取当前活跃用户。"""
    pm = ProfileManager(profiles_dir)
    return pm.select_profile()
