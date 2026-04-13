import os
import sys
import glob
import hashlib
from typing import Optional, List

# 移除可能会导致 stdin 阻塞的强制编码重配置

class ProfileManager:
    def __init__(self, profiles_dir):
        self.profiles_dir = profiles_dir
        os.makedirs(self.profiles_dir, exist_ok=True)

    def _hash_fingerprint(self, raw: str) -> str:
        return hashlib.sha256((raw or "unknown").encode("utf-8")).hexdigest()[:12]

    def _local_db_paths(self, username: str):
        base_dir = os.path.dirname(self.profiles_dir)
        local_db = os.path.join(base_dir, f"history-{username.lower()}.db")
        local_test_db = os.path.join(base_dir, f"test-{username.lower()}.db")
        marker_dir = os.path.join(base_dir, "db_init_markers")
        local_db_marker = os.path.join(
            marker_dir,
            f"main_{self._hash_fingerprint(f'local:{os.path.abspath(local_db)}')}_initialized.flag",
        )
        local_test_marker = os.path.join(
            marker_dir,
            f"test_{self._hash_fingerprint(f'local:{os.path.abspath(local_test_db)}')}_initialized.flag",
        )
        return local_db, local_test_db, local_db_marker, local_test_marker

    def delete_local_profile(self, username: str) -> bool:
        """删除本地用户数据，但不触碰云端数据库。"""
        env_path = os.path.join(self.profiles_dir, f"{username}.env")
        local_db, local_test_db, local_db_marker, local_test_marker = self._local_db_paths(username)

        removed_any = False
        for path in [env_path, local_db, local_test_db, local_db_marker, local_test_marker]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                    removed_any = True
                except OSError:
                    pass

        return removed_any

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
            if profiles:
                print(f"  {create_idx + 1}. [删除本地用户]")
            print("-" * 30)
            # 回退到标准 input 以确保跨终端兼容性 (避免 msvcrt 与 input() 冲突)
            try:
                max_choice = create_idx + 1 if profiles else create_idx
                choice = input(f"请输入序号 (1-{max_choice})，或按 Ctrl+C 退出: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n[Exit] 用户取消选择，程序退出。")
                sys.exit(0)
            if not choice:
                continue

            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(profiles):
                    username = profiles[idx-1]
                    return username
                elif idx == create_idx:
                    from core.config_wizard import ConfigWizard
                    wizard = ConfigWizard(self.profiles_dir)
                    return wizard.run_setup()
                elif idx == create_idx + 1 and profiles:
                    print("\n" + "="*30)
                    print("🗑️  删除本地用户")
                    print("="*30)
                    for i, p in enumerate(profiles, 1):
                        print(f"  {i}. {p}")
                    try:
                        del_choice = input(f"请输入要删除的用户序号 (1-{len(profiles)})，或直接回车取消: ").strip()
                    except (KeyboardInterrupt, EOFError):
                        print("\n[Exit] 用户取消删除。")
                        continue
                    if not del_choice:
                        continue
                    if not del_choice.isdigit() or not (1 <= int(del_choice) <= len(profiles)):
                        print("❌ 无效的选择，请重新输入。")
                        continue
                    target = profiles[int(del_choice) - 1]
                    confirm = input(f"确认删除本地用户 {target}？这只会删除本地 profile 和 SQLite 文件，不会删除云端数据库。(Y/N): ").strip().lower()
                    if confirm in ('y', 'yes'):
                        if self.delete_local_profile(target):
                            print(f"✅ 已删除本地用户 {target}。")
                        else:
                            print(f"⚠️ 未找到可删除的本地文件：{target}")
                    else:
                        print("已取消删除。")
                    continue
            
            print("❌ 无效的选择，请重新输入。")

def get_active_profile(profiles_dir):
    """助手函数：获取当前活跃用户。"""
    pm = ProfileManager(profiles_dir)
    return pm.pick_profile()
