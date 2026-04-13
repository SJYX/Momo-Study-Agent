#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志分级系统测试脚本
演示如何使用不同日志级别
"""
import os
import sys
import time
import logging

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 避免导入 config.py 时触发交互式用户选择
os.environ.setdefault("MOMO_USER", "Asher")

def test_logging_levels():
    """测试日志分级系统"""
    from core.db_manager import _debug_log
    from core.logger import setup_logger, get_logger
    
    print("=" * 70)
    print("日志分级系统演示")
    print("=" * 70)
    print()
    
    # 测试 1: 默认级别（DEBUG）
    print("✓ 测试 1: 默认级别调用（级别：DEBUG）")
    print("-" * 70)
    _debug_log("这是一条调试消息（默认级别）")
    _debug_log("带耗时的调试消息", start_time=time.time() - 0.123)
    print()
    
    # 测试 2: 各种日志级别
    print("✓ 测试 2: 不同日志级别和模块")
    print("-" * 70)
    _debug_log("调试信息：变量值为 x=100", level="DEBUG", module="test_module")
    _debug_log("信息：用户登录成功", level="INFO", module="auth")
    _debug_log("警告：检测到异常操作", level="WARNING", module="security")
    _debug_log("错误：数据库连接失败", level="ERROR", module="db")
    _debug_log("严重错误：系统即将崩溃", level="CRITICAL", module="system")
    print()
    
    # 测试 3: 性能测试消息
    print("✓ 测试 3: 性能计时消息")
    print("-" * 70)
    op_time = time.time()
    time.sleep(0.05)  # 模拟耗时操作
    _debug_log("数据库查询完成", start_time=op_time, level="INFO", module="db")
    print()
    
    # 测试 4: 获取当前日志级别
    print("✓ 测试 4: 查看当前日志配置")
    print("-" * 70)
    logger = setup_logger(username="test_user", environment="dev")
    module_levels = getattr(logger, 'module_levels', {})
    effective_level = logger.base_logger.getEffectiveLevel()
    print(f"全局日志级别: {logging.getLevelName(effective_level)} ({effective_level})")
    print(f"模块级别覆盖: {module_levels if module_levels else '无'}")
    print(f"db_manager 模块级别: {logger.get_module_level('db_manager')}")
    print(f"test_module 模块级别: {logger.get_module_level('test_module')}")
    print()
    
    # 测试 5: 环境变量提示
    print("✓ 测试 5: 日志级别控制")
    print("-" * 70)
    print("使用以下环境变量控制日志级别：")
    print()
    print("  1. 全局日志级别（优先级低）：")
    print("     export LOG_LEVEL=DEBUG          # 显示所有日志")
    print("     export LOG_LEVEL=INFO           # 仅显示 INFO 及以上（默认）")
    print("     export LOG_LEVEL=WARNING        # 仅显示警告及以上")
    print()
    print("  2. 模块级别覆盖（优先级高）：")
    print('     export LOG_MODULE_LEVELS="db_manager:DEBUG,mimo:WARNING"')
    print()
    print("  3. 运行示例：")
    print("     # 仅调试 db_manager 模块")
    print("     export LOG_LEVEL=INFO")
    print('     export LOG_MODULE_LEVELS="db_manager:DEBUG"')
    print("     python main.py")
    print()

if __name__ == "__main__":
    try:
        test_logging_levels()
        print("✅ 日志分级系统测试完成！")
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
