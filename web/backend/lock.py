"""
web/backend/lock.py: 跨平台文件排他锁 — CLI 与 Web 共享模块。

从 main.py 抽出的 acquire_process_lock / release_process_lock，
确保 CLI（python main.py）和 Web（python -m web.backend）不会同时运行。

支持锁恢复：如果锁文件残留但持有进程已死，自动清理并重新获取。
"""
import os
import sys
import atexit
import json
import time

# 模块级状态
_lock_fd = None
_lock_file = None
_lock_released = False

_PROCESS_LOCK_NAME = ".process.lock"


def _write_pid_info(lock_file: str) -> None:
    """写入 PID + 时间戳到锁文件旁边，供恢复检测使用。"""
    pid_file = lock_file + ".pid"
    try:
        info = {"pid": os.getpid(), "ts": time.time()}
        with open(pid_file, "w", encoding="utf-8") as f:
            json.dump(info, f)
    except Exception:
        pass


def _read_pid_info(lock_file: str) -> dict | None:
    """读取锁文件关联的 PID 信息。"""
    pid_file = lock_file + ".pid"
    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _remove_pid_info(lock_file: str) -> None:
    """清理 PID 文件。"""
    pid_file = lock_file + ".pid"
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except Exception:
        pass


def _is_process_alive(pid: int) -> bool:
    """跨平台检测进程是否存活。"""
    try:
        if os.name == "nt":
            # Windows: os.kill(pid, 0) 不发信号，仅检测进程存在性
            # 对于非当前进程需要用 ctypes 或 tasklist
            import subprocess
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        else:
            import signal
            os.kill(pid, 0)
            return True
    except (OSError, subprocess.SubprocessError):
        return False


def _try_recover_lock(lock_file: str) -> bool:
    """尝试恢复残留锁。如果持有进程已死，清理锁文件并返回 True。"""
    info = _read_pid_info(lock_file)
    if info and "pid" in info:
        old_pid = info["pid"]
        if not _is_process_alive(old_pid):
            # 持有进程已死，清理残留锁
            try:
                if os.path.exists(lock_file):
                    os.remove(lock_file)
                _remove_pid_info(lock_file)
                return True
            except OSError:
                pass
    return False


def acquire_process_lock(data_dir: str = None) -> None:
    """获取文件排他锁，确保系统内只有一个进程在操作数据库。

    如果锁文件残留但持有进程已死，自动恢复。

    Args:
        data_dir: 锁文件所在目录。默认使用 ``config.DATA_DIR``。

    Raises:
        SystemExit: 如果锁已被占用且持有进程仍存活。
    """
    global _lock_fd, _lock_file

    if data_dir is None:
        from config import DATA_DIR
        data_dir = DATA_DIR

    _lock_file = os.path.join(data_dir, _PROCESS_LOCK_NAME)
    os.makedirs(data_dir, exist_ok=True)

    # 第一次尝试获取锁
    if _try_acquire(_lock_file):
        _write_pid_info(_lock_file)
        atexit.register(release_process_lock)
        return

    # 锁获取失败，尝试恢复
    if _try_recover_lock(_lock_file):
        # 恢复成功，重试
        if _try_acquire(_lock_file):
            _write_pid_info(_lock_file)
            atexit.register(release_process_lock)
            return

    # 恢复失败，说明有活进程持有锁
    info = _read_pid_info(_lock_file)
    pid_hint = f" (PID: {info['pid']})" if info and "pid" in info else ""
    print(f"\n❌ [致命错误] 检测到程序已经在运行中{pid_hint}！")
    print(f"为保护数据库防冲突(WalConflict)，已拦截本次启动。")
    print(f"如确信无其他进程运行，请手动删除锁文件: {_lock_file}\n")
    sys.exit(1)


def _try_acquire(lock_file: str) -> bool:
    """尝试获取文件锁，成功返回 True。"""
    global _lock_fd
    try:
        if os.name == "nt":
            import msvcrt
            _lock_fd = os.open(lock_file, os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            msvcrt.locking(_lock_fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            _lock_fd = os.open(lock_file, os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (IOError, OSError):
        if _lock_fd is not None:
            try:
                os.close(_lock_fd)
            except Exception:
                pass
            _lock_fd = None
        return False


def release_process_lock() -> None:
    """释放锁文件（幂等，可安全多次调用）。"""
    global _lock_fd, _lock_released

    if _lock_fd is None or _lock_released:
        return

    _lock_released = True
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(_lock_fd, 0, os.SEEK_SET)
            msvcrt.locking(_lock_fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
        os.close(_lock_fd)
        if _lock_file and os.path.exists(_lock_file):
            os.remove(_lock_file)
        _remove_pid_info(_lock_file)
    except Exception:
        pass
    _lock_fd = None


# ---------------------------------------------------------------------------
# Profile 级重任务互斥锁（Web 专用）
# ---------------------------------------------------------------------------
import threading as _threading

_profile_locks: dict[str, _threading.Lock] = {}
_profile_locks_guard = _threading.Lock()
_profile_lock_holders: dict[str, str] = {}  # profile -> task_id


def acquire_profile_lock(profile_name: str, task_id: str) -> bool:
    """尝试获取 profile 级排他锁。成功返回 True，已被占用返回 False。"""
    with _profile_locks_guard:
        if profile_name in _profile_lock_holders:
            return False
        if profile_name not in _profile_locks:
            _profile_locks[profile_name] = _threading.Lock()
        lock = _profile_locks[profile_name]

    acquired = lock.acquire(blocking=False)
    if acquired:
        with _profile_locks_guard:
            _profile_lock_holders[profile_name] = task_id
    return acquired


def release_profile_lock(profile_name: str) -> None:
    """释放 profile 级排他锁（幂等）。"""
    with _profile_locks_guard:
        _profile_lock_holders.pop(profile_name, None)
        lock = _profile_locks.get(profile_name)

    if lock is not None:
        try:
            lock.release()
        except RuntimeError:
            pass  # 未被持有，忽略


def get_profile_lock_holder(profile_name: str) -> str | None:
    """查询当前持有锁的 task_id，无持有者返回 None。"""
    with _profile_locks_guard:
        return _profile_lock_holders.get(profile_name)
