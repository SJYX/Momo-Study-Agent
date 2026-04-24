"""
scripts/start_web.py: 一键启动 Web UI（开发 / 生产模式）。

用法：
    # 开发模式（后端 + 前端 dev server 并行，Ctrl+C 同时关闭）
    python scripts/start_web.py --dev

    # 生产模式（自动构建前端 → FastAPI 托管静态文件）
    python scripts/start_web.py

    # 生产模式（跳过构建，假设 dist 已存在）
    python scripts/start_web.py --skip-build

    # 指定用户
    python scripts/start_web.py --user asher
"""
from __future__ import annotations

import argparse
import os
import platform
import signal
import socket
import subprocess
import sys
import io
import time
import webbrowser
from pathlib import Path

# Windows 控制台 UTF-8 编码修复
if platform.system() == "Windows":
    if hasattr(sys.stdout, "buffer") and sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer") and sys.stderr.encoding != "utf-8":
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent  # 项目根目录
FRONTEND_DIR = ROOT / "web" / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
PROFILES_DIR = ROOT / "data" / "profiles"
LAST_WEB_USER_FILE = ROOT / "data" / ".last_web_user"


def _pick_user() -> str | None:
    """列出已有 profile，让用户选择。仅返回 .env 文件名（不含扩展名）。"""
    if not PROFILES_DIR.is_dir():
        return None
    profiles = sorted(
        f.stem for f in PROFILES_DIR.glob("*.env")
        if f.stem not in ("default",) and not f.stem.startswith(".")
    )
    if not profiles:
        return None
    if len(profiles) == 1:
        print(f"👤 自动选择唯一用户: {profiles[0]}")
        return profiles[0]
    print("\n👤 检测到多个用户，请选择：")
    for i, name in enumerate(profiles, 1):
        print(f"  {i}. {name}")
    while True:
        try:
            raw = input(f"输入编号 [1-{len(profiles)}]: ").strip()
        except (KeyboardInterrupt, EOFError):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(profiles):
            selected = profiles[int(raw) - 1]
            print(f"   -> 已选择: {selected}\n")
            return selected
        print("   无效输入，请重试。")


def _load_last_user() -> str | None:
    try:
        if LAST_WEB_USER_FILE.is_file():
            user = LAST_WEB_USER_FILE.read_text(encoding="utf-8").strip()
            return user or None
    except Exception:
        return None
    return None


def _save_last_user(user: str | None) -> None:
    if not user:
        return
    try:
        LAST_WEB_USER_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_WEB_USER_FILE.write_text(user.strip(), encoding="utf-8")
    except Exception:
        pass


def _is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _pick_available_port(host: str, preferred_port: int, max_tries: int = 20) -> int:
    if _is_port_available(host, preferred_port):
        return preferred_port
    for p in range(preferred_port + 1, preferred_port + 1 + max_tries):
        if _is_port_available(host, p):
            print(f"⚠️ 端口 {preferred_port} 被占用，自动改用 {p}")
            return p
    raise RuntimeError(f"无法找到可用端口（起始 {preferred_port}）")


def _find_npm() -> str:
    """查找 npm 可执行文件（Windows 下可能是 npm.cmd）。"""
    if platform.system() == "Windows":
        # 优先 npm.cmd，否则 npm
        for cmd in ("npm.cmd", "npm"):
            try:
                subprocess.run([cmd, "--version"], capture_output=True, check=True)
                return cmd
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
    return "npm"


def _src_mtime() -> float:
    """获取前端 src/ 下最新修改时间。"""
    src = FRONTEND_DIR / "src"
    if not src.is_dir():
        return 0.0
    latest = 0.0
    for f in src.rglob("*"):
        if f.is_file():
            latest = max(latest, f.stat().st_mtime)
    return latest


def _dist_mtime() -> float:
    """获取 dist/ 下 index.html 的修改时间。"""
    idx = DIST_DIR / "index.html"
    return idx.stat().st_mtime if idx.is_file() else 0.0


def _need_build() -> bool:
    """判断是否需要重新构建前端。"""
    if not DIST_DIR.is_dir():
        return True
    # dist 比 src 旧 → 需要重建
    return _dist_mtime() < _src_mtime()


def _build_frontend(npm: str) -> None:
    """构建前端生产包。"""
    print("📦 构建前端...")
    subprocess.run([npm, "run", "build"], cwd=str(FRONTEND_DIR), check=True)
    print("✅ 前端已构建到 web/frontend/dist/")


