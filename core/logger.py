import logging
import os
import sys
import json
import time
import functools
import queue
import threading
import io
import platform
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener
from datetime import datetime
from typing import Dict, Any, Optional
from collections import defaultdict, Counter
import re

# Global singleton for ContextLogger
_global_context_logger = None

def force_utf8_console():
    """Force UTF-8 encoding for console output on Windows."""
    if platform.system() == "Windows":
        # Reconfigure stdout/stderr to use UTF-8 encoding
        if sys.stdout.encoding != 'utf-8':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if sys.stderr.encoding != 'utf-8':
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    from .log_config import get_full_config
except ImportError:
    # 如果配置模块不存在，使用默认配置
    def get_full_config(environment=None, config_file=None):
        return {
            "log_dir": "logs",
            "max_file_size": 10 * 1024 * 1024,
            "backup_count": 5,
            "encoding": "utf-8",
            "console_level": "INFO",
            "file_level": "DEBUG",
            "use_structured": True,
            "use_async": False,
            "enable_stats": False,
            "async_queue_size": 1000,
            "performance_threshold": 1.0,
            "stats_reset_interval": 3600,
            "enable_compression": False,
            "compression_format": "gzip",
            "compress_after_days": 7,
            "environment": "development",
            "buffer_size": 8192,
            "flush_interval": 1.0,
            "max_workers": 2,
        }

class StructuredFormatter(logging.Formatter):
    """结构化日志格式器，输出JSON格式"""

    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "user": getattr(record, 'user', 'unknown'),
            "session_id": getattr(record, 'session_id', None),
            "extra": getattr(record, 'extra', {})
        }

        # 清理None值
        log_entry = {k: v for k, v in log_entry.items() if v is not None}

        return json.dumps(log_entry, ensure_ascii=False)

class AsyncLogger:
    """异步日志器，避免阻塞主线程"""
    
    def __init__(self, base_logger, config=None):
        if config is None:
            config = {"async_queue_size": 1000}
            
        self.queue = queue.Queue(maxsize=config.get("async_queue_size", 1000))
        self.handler = QueueHandler(self.queue)
        base_logger.addHandler(self.handler)
        
        # 只传递非QueueHandler的handler给listener
        handlers = [h for h in base_logger.handlers if not isinstance(h, QueueHandler)]
        self.listener = QueueListener(self.queue, *handlers)
        self.listener.start()
        
        # 守护线程，确保程序退出时能清理
        self._shutdown_event = threading.Event()
        
    def shutdown(self):
        """优雅关闭异步日志器"""
        self._shutdown_event.set()
        self.listener.stop()

class LogStatistics:
    """日志统计收集器"""
    
    def __init__(self):
        self.stats = {
            'total_logs': 0,
            'level_counts': defaultdict(int),
            'module_counts': defaultdict(int),
            'function_counts': defaultdict(int),
            'user_counts': defaultdict(int),
            'error_patterns': Counter(),
            'performance_stats': {
                'total_functions': 0,
                'avg_duration': 0.0,
                'slowest_function': None,
                'fastest_function': None
            }
        }
        self._lock = threading.Lock()
        
    def record_log(self, record):
        """记录一条日志"""
        with self._lock:
            self.stats['total_logs'] += 1
            self.stats['level_counts'][record.levelname] += 1
            
            if hasattr(record, 'module') and record.module:
                self.stats['module_counts'][record.module] += 1
                
            if hasattr(record, 'funcName') and record.funcName:
                self.stats['function_counts'][record.funcName] += 1
                
            if hasattr(record, 'user'):
                self.stats['user_counts'][record.user] += 1
                
            # 分析错误模式
            if record.levelno >= logging.ERROR:
                self._analyze_error_pattern(record.getMessage())
                
            # 分析性能数据
            if hasattr(record, 'extra') and record.extra:
                self._analyze_performance(record.extra)
    
    def _analyze_error_pattern(self, message):
        """分析错误模式"""
        # 支持中英文的错误模式识别
        patterns = [
            r'Connection.*failed|连接.*失败',
            r'Timeout.*occurred|超时', 
            r'Authentication.*failed|认证.*失败',
            r'Database.*error|数据库.*错误',
            r'API.*error|API.*错误',
            r'Network.*error|网络.*错误'
        ]
        
        for pattern in patterns:
            if re.search(pattern, message, re.IGNORECASE):
                self.stats['error_patterns'][pattern] += 1
                break
    
    def _analyze_performance(self, extra):
        """分析性能数据"""
        if 'duration' in extra:
            duration = extra['duration']
            perf = self.stats['performance_stats']
            
            perf['total_functions'] += 1
            # 计算运行平均值
            perf['avg_duration'] = (
                (perf['avg_duration'] * (perf['total_functions'] - 1)) + duration
            ) / perf['total_functions']
            
            # 更新最慢/最快函数
            func_name = extra.get('function', 'unknown')
            if perf['slowest_function'] is None or duration > perf['slowest_function'][1]:
                perf['slowest_function'] = (func_name, duration)
            if perf['fastest_function'] is None or duration < perf['fastest_function'][1]:
                perf['fastest_function'] = (func_name, duration)
    
    def get_summary(self):
        """获取统计摘要"""
        with self._lock:
            return {
                'total_logs': self.stats['total_logs'],
                'level_distribution': dict(self.stats['level_counts']),
                'top_modules': dict(sorted(self.stats['module_counts'].items(), 
                                         key=lambda x: x[1], reverse=True)[:5]),
                'top_functions': dict(sorted(self.stats['function_counts'].items(), 
                                           key=lambda x: x[1], reverse=True)[:5]),
                'user_activity': dict(self.stats['user_counts']),
                'error_patterns': dict(self.stats['error_patterns']),
                'performance': self.stats['performance_stats'].copy()
            }
    
    def reset(self):
        """重置统计数据"""
        with self._lock:
            self.__init__()

