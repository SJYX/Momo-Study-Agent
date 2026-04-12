# -*- coding: utf-8 -*-
"""
实用工具函数集合
提供常用的辅助功能
"""

import functools
import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, TypeVar, cast

from core.constants import CACHE_MAX_SIZE, CACHE_TTL_SECONDS

# 类型变量
F = TypeVar("F", bound=Callable[..., Any])


# ============================================================================
# 缓存装饰器 (Caching Decorators)
# ============================================================================


def lru_cache_with_ttl(maxsize: int = CACHE_MAX_SIZE, ttl: int = CACHE_TTL_SECONDS):
    """
    带过期时间的 LRU 缓存装饰器

    Args:
        maxsize: 最大缓存条目数
        ttl: 缓存过期时间（秒）
    """

    def decorator(func: F) -> F:
        cache: Dict[str, tuple] = {}  # key -> (result, timestamp)
        cache_info = {"hits": 0, "misses": 0}

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            key = _make_cache_key(args, kwargs)

            # 检查缓存
            if key in cache:
                result, timestamp = cache[key]
                # 检查是否过期
                if time.time() - timestamp < ttl:
                    cache_info["hits"] += 1
                    return result
                else:
                    # 过期，删除
                    del cache[key]

            # 缓存未命中，执行函数
            cache_info["misses"] += 1
            result = func(*args, **kwargs)

            # 保存到缓存
            cache[key] = (result, time.time())

            # 如果超过最大大小，删除最旧的条目
            if len(cache) > maxsize:
                oldest_key = min(cache.keys(), key=lambda k: cache[k][1])
                del cache[oldest_key]

            return result

        def cache_clear():
            cache.clear()
            cache_info["hits"] = 0
            cache_info["misses"] = 0

        def cache_stats():
            return cache_info.copy()

        wrapper.cache_clear = cache_clear  # type: ignore
        wrapper.cache_stats = cache_stats  # type: ignore

        return cast(F, wrapper)

    return decorator


def _make_cache_key(args: tuple, kwargs: dict) -> str:
    """生成缓存键"""
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    key_str = "|".join(key_parts)
    return hashlib.md5(key_str.encode()).hexdigest()


# ============================================================================
# 重试装饰器 (Retry Decorator)
# ============================================================================


def retry_on_exception(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    logger: Optional[Any] = None,
):
    """
    异常重试装饰器

    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff: 延迟倍增系数
        exceptions: 需要重试的异常类型
        logger: 日志记录器
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        if logger:
                            logger.warning(
                                f"函数 {func.__name__} 执行失败，{current_delay}秒后重试 "
                                f"(第 {attempt + 1}/{max_retries} 次)",
                                error=str(e),
                            )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        if logger:
                            logger.error(
                                f"函数 {func.__name__} 重试 {max_retries} 次后仍然失败", error=str(e), exc_info=True
                            )

            # 所有重试都失败，抛出最后一个异常
            raise last_exception

        return cast(F, wrapper)

    return decorator


# ============================================================================
# 性能监控装饰器 (Performance Monitoring)
# ============================================================================


def monitor_performance(threshold_ms: int = 1000, logger: Optional[Any] = None):
    """
    性能监控装饰器

    Args:
        threshold_ms: 性能警告阈值（毫秒）
        logger: 日志记录器
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed_ms = (time.time() - start_time) * 1000
                if elapsed_ms > threshold_ms:
                    if logger:
                        logger.warning(
                            f"函数 {func.__name__} 执行耗时 {elapsed_ms:.2f}ms "
                            f"(超过阈值 {threshold_ms}ms)",
                            function=func.__name__,
                            elapsed_ms=elapsed_ms,
                            threshold_ms=threshold_ms,
                        )

        return cast(F, wrapper)

    return decorator


# ============================================================================
# 时间工具 (Time Utilities)
# ============================================================================


def get_timestamp_with_tz() -> str:
    """获取当前时间戳，格式为 ISO 8601 含时区"""
    return datetime.now(timezone.utc).isoformat()


def parse_iso_timestamp(timestamp: str) -> datetime:
    """解析 ISO 8601 格式时间戳"""
    return datetime.fromisoformat(timestamp)


def get_elapsed_days(timestamp: str) -> int:
    """计算从指定时间戳到现在经过的天数"""
    dt = parse_iso_timestamp(timestamp)
    now = datetime.now(timezone.utc)
    return (now - dt).days


# ============================================================================
# 字符串工具 (String Utilities)
# ============================================================================


def truncate_string(s: str, max_length: int = 100, suffix: str = "...") -> str:
    """截断字符串到指定长度"""
    if len(s) <= max_length:
        return s
    return s[: max_length - len(suffix)] + suffix


def clean_whitespace(s: str) -> str:
    """清理多余的空白字符"""
    return " ".join(s.split())


def safe_str(obj: Any, default: str = "") -> str:
    """安全地将对象转换为字符串"""
    try:
        return str(obj)
    except Exception:
        return default


# ============================================================================
# 哈希工具 (Hash Utilities)
# ============================================================================


def get_file_hash(file_path: str, algorithm: str = "md5") -> str:
    """计算文件哈希值"""
    hash_obj = hashlib.new(algorithm)
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    except Exception:
        return ""


def get_string_hash(s: str, algorithm: str = "md5") -> str:
    """计算字符串哈希值"""
    hash_obj = hashlib.new(algorithm)
    hash_obj.update(s.encode("utf-8"))
    return hash_obj.hexdigest()


# ============================================================================
# 数据验证工具 (Validation Utilities)
# ============================================================================


def is_valid_email(email: str) -> bool:
    """简单的邮箱格式验证"""
    import re

    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def is_valid_url(url: str) -> bool:
    """简单的 URL 格式验证"""
    import re

    pattern = r"^https?://[^\s]+$"
    return bool(re.match(pattern, url))


# ============================================================================
# 批处理工具 (Batch Processing Utilities)
# ============================================================================


def batch_items(items: list, batch_size: int):
    """将列表分批，生成器模式"""
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def chunk_list(items: list, chunk_count: int):
    """将列表平均分成 N 份"""
    chunk_size = len(items) // chunk_count
    remainder = len(items) % chunk_count

    chunks = []
    start = 0
    for i in range(chunk_count):
        # 将余数分配到前面的 chunk
        size = chunk_size + (1 if i < remainder else 0)
        chunks.append(items[start : start + size])
        start += size

    return chunks
