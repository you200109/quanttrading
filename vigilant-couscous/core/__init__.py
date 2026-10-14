"""
核心基础设施模块

提供系统级基础能力：
- ErrorHandler - 统一错误处理和自动重试
- ConfigValidator - 启动时配置全面验证
- Database - SQLite 持久化存储
"""

from .config_validator import ConfigValidator, ValidationResult
from .database import Database, db
from .error_handler import ErrorHandler, ErrorRecord, ErrorSeverity, error_handler

__all__ = [
    "ErrorHandler", "ErrorSeverity", "ErrorRecord", "error_handler",
    "ConfigValidator", "ValidationResult",
    "Database", "db",
]
