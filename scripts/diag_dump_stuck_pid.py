"""一键诊断脚本：抓住"今日任务卡死后"的 Python 进程堆栈。

背景：
    process_word_list 在 ✅ 成功记录 → 进度快照阶段完成 之间静默几小时，
    asher.log 完全空白。代码本身没有阻塞点，必须看实际线程在哪一行。

用法：
    1. 先 `pip install py-spy`
    2. 触发"今日任务全部处理"，等到看到 ✅ 成功记录 ... 后再无新日志
    3. 跑 `python scripts/diag_dump_stuck_pid.py`
       脚本会自动找到 web.backend 进程并 dump 所有线程的 Python 堆栈
    4. 输出落到 logs/py_spy_dump_<timestamp>.txt

输出里我们要找的是：
    - "web-task-*" 线程当前在哪一行
    - "writer-daemon" 线程在哪
    - 有没有线程卡在某把 threading.Lock.acquire / queue.get / time.sleep
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def _find_pid() -> int | None:
    """在 Windows 上找 web.backend 主进程。"""
    try:
        result = subprocess.run(
            ["wmic", "process", "where",
             "name='python.exe' or name='pythonw.exe'",
             "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    for line in result.stdout.splitlines():
        if "web.backend" in line or "start_web" in line or "main.py" in line:
            # CommandLine ... ProcessId
            parts = line.rsplit(None, 1)
            if len(parts) == 2 and parts[1].isdigit():
                return int(parts[1])
    return None


def main() -> int:
    pid_str = sys.argv[1] if len(sys.argv) > 1 else None
    pid: int | None = int(pid_str) if pid_str and pid_str.isdigit() else _find_pid()
    if not pid:
        print("ERROR: 没找到 web.backend 进程。", file=sys.stderr)
        print("用法：python scripts/diag_dump_stuck_pid.py [<pid>]", file=sys.stderr)
        return 1

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path("logs")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"py_spy_dump_{timestamp}_pid{pid}.txt"

    print(f"[diag] 目标 PID = {pid}")
    print(f"[diag] dump 输出 -> {out_path}")
    print(f"[diag] 正在抓取所有线程堆栈（py-spy 需要管理员权限）...")

    # py-spy dump 抓单次快照，包含所有线程当前栈帧
    cmd = ["py-spy", "dump", "--pid", str(pid)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        print("ERROR: py-spy 没装。先 `pip install py-spy`", file=sys.stderr)
        return 2

    out_path.write_text(
        f"=== py-spy dump for PID {pid} at {timestamp} ===\n\n"
        + result.stdout
        + ("\n\n=== stderr ===\n" + result.stderr if result.stderr else ""),
        encoding="utf-8",
    )

    if result.returncode != 0:
        print(f"WARN: py-spy 退出码 {result.returncode}", file=sys.stderr)
        print(result.stderr[:1000], file=sys.stderr)

    print(f"[diag] 完成。打开 {out_path} 看堆栈。")
    print(f"[diag] 重点找 web-task-* 线程 — 它跑的就是 process_word_list。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
