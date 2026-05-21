"""复现脚本：直接调起 web.backend 子进程并捕获完整输出 + 退出码 + 信号。
不经过 start_web.py 包装，避免父进程 SIGINT 处理掩盖真正的崩溃信号。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STDOUT_PATH = ROOT / "debug_stdout.log"
STDERR_PATH = ROOT / "debug_stderr.log"


def main() -> None:
    env = os.environ.copy()
    env["MOMO_USER"] = "asher"
    env["RUST_BACKTRACE"] = "full"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONFAULTHANDLER"] = "1"

    cmd = [sys.executable, "-X", "faulthandler", "-u", "-m", "web.backend",
           "--user", "asher", "--host", "127.0.0.1", "--port", "8765"]
    print(f"启动: {' '.join(cmd)}")
    print(f"stdout -> {STDOUT_PATH}")
    print(f"stderr -> {STDERR_PATH}")

    with open(STDOUT_PATH, "wb") as fout, open(STDERR_PATH, "wb") as ferr:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=fout,
            stderr=ferr,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        print(f"PID={proc.pid}")

        # 等待 listening 就绪
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                import socket
                s = socket.create_connection(("127.0.0.1", 8765), timeout=0.5)
                s.close()
                print("[debug] 后端已就绪")
                break
            except OSError:
                time.sleep(0.5)
        else:
            print("[debug] 等待 60s 仍未就绪")

        if proc.poll() is not None:
            print(f"[debug] 后端在准备就绪前已退出 exit={proc.returncode}")
            return

        # 触发 profile init：调用 PUT /api/users/active?username=asher
        # 这条端点会 _context_manager.get('asher') → _warmup_sync → libsql.connect
        import urllib.request
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8765/api/users/active?username=asher",
                method="PUT",
                headers={"X-Momo-Profile": "asher", "Content-Length": "0"},
                data=b"",
            )
            print(f"[debug] 发送 PUT /api/users/active?username=asher ...")
            with urllib.request.urlopen(req, timeout=180) as resp:
                print(f"[debug] PUT /api/users/active -> {resp.status}")
                print(f"[debug] body = {resp.read()[:500]!r}")
        except Exception as e:
            print(f"[debug] PUT /api/users/active -> {type(e).__name__}: {e}")

        # 等待 60 秒看是否会闪退
        for i in range(60):
            time.sleep(1)
            ret = proc.poll()
            if ret is not None:
                print(f"[debug] 后端在第 {i+1}s 退出，exit code = {ret} (0x{ret & 0xFFFFFFFF:08X})")
                return
        print("[debug] 60s 内未退出，主动 terminate")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"[debug] 最终 exit code = {proc.returncode}")


if __name__ == "__main__":
    main()
