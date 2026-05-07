#!/usr/bin/env python3
"""
测试日志统计功能
"""
import sys
import os
import time
import random

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import setup_logger

def test_log_statistics():
    """测试日志统计功能"""
    print("=== 测试日志统计功能 ===")

    # 设置启用统计的日志器
    logger = setup_logger("stats_test", enable_stats=True)

    # 模拟各种类型的日志
    log_types = [
        ("info", "用户信息处理完成"),
        ("debug", "调试信息：变量值检查"),
        ("warning", "警告：配置参数缺失"),
        ("error", "错误：数据库连接失败"),
        ("error", "错误：API调用超时"),
        ("error", "错误：网络连接错误"),
        ("critical", "严重错误：系统崩溃")
    ]

    # 生成一些日志
    for i in range(20):
        level, message = random.choice(log_types)
        if level == "info":
            logger.info(message, module="test_module", function="test_function")
        elif level == "debug":
            logger.debug(message, module="test_module", function="debug_function")
        elif level == "warning":
            logger.warning(message, module="test_module", function="warn_function")
        elif level == "error":
            logger.error(message, module="test_module", function="error_function")
        elif level == "critical":
            logger.critical(message, module="test_module", function="critical_function")

    # 添加一些性能数据
    logger.info("Function process_data completed", duration=0.5, success=True, function="process_data")
    logger.info("Function validate_input completed", duration=0.1, success=True, function="validate_input")
    logger.info("Function save_to_db completed", duration=2.3, success=True, function="save_to_db")
    logger.error("Function api_call failed: Connection timeout", duration=5.0, success=False, function="api_call")

    # 获取统计信息
    stats = logger.get_statistics()
    if stats:
        print("\n=== 日志统计摘要 ===")
        print(f"总日志数: {stats['total_logs']}")
        print(f"日志级别分布: {stats['level_distribution']}")
        print(f"活跃模块: {stats['top_modules']}")
        print(f"活跃函数: {stats['top_functions']}")
        print(f"用户活动: {stats['user_activity']}")
        print(f"错误模式: {stats['error_patterns']}")
        print(f"性能统计: {stats['performance']}")
    else:
        print("未启用统计功能")

    print("\n日志统计测试完成，请检查 logs/stats_test.log 文件")

if __name__ == "__main__":
    test_log_statistics()