class AsyncStatisticsProcessor(threading.Thread):
    """异步统计处理器，从队列中消费日志记录并更新统计信息"""

    def __init__(self, queue, statistics):
        super().__init__(daemon=True)
        self.queue = queue
        self.statistics = statistics
        self._stop_event = threading.Event()

    def run(self):
        """从队列中消费日志记录并更新统计信息"""
        while not self._stop_event.is_set():
            try:
                # 使用超时等待，以便能够响应停止事件
                record = self.queue.get(timeout=0.1)
                try:
                    self.statistics.record_log(record)
                except Exception:
                    # 忽略统计处理中的错误，避免影响日志系统
                    pass
                finally:
                    self.queue.task_done()
            except queue.Empty:
                # 队列为空，继续等待
                continue
            except Exception:
                # 忽略其他错误
                pass

    def stop(self):
        """停止处理器"""
        self._stop_event.set()

class StatisticsHandler(logging.Handler):
    """收集日志统计的处理器"""

    def __init__(self, statistics, queue=None):
        super().__init__()
        self.statistics = statistics
        self.queue = queue

    def emit(self, record):
        """处理日志记录"""
        if self.queue:
            # 异步模式：将记录放入队列
            try:
                self.queue.put(record, block=False)
            except queue.Full:
                # 队列满时，直接处理（降级到同步）
                self.statistics.record_log(record)
        else:
            # 同步模式：直接处理
            self.statistics.record_log(record)

