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
import sys
import time


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
        try:
            os.kill(parent_pid, 0)
        except (OSError, ProcessLookupError):
            # Parent exited
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
