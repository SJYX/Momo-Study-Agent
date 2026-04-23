"""
web/backend/lock.py: 跨平台文件排他锁 — CLI 与 Web 共享模块。

从 main.py 抽出的 acquire_process_lock / release_process_lock，
确保 CLI（python main.py）和 Web（python -m web.backend）不会同时运行。
"""
import os
import sys
import atexit
import threading

# 模块级状态
_lock_fd = None
_lock_file = None
_lock_released = False

_PROCESS_LOCK_NAME = ".process.lock"


def acquire_process_lock(data_dir: str = None) -> None:
    """获取文件排他锁，确保系统内只有一个进程在操作数据库。

    Args:
        data_dir: 锁文件所在目录。默认使用 ``config.DATA_DIR``。

    Raises:
        SystemExit: 如果锁已被占用。
    """
    global _lock_fd, _lock_file

    if data_dir is None:
        from config import DATA_DIR
        data_dir = DATA_DIR

    _lock_file = os.path.join(data_dir, _PROCESS_LOCK_NAME)
    os.makedirs(data_dir, exist_ok=True)

    try:
        if os.name == "nt":
            import msvcrt
            _lock_fd = os.open(_lock_file, os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            msvcrt.locking(_lock_fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            _lock_fd = os.open(_lock_file, os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        print(f"\n❌ [致命错误] 检测到程序已经在运行中！")
        print(f"为保护数据库防冲突(WalConflict)，已拦截本次启动。")
        print(f"如确信无其他进程运行，请手动删除锁文件: {_lock_file}\n")
        sys.exit(1)

    # 注册退出钩子，确保进程死亡时释放锁
    atexit.register(release_process_lock)


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
    except Exception:
        pass
    _lock_fd = None