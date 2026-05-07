#!/usr/bin/env python3
"""
测试异步日志功能
"""
import sys
import os
import time
import threading

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import setup_logger

def test_async_logging():
    """测试异步日志功能"""
    print("=== 测试异步日志功能 ===")

    # 设置异步日志 - 只调用一次
    logger = setup_logger("async_test", use_async=True)

    def log_worker(worker_id):
        """模拟并发日志写入"""
        for i in range(10):
            logger.info(f"Worker {worker_id} - Message {i}")
            time.sleep(0.01)  # 模拟一些工作

    # 启动多个线程并发写入日志
    threads = []
    for i in range(5):
        t = threading.Thread(target=log_worker, args=(i,))
        threads.append(t)
        t.start()

    # 等待所有线程完成
    for t in threads:
        t.join()

    logger.info("所有异步日志写入完成")

    # 等待异步队列处理完成
    time.sleep(1)

    print("异步日志测试完成，请检查 logs/async_test.log 文件")

if __name__ == "__main__":
    test_async_logging()