class ContextLogger:
    """支持上下文信息和模块级别日志控制的日志器"""

    def __init__(self, base_logger, async_logger=None, statistics=None, module_levels=None):
        self.base_logger = base_logger
        self.context = {}
        self.async_logger = async_logger
        self.statistics = statistics
        
        # 模块级别映射 {"module_name": level_number}
        self.module_levels = module_levels or {}
        
        # 日志级别映射
        self.level_map = {
            "DEBUG": logging.DEBUG,      # 10
            "INFO": logging.INFO,        # 20
            "WARNING": logging.WARNING,  # 30
            "ERROR": logging.ERROR,      # 40
            "CRITICAL": logging.CRITICAL # 50
        }

    def set_context(self, **kwargs):
        """设置上下文信息"""
        self.context.update(kwargs)

    def clear_context(self):
        """清除上下文信息"""
        self.context.clear()
    
    def set_module_levels(self, module_levels):
        """设置模块级别映射
        
        Args:
            module_levels: dict, 格式 {"module_name": logging.DEBUG/INFO/WARNING/ERROR/CRITICAL}
        """
        self.module_levels = module_levels or {}
    
    def get_module_level(self, module):
        """获取指定模块的日志级别
        
        Args:
            module: str, 模块名称
            
        Returns:
            int, 日志级别数值
        """
        if module in self.module_levels:
            return self.module_levels[module]
        return None

    def get_statistics(self):
        """获取日志统计信息"""
        if self.statistics:
            return self.statistics.get_summary()
        return None

    def reset_statistics(self):
        """重置统计数据"""
        if self.statistics:
            self.statistics.reset()

    def _add_context(self, record):
        """为日志记录添加上下文"""
        for key, value in self.context.items():
            setattr(record, key, value)
        return record

    def _should_log(self, level, module):
        """判断是否应该输出此条日志
        
        Args:
            level: int, 日志级别数值
            module: str 或 None, 模块名称
            
        Returns:
            bool, 是否应该输出
        """
        # 如果指定了模块，检查模块级别
        if module and module in self.module_levels:
            module_level = self.module_levels[module]
            return level >= module_level
        
        # 否则，检查全局级别（通过 base_logger 的 effective_level）
        return level >= self.base_logger.getEffectiveLevel()

    def log(self, level, message, **kwargs):
        """通用日志方法"""
        module = kwargs.get('module')
        func_name = kwargs.get('function')
        
        # 检查是否应该输出此条日志
        if not self._should_log(level, module):
            return
        
        record = logging.LogRecord(
            name=self.base_logger.name,
            level=level,
            pathname="",
            lineno=0,
            msg=message,
            args=(),
            exc_info=None
        )
        
        # 设置模块和函数信息
        if module:
            record.module = module
        if func_name:
            record.funcName = func_name
            
        record = self._add_context(record)
        
        # 将额外参数存储在extra中
        if kwargs:
            if not hasattr(record, 'extra'):
                record.extra = {}
            record.extra.update(kwargs)
        
        # 如果启用了异步日志，通过队列发送，否则直接处理
        if self.async_logger:
            # 异步模式：只通过QueueHandler发送，避免重复
            self.async_logger.handler.handle(record)
        else:
            # 同步模式：直接处理
            self.base_logger.handle(record)

    def debug(self, message, **kwargs):
        self.log(logging.DEBUG, message, **kwargs)

    def info(self, message, **kwargs):
        self.log(logging.INFO, message, **kwargs)

    def warning(self, message, **kwargs):
        self.log(logging.WARNING, message, **kwargs)

    def error(self, message, **kwargs):
        self.log(logging.ERROR, message, **kwargs)

    def critical(self, message, **kwargs):
        self.log(logging.CRITICAL, message, **kwargs)

