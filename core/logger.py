import logging
import os
import sys

def setup_logger(username: str, log_dir: str = "logs"):
    """
    配置全局日志系统。
    - username: 当前运行的用户，用于命名日志文件。
    - log_dir: 日志存储目录。
    """
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, f"{username}.log")
    
    # 获取根日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 避免重复添加 Handler (防止多次初始化)
    if logger.handlers:
        return logger

    # 定义统一的格式：时间 - 级别 - 内容
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # Handler 1: 文件输出 (增量追加)
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Handler 2: 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# 便捷获取 logger 的函数
def get_logger():
    return logging.getLogger()
