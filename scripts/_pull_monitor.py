"""Standalone subprocess to monitor libsql initial pull progress.

Run by _connect_embedded_replica() as a separate process (has its own GIL,
so it runs even while the main process is blocked in libsql.connect()).

Usage:
    python scripts/_pull_monitor.py <db_path> <total_bytes> <parent_pid>

Output (to stdout, every 2 seconds):
    [下载进度] 2.5 MB
    [下载进度] 2.5 MB / 50.0 MB (5%)
"""
from __future__ import annotations

import os
import platform
import sys
import time


def _is_parent_alive(parent_pid: int) -> bool:
    """Check if parent process is alive, safely on all platforms.

    On Windows, os.kill(pid, 0) can raise SystemError (CPython bug) with
    certain process states (WinError 87). Use ctypes OpenProcess instead.
    """
    if platform.system() != "Windows":
        try:
            os.kill(parent_pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    # Windows: use OpenProcess(PROCESS_QUERY_INFORMATION, FALSE, pid)
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, parent_pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


def main() -> None:
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <db_path> <total_bytes> <parent_pid>", file=sys.stderr)
        sys.exit(1)

    db_path = sys.argv[1]
    total_bytes = int(sys.argv[2])
    parent_pid = int(sys.argv[3])

    last_size = 0
    no_progress_count = 0

    while True:
        # Check parent process is alive
        if not _is_parent_alive(parent_pid):
            break

        time.sleep(2)

        try:
            if not os.path.exists(db_path):
                continue
            size = os.path.getsize(db_path)
        except OSError:
            continue

        if size <= last_size:
            no_progress_count += 1
            if no_progress_count > 30:
                # No progress for 60s, probably done or stuck
                break
            continue

        no_progress_count = 0
        last_size = size
        size_mb = size / 1024 / 1024

        if total_bytes > 0:
            total_mb = total_bytes / 1024 / 1024
            pct = min(int(size * 100 / total_bytes), 100)
            print(f"[下载进度] {size_mb:.1f} MB / {total_mb:.1f} MB ({pct}%)", flush=True)
        else:
            print(f"[下载进度] {size_mb:.1f} MB", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit, OSError):
        pass
