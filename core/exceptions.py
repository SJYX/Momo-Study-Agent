"""
core/exceptions.py: 业务异常类型定义，细化错误处理与抛出语义。
"""
# -*- coding: utf-8 -*-
"""
自定义异常类
提供更细粒度的错误处理
"""


class MomoBaseException(Exception):
    """Momo Study Agent 基础异常类"""

    def __init__(self, message: str, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self):
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


# ============================================================================
# 数据库相关异常 (Database Exceptions)
# ============================================================================


class DatabaseError(MomoBaseException):
    """数据库操作错误"""

    pass


class DatabaseConnectionError(DatabaseError):
    """数据库连接失败"""

    pass


class DatabaseInitError(DatabaseError):
    """数据库初始化失败"""

    pass


class DatabaseSyncError(DatabaseError):
    """数据库同步失败"""

    pass


# ============================================================================
# API 相关异常 (API Exceptions)
# ============================================================================


class APIError(MomoBaseException):
    """API 调用错误"""

    pass


class APIRateLimitError(APIError):
    """API 请求频率限制"""

    def __init__(self, message: str, retry_after: int = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class APIAuthError(APIError):
    """API 认证失败"""

    pass


class APIQuotaExceededError(APIError):
    """API 配额超限"""

    pass


class APITimeoutError(APIError):
    """API 请求超时"""

    pass


class APIResponseError(APIError):
    """API 响应格式错误"""

    pass


# ============================================================================
# AI 相关异常 (AI Exceptions)
# ============================================================================


class AIError(MomoBaseException):
    """AI 处理错误"""

    pass


class AIGenerationError(AIError):
    """AI 生成内容失败"""

    pass


class AIParsingError(AIError):
    """AI 响应解析失败"""

    pass


class AIModelNotAvailableError(AIError):
    """AI 模型不可用"""

    pass


# ============================================================================
# 配置相关异常 (Configuration Exceptions)
# ============================================================================


class ConfigError(MomoBaseException):
    """配置错误"""

    pass


class ConfigValidationError(ConfigError):
    """配置验证失败"""

    pass


class ConfigMissingError(ConfigError):
    """配置缺失"""

    pass


# ============================================================================
# 用户相关异常 (User Exceptions)
# ============================================================================


class UserError(MomoBaseException):
    """用户操作错误"""

    pass


class UserNotFoundError(UserError):
    """用户不存在"""

    pass


class UserAuthError(UserError):
    """用户认证失败"""

    pass


class UserPermissionError(UserError):
    """用户权限不足"""

    pass


# ============================================================================
# 数据处理异常 (Data Processing Exceptions)
# ============================================================================


class DataError(MomoBaseException):
    """数据处理错误"""

    pass


class DataValidationError(DataError):
    """数据验证失败"""

    pass


class DataParsingError(DataError):
    """数据解析失败"""

    pass


class DataNotFoundError(DataError):
    """数据不存在"""

    pass
