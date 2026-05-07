#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试性能监控功能
"""
import sys
sys.path.insert(0, '.')

from core.logger import setup_logger, log_performance
import time

def test_performance_monitoring():
    logger = setup_logger("perf_test", use_structured=True)
    logger.set_context(session_id="perf_test_123")

    @log_performance(logger)
    def slow_function(delay=0.1):
        """模拟一个耗时函数"""
        time.sleep(delay)
        return "completed"

    @log_performance(logger)
    def fast_function():
        """模拟一个快速函数"""
        return sum(range(1000))

    @log_performance(logger)
    def error_function():
        """模拟一个会出错的函数"""
        raise ValueError("测试错误")

    # 测试正常函数
    result1 = slow_function(0.2)
    result2 = fast_function()

    # 测试错误函数
    try:
        error_function()
    except ValueError:
        pass

    print("性能监控测试完成，请检查日志文件")

if __name__ == "__main__":
    test_performance_monitoring()