"""
web/backend/__main__.py: python -m web.backend 入口 — 取锁 → uvicorn。

用法：
    python -m web.backend
    python -m web.backend --user asher
    python -m web.backend --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import argparse
import os
import sys
import io
import platform
import threading
import time
import webbrowser

# Windows 控制台 UTF-8 编码修复
if platform.system() == "Windows":
    if hasattr(sys.stdout, "buffer") and sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer") and sys.stderr.encoding != "utf-8":
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description="MOMO Study Agent — Web 后端")
    parser.add_argument("--user", default=None, help="指定用户（覆盖 MOMO_USER 环境变量）")
    parser.add_argument("--host", default="127.0.0.1", help="绑定地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8765, help="端口（默认 8765）")
    parser.add_argument("--env", choices=["development", "staging", "production"],
                        default=os.getenv("MOMO_ENV", "development"))
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument("--open-browser", action="store_true", help="启动后自动打开浏览器")
    args = parser.parse_args()

    # 1. 设置用户
    if args.user:
        os.environ["MOMO_USER"] = args.user

    # 注意：Web 模式默认不做交互式选用户。
    # 用户应在 Gateway 页面中选择/创建 profile。

    # 2. 获取进程锁（与 CLI 互斥）
    from web.backend.lock import acquire_process_lock
    acquire_process_lock()

    print(f"\n🌐 MOMO Study Agent Web 后端")
    print(f"   用户: {os.getenv('MOMO_USER', 'default')} (可在 Gateway 切换)")
    print(f"   地址: http://{args.host}:{args.port}")
    print(f"   健康检查: http://{args.host}:{args.port}/api/health")
    print(f"   按 Ctrl+C 停止\n")

    if args.open_browser:
        def _open():
            time.sleep(1.0)
            try:
                webbrowser.open(f"http://{args.host}:{args.port}")
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    # 3. 启动 uvicorn
    import uvicorn
    uvicorn.run(
        "web.backend.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        workers=1,  # 禁止多 worker（进程锁限制）
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
