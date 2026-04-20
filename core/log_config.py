"""
core/log_config.py: 日志系统配置与参数定义。
"""
#!/usr/bin/env python3

import os

# 基础日志配置
LOG_CONFIG = {
    "log_dir": "logs",
    "max_file_size": 10 * 1024 * 1024,  # 10MB
    "backup_count": 5,
    "encoding": "utf-8",
    "log_level": "INFO",
    "console_level": "INFO",
    "file_level": "DEBUG",
    "module_levels": {},
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
    "force_utf8_console": True,
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
    },
}


def get_config(environment=None):
    """获取配置，根据环境合并配置。"""
    config = LOG_CONFIG.copy()
    if environment:
        config.update(ENV_CONFIGS.get(environment, {}))
    else:
        config.update(ENV_CONFIGS.get(config["environment"], {}))
    return config


def load_yaml_config(config_file="config/logging.yaml"):
    """从 YAML 文件加载配置。"""
    try:
        import yaml

        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except ImportError:
        pass
    return {}


def save_yaml_config(config, config_file="config/logging.yaml"):
    """保存配置到 YAML 文件。"""
    try:
        import yaml

        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    except ImportError:
        print("警告：未安装PyYAML，无法保存YAML配置")


def merge_configs(base_config, override_config):
    """递归合并配置字典。"""
    result = base_config.copy()
    for key, value in (override_config or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


def get_full_config(environment=None, config_file=None):
    """获取完整配置：默认配置 + 环境配置 + YAML 文件配置。"""
    config = LOG_CONFIG.copy()
    if environment:
        config.update(ENV_CONFIGS.get(environment, {}))
    if config_file:
        config = merge_configs(config, load_yaml_config(config_file))
    return config

