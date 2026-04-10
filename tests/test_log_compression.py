#!/usr/bin/env python3
"""
测试日志压缩功能
"""
import sys
import os
import time
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import setup_logger
from core.log_archiver import LogCompressor, LogArchiver, auto_archive_logs

def test_compression():
    """测试压缩功能"""
    print("=== 测试日志压缩功能 ===")

    # 创建测试日志文件
    test_log_file = "logs/test_compression.log"
    os.makedirs("logs", exist_ok=True)

    # 写入一些测试内容
    with open(test_log_file, 'w', encoding='utf-8') as f:
        for i in range(100):
            f.write(f"2026-04-10 13:40:00,000 - INFO - 测试日志消息 {i}\n")

    original_size = os.path.getsize(test_log_file)
    print(f"原始文件大小: {original_size} 字节")

    # 测试不同压缩格式
    compressor = LogCompressor()

    # Gzip压缩
    gzip_file = compressor.compress_file(test_log_file, "logs/test_compression.log.gz")
    gzip_size = os.path.getsize(gzip_file)
    print(f"Gzip压缩后: {gzip_size} 字节 (压缩率: {(1 - gzip_size/original_size)*100:.1f}%)")

    # Zip压缩
    compressor_zip = LogCompressor("zip")
    zip_file = compressor_zip.compress_file(test_log_file, "logs/test_compression.log.zip")
    zip_size = os.path.getsize(zip_file)
    print(f"Zip压缩后: {zip_size} 字节 (压缩率: {(1 - zip_size/original_size)*100:.1f}%)")

    # Bz2压缩
    compressor_bz2 = LogCompressor("bz2")
    bz2_file = compressor_bz2.compress_file(test_log_file, "logs/test_compression.log.bz2")
    bz2_size = os.path.getsize(bz2_file)
    print(f"Bz2压缩后: {bz2_size} 字节 (压缩率: {(1 - bz2_size/original_size)*100:.1f}%)")

def test_archiver():
    """测试归档功能"""
    print("\n=== 测试日志归档功能 ===")

    # 创建一些旧的日志文件（修改时间设为7天前）
    old_time = time.time() - (8 * 24 * 60 * 60)  # 8天前

    for i in range(3):
        old_log = f"logs/old_test_{i}.log"
        with open(old_log, 'w', encoding='utf-8') as f:
            f.write("这是旧的日志文件\n" * 50)

        # 设置旧的修改时间
        os.utime(old_log, (old_time, old_time))

    # 创建新的日志文件
    new_log = "logs/new_test.log"
    with open(new_log, 'w', encoding='utf-8') as f:
        f.write("这是新的日志文件\n" * 10)

    print("创建了3个旧日志文件和1个新日志文件")

    # 测试归档器
    archiver = LogArchiver("logs", compress_after_days=7)

    # 显示初始统计
    initial_stats = archiver.get_archive_stats()
    print(f"初始状态 - 日志文件: {initial_stats['total_log_files']} 个")

    # 执行归档
    archived = archiver.archive_old_logs()
    print(f"归档了 {len(archived)} 个文件")

    # 显示归档后统计
    after_stats = archiver.get_archive_stats()
    print(f"归档后 - 日志文件: {after_stats['total_log_files']} 个, 压缩文件: {after_stats['total_compressed_files']} 个")

def test_auto_archive():
    """测试自动归档功能"""
    print("\n=== 测试自动归档功能 ===")

    config = {
        "compression_format": "gzip",
        "compress_after_days": 7,
        "archive_retention_days": 30
    }

    archived, removed = auto_archive_logs("logs", config)
    print(f"自动归档完成 - 归档: {len(archived)} 个, 清理: {len(removed)} 个")

def cleanup_test_files():
    """清理测试文件"""
    import glob

    test_files = glob.glob("logs/test_*.log*") + glob.glob("logs/old_test_*.log*") + glob.glob("logs/new_test.log*")

    for file in test_files:
        try:
            os.remove(file)
            print(f"清理测试文件: {file}")
        except:
            pass

if __name__ == "__main__":
    try:
        test_compression()
        test_archiver()
        test_auto_archive()
    finally:
        cleanup_test_files()