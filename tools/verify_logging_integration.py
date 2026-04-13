#!/usr/bin/env python3
"""
验证日志分级和模块级别过滤是否集成正确
使用各种 LOG_LEVEL 和 LOG_MODULE_LEVELS 配置运行
"""

import os
import sys
import logging
import io

# 确保能找到 core 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 避免导入 config.py 时触发交互式用户选择
os.environ.setdefault('MOMO_USER', 'Asher')

from core.logger import setup_logger, get_logger, ContextLogger


def test_global_log_level():
    """测试全局日志级别过滤"""
    print("\n" + "="*60)
    print("TEST 1: 全局日志级别过滤 (LOG_LEVEL=WARNING)")
    print("="*60)
    
    # 设置环境变量
    os.environ['LOG_LEVEL'] = 'WARNING'
    os.environ.pop('LOG_MODULE_LEVELS', None)
    
    # 重新初始化日志
    logger = setup_logger(username="test_user", environment="dev")
    
    # 执行日志调用
    print("\n发送日志:")
    logger.debug("DEBUG: 这条不应该出现")
    logger.info("INFO: 这条不应该出现")
    logger.warning("WARNING: 这条应该出现")
    logger.error("ERROR: 这条应该出现")
    
    print("\n✓ 预期: 仅显示 WARNING 和 ERROR")


def test_module_level_override():
    """测试模块级别覆盖全局级别"""
    print("\n" + "="*60)
    print("TEST 2: 模块级别覆盖 (全局=WARNING, db_manager=DEBUG)")
    print("="*60)
    
    # 设置环境变量
    os.environ['LOG_LEVEL'] = 'WARNING'
    os.environ['LOG_MODULE_LEVELS'] = 'db_manager:DEBUG'
    
    # 重新初始化日志
    logger = setup_logger(username="test_user", environment="dev")
    
    # 验证模块级别配置是否加载
    if hasattr(logger, 'get_module_level'):
        db_level = logger.get_module_level('db_manager')
        print(f"\n验证模块级别:")
        print(f"  全局日志级别: {logger.base_logger.getEffectiveLevel()}")
        print(f"  db_manager 模块级别: {db_level}")
        print(f"  DEBUG 级别值: {logging.DEBUG}")
    
    # 执行日志调用测试模块级别过滤
    print("\n发送日志 (模块='db_manager'):")
    
    # 直接调用 ContextLogger.log() 来测试模块级别过滤
    if hasattr(logger, 'log'):
        # 模块级别应该覆盖全局级别
        logger.log(logging.DEBUG, "DEBUG: db_manager 模块 (应该出现)", module="db_manager")
        logger.log(logging.INFO, "INFO: db_manager 模块 (应该出现)", module="db_manager")
        logger.log(logging.WARNING, "WARNING: db_manager 模块 (应该出现)", module="db_manager")
    
    print("\nN发送日志 (模块='other_module'):")
    if hasattr(logger, 'log'):
        # other_module 应遵循全局 WARNING 级别
        logger.log(logging.DEBUG, "DEBUG: other_module (不应该出现)", module="other_module")
        logger.log(logging.INFO, "INFO: other_module (不应该出现)", module="other_module")
        logger.log(logging.WARNING, "WARNING: other_module (应该出现)", module="other_module")
    
    print("\n✓ 预期: db_manager 显示 DEBUG+, other_module 显示 WARNING+")


def test_environment_variable_parsing():
    """测试环境变量解析"""
    print("\n" + "="*60)
    print("TEST 3: 环境变量解析")
    print("="*60)
    
    # 设置复杂的环境变量
    os.environ['LOG_LEVEL'] = 'INFO'
    os.environ['LOG_MODULE_LEVELS'] = 'db_manager:DEBUG,mimo_client:ERROR,gemini_client:WARNING'
    
    # 重新初始化日志
    logger = setup_logger(username="test_user", environment="dev")
    
    if hasattr(logger, 'get_module_level'):
        print("\n解析的模块级别:")
        for module in ['db_manager', 'mimo_client', 'gemini_client', 'unknown_module']:
            level = logger.get_module_level(module)
            level_names = {
                logging.DEBUG: "DEBUG",
                logging.INFO: "INFO",
                logging.WARNING: "WARNING",
                logging.ERROR: "ERROR",
                logging.CRITICAL: "CRITICAL"
            }
            print(f"  {module}: {level_names.get(level, f'unknown({level})')}")
    
    print("\n✓ 预期: db_manager=DEBUG, mimo_client=ERROR, gemini_client=WARNING, unknown_module=INFO (全局)")


def test_backward_compatibility():
    """测试向后兼容性 - 现有代码应该继续工作"""
    print("\n" + "="*60)
    print("TEST 4: 向后兼容性（现有调用方式）")
    print("="*60)
    
    os.environ['LOG_LEVEL'] = 'DEBUG'
    os.environ.pop('LOG_MODULE_LEVELS', None)
    
    logger = setup_logger(username="test_user", environment="dev")
    
    print("\n使用标准 logger 接口:")
    logger.debug("debug 消息")
    logger.info("info 消息")
    logger.warning("warning 消息")
    logger.error("error 消息")
    
    print("\n✓ 预期: 所有消息都应该出现")


def test_db_manager_usage():
    """测试 db_manager._debug_log 函数的集成"""
    print("\n" + "="*60)
    print("TEST 5: db_manager._debug_log() 集成")
    print("="*60)
    
    os.environ['LOG_LEVEL'] = 'INFO'
    os.environ['LOG_MODULE_LEVELS'] = 'db_manager:DEBUG'
    os.environ['MOMO_USER'] = 'Asher'
    
    # 重新初始化日志
    from core import db_manager
    setup_logger(username="test_user", environment="dev")
    
    print("\n调用 _debug_log:")
    
    # 模拟实际使用
    import time
    start = time.time()
    
    # 这些应该出现（db_manager 模块覆盖为 DEBUG）
    db_manager._debug_log("调试消息", start_time=start, level="DEBUG", module="db_manager")
    db_manager._debug_log("信息消息", level="INFO", module="db_manager")
    
    print("\n✓ 预期: DEBUG 和 INFO 都应该出现，并且包含时间戳")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("日志系统集成验证")
    print("="*60)
    
    try:
        test_global_log_level()
        test_module_level_override()
        test_environment_variable_parsing()
        test_backward_compatibility()
        test_db_manager_usage()
        
        print("\n" + "="*60)
        print("✓ 所有验证测试完成")
        print("="*60)
        
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
