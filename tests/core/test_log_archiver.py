import os
import time
import pytest
import gzip
from datetime import datetime, timedelta
from core.log_archiver import LogArchiver

@pytest.fixture
def temp_log_dir(tmp_path):
    """提供一个临时的日志目录。"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return log_dir

def test_archive_needed_detection(temp_log_dir):
    """验证是否能正确检测出需要归档的文件（基于天数）。"""
    # 设置 1 天后归档
    archiver = LogArchiver(str(temp_log_dir), compress_after_days=1)
    
    # 1. 新文件不需要归档
    new_file = temp_log_dir / "new.log"
    new_file.write_text("hello")
    assert archiver.archive_old_logs() == []
    
    # 2. 旧文件需要归档
    old_file = temp_log_dir / "old.log"
    old_file.write_text("old data")
    # 修改时间为 2 天前
    old_time = time.time() - (2 * 24 * 3600)
    os.utime(old_file, (old_time, old_time))
    
    archived = archiver.archive_old_logs()
    assert len(archived) == 1
    assert archived[0].endswith(".gz")

def test_full_archive_cycle(temp_log_dir):
    """验证 归档 -> 压缩 的全过程。"""
    archiver = LogArchiver(str(temp_log_dir), compress_after_days=0) # 0 天即立即归档
    
    log_file = temp_log_dir / "test.log"
    content = "Test content"
    log_file.write_text(content)
    
    # 修改时间为 1 小时前，确保触发 (如果是 0 天判断)
    old_time = time.time() - 3600
    os.utime(log_file, (old_time, old_time))
    
    # 执行归档
    archived_files = archiver.archive_old_logs()
    
    assert len(archived_files) == 1
    gz_path = archived_files[0]
    assert os.path.exists(gz_path)
    
    # 验证压缩包内容
    with gzip.open(gz_path, 'rt') as f:
        assert f.read() == content

def test_cleanup_expired_archives(temp_log_dir):
    """验证过期归档清理逻辑。"""
    archiver = LogArchiver(str(temp_log_dir))
    
    # 创建一个伪造的旧压缩包
    old_gz = temp_log_dir / "archive.log.gz"
    old_gz.write_text("old zipped data")
    
    # 修改其时间为 40 天前
    old_time = time.time() - (40 * 24 * 3600)
    os.utime(old_gz, (old_time, old_time))
    
    # 执行清理 (保留 30 天)
    removed = archiver.cleanup_old_archives(keep_days=30)
    
    assert len(removed) == 1
    assert not old_gz.exists()
