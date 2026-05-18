#!/usr/bin/env python3
"""
测试配置系统功能
"""
import sys
import os
import json

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import setup_logger
from core.log_config import get_full_config, save_yaml_config

def test_config_system():
    """测试配置系统功能"""
    print("=== 测试配置系统功能 ===")

    # 测试1: 默认配置
    print("\n1. 测试默认配置:")
    default_config = get_full_config()
    print(f"环境: {default_config.get('environment')}")
    print(f"结构化日志: {default_config.get('use_structured')}")
    print(f"异步日志: {default_config.get('use_async')}")
    print(f"统计功能: {default_config.get('enable_stats')}")

    # 测试2: 环境配置
    print("\n2. 测试生产环境配置:")
    prod_config = get_full_config(environment="production")
    print(f"环境: {prod_config.get('environment')}")
    print(f"控制台级别: {prod_config.get('console_level')}")
    print(f"异步日志: {prod_config.get('use_async')}")
    print(f"压缩功能: {prod_config.get('enable_compression')}")

    # 测试3: YAML配置
    print("\n3. 测试YAML配置加载:")
    yaml_config = get_full_config(config_file="config/logging.yaml")
    print(f"应用名称: {yaml_config.get('custom_settings', {}).get('app_name')}")
    print(f"版本: {yaml_config.get('custom_settings', {}).get('version')}")

    # 测试4: 使用配置创建日志器
    print("\n4. 测试使用配置创建日志器:")
    logger = setup_logger("config_test", config_file="config/logging.yaml")
    logger.info("使用YAML配置创建的日志器测试", module="test_config", function="test_config_system")

    # 测试5: 环境覆盖
    print("\n5. 测试环境覆盖:")
    staging_logger = setup_logger("staging_test", environment="staging")
    staging_logger.warning("Staging环境日志测试", module="test_config", function="test_staging")

    # 测试6: 参数覆盖
    print("\n6. 测试参数覆盖:")
    override_logger = setup_logger("override_test", use_async=True, enable_stats=True)
    override_logger.error("参数覆盖测试", module="test_config", function="test_override")

    print("\n配置系统测试完成，请检查 logs/ 目录下的日志文件")

def test_config_save():
    """测试配置保存功能"""
    print("\n=== 测试配置保存功能 ===")

    # 创建自定义配置
    custom_config = {
        "log_dir": "custom_logs",
        "use_structured": False,
        "custom_feature": {
            "enabled": True,
            "threshold": 0.5
        }
    }

    # 保存配置
    save_yaml_config(custom_config, "config/test_config.yaml")

    # 加载并验证
    loaded_config = get_full_config(config_file="config/test_config.yaml")
    print(f"自定义日志目录: {loaded_config.get('log_dir')}")
    print(f"结构化日志: {loaded_config.get('use_structured')}")
    print(f"自定义功能: {loaded_config.get('custom_feature')}")

if __name__ == "__main__":
    test_config_system()
    test_config_save()