"""
统一错误处理框架 - 系统级健壮性保障

提供：分级错误处理、自动重试（指数退避）、错误聚合去重、健康状态上报、优雅降级策略
"""

import functools
import json
import logging
import time
import traceback
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
ERROR_LOG = ROOT / "reports" / "errors.jsonl"
ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)


class ErrorSeverity(Enum):
    RECOVERABLE = "recoverable"
    DEGRADED = "degraded"
    RESTART_REQUIRED = "restart_required"
    FATAL = "fatal"


@dataclass
class ErrorRecord:
    error_type: str
    message: str
    severity: ErrorSeverity
    module: str
    function: str
    traceback: str
    timestamp: datetime = field(default_factory=datetime.now)
    retry_count: int = 0
    recovered: bool = False


class ErrorHandler:
    MAX_RETRIES = 3
    BASE_DELAY = 1.0
    MAX_DELAY = 60.0
    ERROR_WINDOW = timedelta(minutes=5)
    MAX_ERRORS_PER_WINDOW = 10

    def __init__(self):
        self.error_history: list[ErrorRecord] = []
        self.error_counts: dict[str, int] = defaultdict(int)
        self.last_errors: dict[str, datetime] = {}
        self.degraded_modules: set = set()

    def handle(self, error: Exception, module: str, function: str,
               severity: ErrorSeverity = ErrorSeverity.RECOVERABLE) -> ErrorRecord:
        error_key = f"{type(error).__name__}:{module}:{function}"
        self.error_counts[error_key] += 1
        self.last_errors[error_key] = datetime.now()
        record = ErrorRecord(
            error_type=type(error).__name__, message=str(error)[:500],
            severity=severity, module=module, function=function,
            traceback=traceback.format_exc()[-2000:],
        )
        self.error_history.append(record)
        if severity == ErrorSeverity.FATAL:
            logger.critical(f"致命错误 [{module}.{function}]: {error}")
        elif severity == ErrorSeverity.DEGRADED:
            logger.warning(f"降级错误 [{module}.{function}]: {error}")
            self.degraded_modules.add(module)
        else:
            logger.error(f"可恢复错误 [{module}.{function}]: {error}")
        self._save_record(record)
        return record

    def retry(self, max_retries: int = None, base_delay: float = None,
              exceptions: tuple = (Exception,)):
        max_retries = max_retries or self.MAX_RETRIES
        base_delay = base_delay or self.BASE_DELAY
        def decorator(func: Callable):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                last_error = None
                for attempt in range(max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_error = e
                        if attempt < max_retries:
                            delay = min(base_delay * (2 ** attempt), self.MAX_DELAY)
                            logger.warning(f"{func.__name__} 第{attempt+1}次重试，等待{delay:.1f}s: {e}")
                            time.sleep(delay)
                        else:
                            self.handle(e, func.__module__, func.__name__, ErrorSeverity.RECOVERABLE)
                raise last_error
            return wrapper
        return decorator

    def safe_call(self, func: Callable, *args, default_return: Any = None,
                  module: str = "unknown", **kwargs) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            self.handle(e, module, func.__name__, ErrorSeverity.RECOVERABLE)
            return default_return

    def is_healthy(self) -> bool:
        recent = sum(1 for e in self.error_history if datetime.now() - e.timestamp < self.ERROR_WINDOW)
        return recent < self.MAX_ERRORS_PER_WINDOW and len(self.degraded_modules) < 3

    def get_health_report(self) -> dict:
        recent = [e for e in self.error_history if datetime.now() - e.timestamp < self.ERROR_WINDOW]
        return {
            "status": "healthy" if self.is_healthy() else "degraded",
            "total_errors": len(self.error_history),
            "errors_5min": len(recent),
            "degraded_modules": list(self.degraded_modules),
            "top_errors": sorted(self.error_counts.items(), key=lambda x: x[1], reverse=True)[:5],
            "timestamp": datetime.now().isoformat(),
        }

    def _save_record(self, record: ErrorRecord):
        try:
            with open(ERROR_LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    "type": record.error_type, "message": record.message,
                    "severity": record.severity.value, "module": record.module,
                    "function": record.function, "timestamp": record.timestamp.isoformat(),
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass


error_handler = ErrorHandler()