def _run_production(args: argparse.Namespace) -> None:
    """生产模式：可选构建 → 受控启动 FastAPI（支持 Ctrl+C 收敛关闭）。"""
    npm = _find_npm()

    # 构建前端（除非 --skip-build）
    if not args.skip_build and _need_build():
        _build_frontend(npm)
    elif not args.skip_build:
        print("📦 前端 dist/ 已是最新，跳过构建。")

    # 受控启动后端（避免 execvp 导致 Ctrl+C 在某些场景不收敛）
    print(f"\n🌐 启动 Web 后端 (生产模式)...")
    cmd = [sys.executable, "-m", "web.backend"]
    if args.user:
        cmd.extend(["--user", args.user])
    cmd.extend(["--host", args.host, "--port", str(args.port)])
    if args.open:
        cmd.append("--open-browser")

    proc = subprocess.Popen(cmd, cwd=str(ROOT))

    def _cleanup(*_):
        print("\n\n🛑 正在关闭后端服务...")
        try:
            if platform.system() == "Windows":
                proc.terminate()
            else:
                proc.send_signal(signal.SIGINT)
        except OSError:
            pass

        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            print("⚠️ 后端未在超时内退出，执行强制关闭")
            proc.kill()
            proc.wait(timeout=3)

        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    if platform.system() != "Windows":
        signal.signal(signal.SIGTERM, _cleanup)

    try:
        while True:
            ret = proc.poll()
            if ret is not None:
                # 子进程自己退出，向上透传退出码
                sys.exit(ret)
            time.sleep(0.5)
    except KeyboardInterrupt:
        _cleanup()


def _run_dev(args: argparse.Namespace) -> None:
    """开发模式：并行启动后端 + 前端 dev server。"""
    npm = _find_npm()
    procs: list[subprocess.Popen] = []

    def _cleanup(*_):
        print("\n\n🛑 正在关闭开发服务器...")
        for p in procs:
            try:
                if platform.system() == "Windows":
                    p.terminate()
                else:
                    p.send_signal(signal.SIGINT)
            except OSError:
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    if platform.system() != "Windows":
        signal.signal(signal.SIGTERM, _cleanup)

    # 1. 启动后端
    backend_cmd = [sys.executable, "-m", "web.backend", "--reload"]
    if args.user:
        backend_cmd.extend(["--user", args.user])
    backend_cmd.extend(["--host", args.host, "--port", str(args.port)])

    print(f"🚀 后端启动中: http://{args.host}:{args.port}")
    backend_proc = subprocess.Popen(backend_cmd, cwd=str(ROOT))
    procs.append(backend_proc)

    # 2. 启动前端 dev server
    frontend_cmd = [npm, "run", "dev", "--", "--host", args.frontend_host, "--port", str(args.frontend_port)]
    frontend_host = args.frontend_host
    frontend_port = args.frontend_port
    env = os.environ.copy()
    env["VITE_API_BASE"] = f"http://{args.host}:{args.port}"

    print(f"🎨 前端启动中: http://{frontend_host}:{frontend_port}")
    frontend_proc = subprocess.Popen(
        frontend_cmd,
        cwd=str(FRONTEND_DIR),
        env=env,
    )
    procs.append(frontend_proc)

    print(f"\n✅ 开发模式已就绪：")
    print(f"   后端 API:  http://{args.host}:{args.port}")
    print(f"   前端 Dev:  http://{frontend_host}:{frontend_port}")
    print(f"   按 Ctrl+C 同时关闭\n")

    if args.open:
        try:
            webbrowser.open(f"http://{args.frontend_host}:{args.frontend_port}")
        except Exception:
            pass

    # 等待任一进程退出
    try:
        while True:
            for p in procs:
                ret = p.poll()
                if ret is not None:
                    print(f"\n⚠️  子进程退出 (code={ret})，正在关闭...")
                    _cleanup()
            time.sleep(0.5)
    except KeyboardInterrupt:
        _cleanup()


def main():
    parser = argparse.ArgumentParser(description="MOMO Study Agent — 一键启动 Web UI")
    parser.add_argument("--user", default=None, help="指定用户（省略则交互选择或自动检测）")
    parser.add_argument("--host", default="127.0.0.1", help="后端绑定地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8765, help="后端端口（默认 8765）")
    parser.add_argument("--dev", action="store_true", help="开发模式（后端 + 前端 dev server 并行）")
    parser.add_argument("--skip-build", action="store_true", help="生产模式跳过前端构建")
    parser.add_argument("--frontend-host", default="localhost", help="前端 dev server 地址（默认 localhost）")
    parser.add_argument("--frontend-port", type=int, default=5173, help="前端 dev server 端口（默认 5173）")
    parser.add_argument("--open", dest="open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--no-open", dest="open", action="store_false", help="启动后不自动打开浏览器")
    parser.set_defaults(open=True)
    args = parser.parse_args()

    args.port = _pick_available_port(args.host, args.port)
    if args.dev:
        args.frontend_port = _pick_available_port(args.frontend_host, args.frontend_port)

    # 用户选择：--user > MOMO_USER > 上次使用用户 > 交互选择
    user = args.user or os.getenv("MOMO_USER") or _load_last_user()
    if not user:
        user = _pick_user()
    if user:
        args.user = user
        os.environ["MOMO_USER"] = user
        _save_last_user(user)

    if args.dev:
        _run_dev(args)
    else:
        _run_production(args)


if __name__ == "__main__":
    main()
