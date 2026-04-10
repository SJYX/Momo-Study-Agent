#!/usr/bin/env python3
"""
日志系统配置文件
"""
import os

# 日志配置
LOG_CONFIG = {
    # 基础配置
    "log_dir": "logs",
    "max_file_size": 10 * 1024 * 1024,  # 10MB
    "backup_count": 5,
    "encoding": "utf-8",

    # 日志级别
    "console_level": "INFO",
    "file_level": "DEBUG",

    # 功能开关
    "use_structured": True,
    "use_async": False,
    "enable_stats": False,

    # 异步日志配置
    "async_queue_size": 1000,

    # 性能监控配置
    "performance_threshold": 1.0,  # 秒，超过此时间记录警告

    # 统计配置
    "stats_reset_interval": 3600,  # 秒，统计重置间隔

    # 压缩配置
    "enable_compression": False,
    "compression_format": "gzip",  # gzip, zip, bz2
    "compress_after_days": 7,

    # 环境配置
    "environment": "development",  # development, staging, production

    # 高级配置
    "buffer_size": 8192,
    "flush_interval": 1.0,  # 秒
    "max_workers": 2,  # 异步处理线程数
}

# 环境特定配置
ENV_CONFIGS = {
    "development": {
        "console_level": "DEBUG",
        "use_async": False,
        "enable_stats": True,
        "enable_compression": False,
    },
    "staging": {
        "console_level": "INFO",
        "use_async": True,
        "enable_stats": True,
        "enable_compression": True,
        "compress_after_days": 3,
    },
    "production": {
        "console_level": "WARNING",
        "use_async": True,
        "enable_stats": False,
        "enable_compression": True,
        "compress_after_days": 7,
        "max_workers": 4,
    }
}

def get_config(environment=None):
    """
    获取配置，根据环境合并配置
    """
    config = LOG_CONFIG.copy()

    if environment:
        env_config = ENV_CONFIGS.get(environment, {})
        config.update(env_config)
    else:
        # 使用默认环境
        env_config = ENV_CONFIGS.get(config["environment"], {})
        config.update(env_config)

    return config

def load_yaml_config(config_file="config/logging.yaml"):
    """
    从YAML文件加载配置
    """
    try:
        import yaml
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f)
                return yaml_config
    except ImportError:
        pass  # 如果没有yaml库，使用默认配置

    return {}

def save_yaml_config(config, config_file="config/logging.yaml"):
    """
    保存配置到YAML文件
    """
    try:
        import yaml
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    except ImportError:
        print("警告：未安装PyYAML，无法保存YAML配置")

def merge_configs(base_config, override_config):
    """
    递归合并配置字典
    """
    result = base_config.copy()

    for key, value in override_config.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value

    return result

def get_full_config(environment=None, config_file=None):
    """
    获取完整配置：默认配置 + 环境配置 + YAML文件配置
    """
    # 基础配置
    config = LOG_CONFIG.copy()

    # 环境配置
    if environment:
        env_config = ENV_CONFIGS.get(environment, {})
        config.update(env_config)

    # YAML文件配置
    if config_file:
        yaml_config = load_yaml_config(config_file)
        config = merge_configs(config, yaml_config)

    return config