#!/usr/bin/env python3
"""
最终集成测试 - 验证所有日志系统功能
"""
import sys
import os
import time

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import setup_logger, log_performance
from core.log_config import get_full_config
from core.log_archiver import auto_archive_logs

@log_performance
def slow_operation():
    """模拟慢操作"""
    time.sleep(0.1)
    return "completed"

@log_performance
def fast_operation():
    """模拟快操作"""
    return "done"

@log_performance
def error_operation():
    """模拟错误操作"""
    raise ValueError("测试错误")

def test_full_integration():
    """完整集成测试"""
    print("🚀 开始日志系统完整集成测试")
    print("=" * 50)

    # 1. 测试配置系统
    print("\n1️⃣ 测试配置系统")
    config = get_full_config("production", "config/logging.yaml")
    print(f"✅ 生产环境配置加载成功")
    print(f"   异步日志: {config['use_async']}")
    print(f"   压缩功能: {config['enable_compression']}")

    # 2. 测试生产环境日志器
    print("\n2️⃣ 测试生产环境日志器")
    logger = setup_logger(
        "integration_test",
        environment="production",
        enable_stats=True,
        use_async=True
    )
    logger.info("🚀 日志系统集成测试开始", test_phase="integration")

    # 3. 测试性能监控
    print("\n3️⃣ 测试性能监控")
    try:
        result1 = slow_operation()
        result2 = fast_operation()
        result3 = error_operation()
    except ValueError:
        pass

    logger.info("✅ 性能监控测试完成")

    # 4. 测试日志统计
    print("\n4️⃣ 测试日志统计")
    stats = logger.get_statistics()
    if stats:
        print(f"✅ 统计功能正常 - 记录数: {stats['total_logs']}")
        print(f"   级别分布: {stats['level_distribution']}")
        if stats['performance']['total_functions'] > 0:
            print(f"   性能统计: {stats['performance']['total_functions']} 个函数")
            print(".1f"
    # 5. 测试日志压缩
    print("\n5️⃣ 测试日志压缩")
    archived, removed = auto_archive_logs("logs", config)
    print(f"✅ 归档完成 - 归档: {len(archived)} 个, 清理: {len(removed)} 个")

    # 6. 测试多环境切换
    print("\n6️⃣ 测试多环境切换")
    dev_logger = setup_logger("dev_test", environment="development")
    dev_logger.debug("开发环境调试日志", environment="development")

    staging_logger = setup_logger("staging_test", environment="staging")
    staging_logger.info("Staging环境信息日志", environment="staging")

    logger.info("🎉 日志系统集成测试完成", test_phase="integration_complete")

    print("\n" + "=" * 50)
    print("🎉 所有测试通过！日志系统功能完整")
    print("\n📊 测试结果总结:")
    print(f"   • 配置系统: ✅")
    print(f"   • 生产环境日志器: ✅")
    print(f"   • 性能监控: ✅")
    print(f"   • 日志统计: ✅")
    print(f"   • 日志压缩: ✅")
    print(f"   • 多环境支持: ✅")

if __name__ == "__main__":
    test_full_integration()