def log_performance(logger_or_func):
    """性能监控装饰器"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time

                # Handle both logger instance and logger factory function
                if callable(logger_or_func):
                    logger = logger_or_func()
                else:
                    logger = logger_or_func

                logger.debug(
                    f"Function {func.__name__} completed",
                    duration=duration,
                    success=True,
                    module=func.__module__,
                    function=func.__name__
                )
                return result
            except Exception as e:
                duration = time.time() - start_time

                # Handle both logger instance and logger factory function
                if callable(logger_or_func):
                    logger = logger_or_func()
                else:
                    logger = logger_or_func

                logger.error(
                    f"Function {func.__name__} failed: {str(e)}",
                    duration=duration,
                    success=False,
                    error=str(e),
                    module=func.__module__,
                    function=func.__name__
                )
                raise
        return wrapper
    return decorator

def setup_logger(username: str, log_dir: str = None, use_structured: bool = None, use_async: bool = None, enable_stats: bool = None, config_file: str = None, environment: str = None):
    """
    配置全局日志系统。
    - username: 当前运行的用户，用于命名日志文件。
    - log_dir: 日志存储目录（可选，会被配置覆盖）。
    - use_structured: 是否使用结构化日志（可选，会被配置覆盖）。
    - use_async: 是否使用异步日志（可选，会被配置覆盖）。
    - enable_stats: 是否启用日志统计（可选，会被配置覆盖）。
    - config_file: 配置文件路径。
    - environment: 环境名称（development, staging, production）。
    
    支持的环境变量：
    - LOG_LEVEL: 全局日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
    - LOG_MODULE_LEVELS: 模块级别覆盖，格式 "module1:DEBUG,module2:WARNING"
    """
    global _global_context_logger

    # 获取配置
    config = get_full_config(environment, config_file)

    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    env_level_name = os.getenv("LOG_LEVEL")
    configured_level_name = env_level_name or config.get("log_level", "INFO")
    global_level = level_map.get(str(configured_level_name).upper(), logging.INFO)

    # 强制控制台使用UTF-8编码（Windows）
    if config.get("force_utf8_console", True):
        force_utf8_console()

    # 参数覆盖配置
    if log_dir is not None:
        config["log_dir"] = log_dir
    if use_structured is not None:
        config["use_structured"] = use_structured
    if use_async is not None:
        config["use_async"] = use_async
    if enable_stats is not None:
        config["enable_stats"] = enable_stats

    log_file = os.path.join(config["log_dir"], f"{username}.log")

    # 获取根日志记录器
    logger = logging.getLogger()
    logger.setLevel(global_level)

    # 避免重复添加 Handler (防止多次初始化)
    if logger.handlers:
        context_logger = ContextLogger(logger)
        context_logger.set_context(user=username)
        _setup_module_levels(context_logger, config)

        _global_context_logger = context_logger
        return context_logger

    # 文件格式器：按配置决定是否 JSON
    if config["use_structured"]:
        file_formatter = StructuredFormatter()
    else:
        file_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    # 控制台格式器：永远使用增强可读性的文本
    console_formatter = logging.Formatter(
        '[%(levelname)s] %(message)s'
    )

    # Handler 1: 轮转文件输出
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=config["max_file_size"],
        backupCount=config["backup_count"],
        encoding=config["encoding"]
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.NOTSET)
    logger.addHandler(file_handler)

    # Handler 2: 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.NOTSET)
    logger.addHandler(console_handler)

    # 设置异步日志
    async_logger = None
    if config["use_async"]:
        async_logger = AsyncLogger(logger, config)

    # 设置统计收集
    statistics = None
    async_stats_processor = None
    if config["enable_stats"]:
        statistics = LogStatistics()
        # 使用异步统计处理
        stats_queue = queue.Queue(maxsize=1000)
        stats_handler = StatisticsHandler(statistics, queue=stats_queue)
        stats_handler.setLevel(logging.DEBUG)
        logger.addHandler(stats_handler)

        # 启动异步统计处理器
        async_stats_processor = AsyncStatisticsProcessor(stats_queue, statistics)
        async_stats_processor.start()

    # 返回上下文日志器
    context_logger = ContextLogger(logger, async_logger, statistics)
    context_logger.set_context(user=username)
    
    # 从环境变量和配置加载模块级别
    _setup_module_levels(context_logger, config)

    # 设置全局单例
    _global_context_logger = context_logger

    return context_logger

def _setup_module_levels(context_logger, config=None):
    """从配置和环境变量设置模块级别
    
    优先级：
    1. 环境变量 LOG_MODULE_LEVELS (最高)
    2. 代码中设置的 module_levels 配置
    3. 全局日志级别 (最低)
    """
    level_map = {
        "DEBUG": logging.DEBUG,      # 10
        "INFO": logging.INFO,        # 20
        "WARNING": logging.WARNING,  # 30
        "ERROR": logging.ERROR,      # 40
        "CRITICAL": logging.CRITICAL # 50
    }
    
    module_levels = {}

    # 1. 先加载配置文件中的默认模块级别
    config_module_levels = (config or {}).get("module_levels", {})
    if isinstance(config_module_levels, dict):
        for module_name, level_name in config_module_levels.items():
            if isinstance(level_name, str):
                level_num = level_map.get(level_name.strip().upper())
                if level_num is not None:
                    module_levels[module_name.strip()] = level_num
            elif isinstance(level_name, int):
                module_levels[module_name.strip()] = level_name

    # 2. 再用环境变量覆盖：格式 "module1:DEBUG,module2:WARNING"
    env_module_levels = os.getenv("LOG_MODULE_LEVELS", "")
    if env_module_levels:
        try:
            for pair in env_module_levels.split(","):
                if not pair.strip():
                    continue
                module_name, level_name = pair.strip().split(":", 1)
                level_num = level_map.get(level_name.strip().upper())
                if level_num is not None:
                    module_levels[module_name.strip()] = level_num
        except (ValueError, KeyError):
            pass  # 忽略格式错误
    
    if module_levels:
        context_logger.set_module_levels(module_levels)

# 便捷获取 logger 的函数
def get_logger():
    global _global_context_logger
    if _global_context_logger is None:
        # If setup_logger hasn't been called yet, create a basic ContextLogger
        # This ensures get_logger() works even if called before setup_logger()
        _global_context_logger = ContextLogger(logging.getLogger())
    return _global_context_logger
