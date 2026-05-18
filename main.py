import os
import sys
import argparse
import runpy
from pathlib import Path

# ==============================================================================
# EARLY BOOTSTRAP: 用户配置热加载 (彻底消灭 subprocess 多进程套娃)
# ==============================================================================
# 必须在导入任何业务模块（尤其是 config）之前执行
if __name__ == "__main__":
    _user_from_env = bool(os.getenv("MOMO_USER"))
    if not _user_from_env and sys.stdin.isatty():
        import config
        # 如果当前是默认用户且处于交互模式，触发选择菜单
        if getattr(config, "ACTIVE_USER", "default") == "default":
            try:
                selected_user = config.pm.normalize_username(config.pm.pick_profile() or "")
                if not selected_user:
                    print("\n[Exit] 未选择有效用户，已退出。")
                    sys.exit(0)

                # 1. 直接在当前进程注入环境变量
                os.environ["MOMO_USER"] = selected_user

                # 2. 热重载 config 模块，使后续导包拿到真实用户配置
                import importlib
                importlib.reload(config)
            except (KeyboardInterrupt, EOFError):
                print("\n[Exit] 用户取消选择。")
                sys.exit(0)

# ==============================================================================
# 常规导包开始（此时 config 已经是最终用户的真实配置）
# ==============================================================================
# 业务编排已抽到 core/study_flow.py，main.py 只保留入口编排。
from core.study_flow import StudyFlowManager
from web.backend.lock import acquire_process_lock


def run(environment=None, config_file=None):
    # 【核心防御】在初始化任何数据库连接前获取进程锁
    acquire_process_lock()

    manager = None
    try:
        manager = StudyFlowManager(environment=environment, config_file=config_file)
        manager.run()
    except KeyboardInterrupt:
        if manager and getattr(manager, "logger", None):
            manager.logger.info("用户手动退出", module="main")
    except Exception as e:
        if manager and getattr(manager, "logger", None):
            manager.logger.error(f"意外崩溃: {e}", exc_info=True, module="main")
        raise
    finally:
        if manager:
            manager.shutdown()


def web_main():
    """CLI 子命令入口：momo web ..."""
    project_root = Path(__file__).resolve().parent
    script_path = project_root / "scripts" / "start_web.py"
    runpy.run_path(str(script_path), run_name="__main__")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "web":
        # 支持：momo web [args...]
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        web_main()
        return

    parser = argparse.ArgumentParser(description="墨墨背单词AI助记系统")
    parser.add_argument(
        "--env",
        choices=["development", "staging", "production"],
        default=os.getenv("MOMO_ENV", "development"),
    )
    parser.add_argument("--config", default=os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml"))
    args = parser.parse_args()

    # 执行主程序
    run(environment=args.env, config_file=args.config)


if __name__ == "__main__":
    main()
