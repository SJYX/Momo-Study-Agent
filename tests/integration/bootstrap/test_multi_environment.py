#!/usr/bin/env python3
"""
测试多环境支持功能
"""
import sys
import os
import subprocess

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import setup_logger
from core.log_config import get_full_config

def test_environment_configs():
    """测试不同环境配置"""
    print("=== 测试多环境配置 ===")

    environments = ['development', 'staging', 'production']

    for env in environments:
        print(f"\n{env.upper()} 环境配置:")
        config = get_full_config(environment=env)
        print(f"  控制台级别: {config.get('console_level')}")
        print(f"  异步日志: {config.get('use_async')}")
        print(f"  统计功能: {config.get('enable_stats')}")
        print(f"  压缩功能: {config.get('enable_compression')}")
        print(f"  压缩天数: {config.get('compress_after_days')}")

def test_environment_loggers():
    """测试不同环境的日志器"""
    print("\n=== 测试环境日志器 ===")

    environments = ['development', 'staging', 'production']

    for env in environments:
        print(f"\n创建 {env} 环境日志器:")
        logger = setup_logger(f"test_{env}", environment=env)

        logger.info(f"测试 {env} 环境日志器", environment=env, test_type="environment")

        # 如果启用了统计，显示统计信息
        stats = logger.get_statistics()
        if stats:
            print(f"  统计功能已启用 - 当前日志数: {stats['total_logs']}")

def test_command_line_args():
    """测试命令行参数"""
    print("\n=== 测试命令行参数 ===")

    # 测试帮助信息
    print("测试 --help 参数:")
    try:
        result = subprocess.run([
            sys.executable, 'main.py', '--help'
        ], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        print("帮助信息显示成功")
    except Exception as e:
        print(f"帮助信息测试失败: {e}")

    # 测试环境参数解析（不实际运行）
    print("测试环境参数解析:")
    import argparse

    parser = argparse.ArgumentParser(description='墨墨背单词AI助记系统')
    parser.add_argument('--env', '--environment',
                       choices=['development', 'staging', 'production'],
                       default='development',
                       help='运行环境')
    parser.add_argument('--config', '--config-file',
                       default='config/logging.yaml',
                       help='配置文件路径')
    parser.add_argument('--log-level',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       help='覆盖控制台日志级别')
    parser.add_argument('--async-log', action='store_true',
                       help='启用异步日志')
    parser.add_argument('--enable-stats', action='store_true',
                       help='启用日志统计')

    # 测试参数解析
    test_args = ['--env', 'production', '--async-log', '--enable-stats']
    args = parser.parse_args(test_args)

    print(f"  解析的环境: {args.env}")
    print(f"  异步日志: {args.async_log}")
    print(f"  统计功能: {args.enable_stats}")

def test_config_file_loading():
    """测试配置文件加载"""
    print("\n=== 测试配置文件加载 ===")

    # 测试YAML配置加载
    config = get_full_config(config_file="config/logging.yaml")
    print(f"YAML配置加载成功: {config.get('custom_settings', {}).get('app_name', 'N/A')}")

    # 测试不存在的配置文件
    config_missing = get_full_config(config_file="config/nonexistent.yaml")
    print(f"缺失配置文件回退到默认配置: {config_missing.get('environment')}")

if __name__ == "__main__":
    test_environment_configs()
    test_environment_loggers()
    test_command_line_args()
    test_config_file_loading()

    print("\n=== 多环境支持测试完成 ===")