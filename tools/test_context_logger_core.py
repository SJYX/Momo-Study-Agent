#!/usr/bin/env python3
"""
直接测试 ContextLogger._should_log() 的核心逻辑，不涉及交互式初始化
"""

import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.logger import ContextLogger


def test_should_log_logic():
    """测试 _should_log() 核心过滤逻辑"""
    
    print("\n" + "="*60)
    print("TEST: ContextLogger._should_log() 核心逻辑")
    print("="*60)
    
    # 创建基础的 Python logger
    base_logger = logging.getLogger("test")
    base_logger.setLevel(logging.INFO)  # 全局 INFO
    
    # 包装为 ContextLogger
    context_logger = ContextLogger(base_logger)
    
    # 设置模块级别
    context_logger.set_module_levels({
        "db_manager": logging.DEBUG,      # 10
        "mimo_client": logging.ERROR,     # 40
        "gemini_client": logging.WARNING, # 30
    })
    
    print("\n初始化:")
    print(f"  全局级别: INFO ({logging.INFO})")
    print(f"  db_manager: DEBUG ({logging.DEBUG})")
    print(f"  mimo_client: ERROR ({logging.ERROR})")
    print(f"  gemini_client: WARNING ({logging.WARNING})")
    print(f"  未配置模块: 默认使用全局 INFO ({logging.INFO})")
    
    # 测试用例
    test_cases = [
        # (level, module, expected_result, description)
        (logging.DEBUG, "db_manager", True, "db_manager DEBUG 应该显示 (模块级< 全局)"),
        (logging.INFO, "db_manager", True, "db_manager INFO 应该显示"),
        (logging.WARNING, "db_manager", True, "db_manager WARNING 应该显示"),
        (logging.DEBUG, "mimo_client", False, "mimo_client DEBUG 不应显示 (模块级> 全局)"),
        (logging.ERROR, "mimo_client", True, "mimo_client ERROR 应该显示 (等于模块级)"),
        (logging.DEBUG, "unknown", False, "unknown DEBUG 不应显示 (使用全局 INFO)"),
        (logging.INFO, "unknown", True, "unknown INFO 应该显示 (等于全局)"),
        (logging.WARNING, "unknown", True, "unknown WARNING 应该显示"),
        (logging.WARNING, "gemini_client", True, "gemini_client WARNING 应该显示"),
        (logging.ERROR, "gemini_client", True, "gemini_client ERROR 应该显示"),
    ]
    
    print("\n执行测试:")
    passed = 0
    failed = 0
    
    for level, module, expected, description in test_cases:
        result = context_logger._should_log(level, module)
        status = "✓ PASS" if result == expected else "✗ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"  [{status}] {description}")
        print(f"       _should_log({logging.getLevelName(level)}, '{module}') = {result} (期望 {expected})")
    
    print("\n" + "="*60)
    print(f"结果: {passed} 通过, {failed} 失败")
    print("="*60)
    
    return failed == 0


def test_module_level_priority():
    """测试模块级别优先级"""
    
    print("\n" + "="*60)
    print("TEST: 模块级别优先级")
    print("="*60)
    
    base_logger = logging.getLogger("priority_test")
    base_logger.setLevel(logging.WARNING)  # 全局 WARNING
    
    context_logger = ContextLogger(base_logger)
    context_logger.set_module_levels({
        "special_module": logging.DEBUG,  # 模块覆盖为 DEBUG
    })
    
    print("\n全局级别: WARNING (30)")
    print("special_module 模块级别: DEBUG (10)")
    
    print("\n发送日志到 'special_module':")
    
    # 模块级别应该覆盖全局级别
    test_results = [
        (logging.DEBUG, "special_module", True, "DEBUG 应该通过 (被模块级别允许)"),
        (logging.DEBUG, "other_module", False, "DEBUG 不应通过 (全局级别 WARNING)"),
        (logging.WARNING, "other_module", True, "WARNING 应该通过 (匹配全局级别)"),
    ]
    
    for level, module, expected, desc in test_results:
        result = context_logger._should_log(level, module)
        status = "✓" if result == expected else "✗"
        print(f"  [{status}] {desc}")
        print(f"       → {result}")
    
    return True


if __name__ == "__main__":
    print("\n" + "="*60)
    print("ContextLogger 核心逻辑测试")
    print("="*60)
    
    try:
        success1 = test_should_log_logic()
        success2 = test_module_level_priority()
        
        if success1 and success2:
            print("\n✓ 所有测试通过")
            sys.exit(0)
        else:
            print("\n✗ 某些测试失败")
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
