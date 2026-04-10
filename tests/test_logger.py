#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试新的日志系统
"""
import sys
sys.path.insert(0, '.')

from core.logger import setup_logger

def test_logger():
    # 测试结构化日志
    logger = setup_logger("test_user", use_structured=True)

    # 设置上下文
    logger.set_context(session_id="test_session_123")

    # 测试不同级别的日志
    logger.debug("这是一条调试信息", module="test", function="test_logger")
    logger.info("这是一条信息", module="test", function="test_logger", extra={"key": "value"})
    logger.warning("这是一条警告", module="test", function="test_logger")
    logger.error("这是一条错误", module="test", function="test_logger")

    print("日志测试完成，请检查 logs/test_user.log 文件")

if __name__ == "__main__":
    test_logger()