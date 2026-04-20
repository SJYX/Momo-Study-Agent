"""
core/ui_manager.py: CLI 交互界面，仅负责输入输出与菜单展示。
"""
import os
import msvcrt
from typing import List


class CLIUIManager:
    """CLI 交互层：仅负责展示与输入，不承载业务逻辑。"""

    def __init__(self, logger):
        self.logger = logger
        self._menu_active = False
        self._menu_status_line = ""

    def wait_for_choice(self, valid_choices: List[str]) -> str:
        while True:
            try:
                choice = input("请输入选项序号 (或按 Ctrl+C 退出): ").strip()
                if choice in valid_choices:
                    return choice
                print(f"❌ 无效选项，请从 {valid_choices} 中选择。")
            except (KeyboardInterrupt, EOFError):
                raise KeyboardInterrupt

    def render_main_menu(self, today_count: int, future_count: int, status_line: str = "") -> None:
        print("\n" + "=" * 35)
        print("👤 用户模式选择")
        print("=" * 35)
        print(f"  1. [今日任务] 处理今日待复习 ({today_count} 个)")
        print(f"  2. [未来计划] 处理未来 7 天待学 ({future_count} 个)")
        print("  3. [智能迭代] 优化薄弱词助记")
        print("  4. [同步&退出] 保存所有数据并安全退出")
        print("-" * 35)
        if status_line:
            print(status_line)
            print("-" * 35)

    def render_future_days_menu(self) -> int:
        print("\n" + "-" * 30)
        print("📅 选择未来计划时间跨度")
        print("-" * 30)
        print("  1. 未来 1 天")
        print("  2. 未来 3 天")
        print("  3. 未来 7 天 (默认)")
        print("  4. 未来 14 天")
        print("  5. 未来 30 天")
        print("  6. 自定义天数")
        print("  0. 返回主菜单")
        print("-" * 30)

        # wait_for_choice expects a list of strings
        choice = self.wait_for_choice(["1", "2", "3", "4", "5", "6", "0"])

        mapping = {"1": 1, "2": 3, "3": 7, "4": 14, "5": 30}
        if choice in mapping:
            return mapping[choice]
        if choice == "6":
            try:
                days_str = self.ask_text("请输入查询天数 (1-100)", default="7")
                days = int(days_str)
                return max(1, min(100, days))
            except ValueError:
                print("❌ 输入无效，默认使用 7 天")
                return 7
        return 0 # 0 means go back

    def ask_confirmation(self, message: str) -> bool:
        print(f"\n❓ {message} (y/n)")
        # support enter as default 'y' if we add it to choices, but here we stick to explicit
        choice = self.wait_for_choice(["y", "n", "Y", "N"])
        return choice.lower() == "y"

    def ui_print(self, message: str, style: str = "") -> None:
        print(message)

    def ui_notice(self, title: str, message: str, border_style: str = "cyan") -> None:
        print("\n" + "=" * 10 + f" {title} " + "=" * 10)
        print(message)
        print("=" * 30)

    def ask_text(self, prompt_text: str, default: str = "") -> str:
        raw = input(f"{prompt_text}{f' (默认 {default})' if default else ''}: ").strip()
        return raw if raw else default

    def ask_secret(self, prompt_text: str) -> str:
        try:
            import getpass
            return getpass.getpass(f"{prompt_text}: ").strip()
        except Exception:
            return input(f"{prompt_text}: ").strip()

    def clear_screen(self) -> None:
        os.system("cls" if os.name == "nt" else "clear")

    def set_menu_status_line(self, message: str) -> None:
        self._menu_status_line = message or ""

    def consume_menu_status_line(self) -> str:
        msg = self._menu_status_line
        self._menu_status_line = ""
        return msg

    def is_menu_active(self) -> bool:
        return self._menu_active

    def set_menu_active(self, active: bool) -> None:
        self._menu_active = bool(active)

    def check_esc_interrupt(self):
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ord(ch) == 27:
                print("\n" + "!" * 30)
                print("检测到 Esc 键，正在中断并保存...")
                print("!" * 30)
                raise KeyboardInterrupt
            return ch
        return None

    def render_sync_progress(self, label: str, progress: dict) -> None:
        stage = progress.get("stage", "unknown")
        current = int(progress.get("current", 0))
        total = int(progress.get("total", 0))
        msg = progress.get("message", "")
        if total > 0:
            print(f"[{label}] {stage}: {current}/{total} - {msg}")
        else:
            print(f"[{label}] {stage}: {msg}")
