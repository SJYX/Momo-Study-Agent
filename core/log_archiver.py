#!/usr/bin/env python3
"""
日志压缩和归档功能
"""
import os
import gzip
import zipfile
import bz2
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

class LogCompressor:
    """日志压缩器"""

    def __init__(self, compression_format: str = "gzip"):
        self.compression_format = compression_format
        self.compressors = {
            "gzip": self._compress_gzip,
            "zip": self._compress_zip,
            "bz2": self._compress_bz2
        }

    def compress_file(self, file_path: str, output_path: Optional[str] = None) -> str:
        """
        压缩单个文件
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if output_path is None:
            output_path = self._get_compressed_path(file_path)

        compressor = self.compressors.get(self.compression_format)
        if not compressor:
            raise ValueError(f"不支持的压缩格式: {self.compression_format}")

        compressor(file_path, output_path)
        return output_path

    def _compress_gzip(self, input_path: str, output_path: str):
        """使用gzip压缩"""
        with open(input_path, 'rb') as f_in:
            with gzip.open(output_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

    def _compress_zip(self, input_path: str, output_path: str):
        """使用zip压缩"""
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(input_path, os.path.basename(input_path))

    def _compress_bz2(self, input_path: str, output_path: str):
        """使用bz2压缩"""
        with open(input_path, 'rb') as f_in:
            with bz2.open(output_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

    def _get_compressed_path(self, file_path: str) -> str:
        """获取压缩文件路径"""
        extensions = {
            "gzip": ".gz",
            "zip": ".zip",
            "bz2": ".bz2"
        }
        ext = extensions.get(self.compression_format, ".gz")
        return file_path + ext

class LogArchiver:
    """日志归档器"""

    def __init__(self, log_dir: str, compression_format: str = "gzip", compress_after_days: int = 7):
        self.log_dir = Path(log_dir)
        self.compressor = LogCompressor(compression_format)
        self.compress_after_days = compress_after_days

    def archive_old_logs(self) -> List[str]:
        """
        归档超过指定天数的日志文件
        """
        archived_files = []
        cutoff_time = datetime.now() - timedelta(days=self.compress_after_days)

        # 查找所有日志文件
        log_files = self._find_log_files()

        for log_file in log_files:
            if self._should_archive(log_file, cutoff_time):
                try:
                    compressed_path = self.compressor.compress_file(str(log_file))
                    archived_files.append(compressed_path)
                    print(f"已归档: {log_file} -> {compressed_path}")
                except Exception as e:
                    print(f"归档失败 {log_file}: {e}")

        return archived_files

    def _find_log_files(self) -> List[Path]:
        """查找所有日志文件"""
        log_files = []
        if not self.log_dir.exists():
            return log_files

        # 查找.log文件，但排除压缩文件
        for file_path in self.log_dir.glob("*.log"):
            if file_path.is_file():
                log_files.append(file_path)

        return log_files

    def _should_archive(self, file_path: Path, cutoff_time: datetime) -> bool:
        """判断文件是否应该被归档"""
        try:
            # 检查文件修改时间
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            return mtime < cutoff_time
        except OSError:
            return False

    def cleanup_old_archives(self, keep_days: int = 30) -> List[str]:
        """
        清理过期的归档文件
        """
        removed_files = []
        cutoff_time = datetime.now() - timedelta(days=keep_days)

        # 查找所有压缩文件
        compressed_files = self._find_compressed_files()

        for compressed_file in compressed_files:
            if self._should_cleanup(compressed_file, cutoff_time):
                try:
                    os.remove(compressed_file)
                    removed_files.append(str(compressed_file))
                    print(f"已清理过期归档: {compressed_file}")
                except Exception as e:
                    print(f"清理失败 {compressed_file}: {e}")

        return removed_files

    def _find_compressed_files(self) -> List[Path]:
        """查找所有压缩文件"""
        compressed_files = []
        if not self.log_dir.exists():
            return compressed_files

        # 查找压缩文件
        for ext in ['*.gz', '*.zip', '*.bz2']:
            for file_path in self.log_dir.glob(ext):
                if file_path.is_file():
                    compressed_files.append(file_path)

        return compressed_files

    def _should_cleanup(self, file_path: Path, cutoff_time: datetime) -> bool:
        """判断压缩文件是否应该被清理"""
        try:
            # 检查文件修改时间
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            return mtime < cutoff_time
        except OSError:
            return False

    def get_archive_stats(self) -> dict:
        """获取归档统计信息"""
        stats = {
            "total_log_files": 0,
            "total_compressed_files": 0,
            "total_size_logs": 0,
            "total_size_compressed": 0,
            "compression_ratio": 0.0
        }

        if not self.log_dir.exists():
            return stats

        # 统计日志文件
        for log_file in self._find_log_files():
            stats["total_log_files"] += 1
            stats["total_size_logs"] += log_file.stat().st_size

        # 统计压缩文件
        for compressed_file in self._find_compressed_files():
            stats["total_compressed_files"] += 1
            stats["total_size_compressed"] += compressed_file.stat().st_size

        # 计算压缩率
        if stats["total_size_logs"] > 0:
            stats["compression_ratio"] = (
                (stats["total_size_logs"] - stats["total_size_compressed"])
                / stats["total_size_logs"]
            ) * 100

        return stats

def auto_archive_logs(log_dir: str = "logs", config: Optional[dict] = None):
    """
    自动归档日志文件
    """
    if config is None:
        config = {}

    compression_format = config.get("compression_format", "gzip")
    compress_after_days = config.get("compress_after_days", 7)

    archiver = LogArchiver(log_dir, compression_format, compress_after_days)

    print(f"开始归档日志文件 (超过 {compress_after_days} 天的文件)...")
    archived = archiver.archive_old_logs()

    print(f"成功归档 {len(archived)} 个文件")

    # 清理过期归档
    keep_days = config.get("archive_retention_days", 30)
    print(f"清理超过 {keep_days} 天的归档文件...")
    removed = archiver.cleanup_old_archives(keep_days)

    print(f"清理了 {len(removed)} 个过期归档文件")

    # 显示统计信息
    stats = archiver.get_archive_stats()
    print("\n归档统计:")
    print(f"  日志文件: {stats['total_log_files']} 个")
    print(f"  压缩文件: {stats['total_compressed_files']} 个")
    print(f"  日志总大小: {stats['total_size_logs'] / 1024:.1f} KB")
    print(f"  压缩总大小: {stats['total_size_compressed'] / 1024:.1f} KB")
    print(f"  压缩率: {stats['compression_ratio']:.1f}%")

    return archived, removed