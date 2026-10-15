"""
系统弹性增强模块
- 熔断器：防止连续失败导致雪崩
- 幂等性：防止重复下单
- 优雅关闭：安全释放资源
- 资源限制：控制内存和 CPU 使用
"""
import os
import time
import signal
import hashlib
import logging
import threading
from functools import wraps
from typing import Dict, Optional, Callable, Any

logger = logging.getLogger('Resilience')


# ==================== 熔断器 ====================

class CircuitBreaker:
    """熔断器：防止连续失败导致雪崩

    状态：CLOSED（正常）→ OPEN（熔断）→ HALF_OPEN（半开试探）→ CLOSED
    """

    def __init__(self, failure_threshold=5, recovery_timeout=60, expected_exception=Exception):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failures = 0
        self.last_failure_time = None
        self.state = 'CLOSED'
        self._lock = threading.Lock()

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """通过熔断器调用函数"""
        with self._lock:
            if self.state == 'OPEN':
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    logger.info('Circuit breaker: OPEN -> HALF_OPEN')
                    self.state = 'HALF_OPEN'
                else:
                    raise Exception(f'Circuit breaker is OPEN (failures={self.failures})')

        try:
            result = func(*args, **kwargs)
            with self._lock:
                if self.state == 'HALF_OPEN':
                    logger.info('Circuit breaker: HALF_OPEN -> CLOSED')
                    self.state = 'CLOSED'
                    self.failures = 0
            return result
        except self.expected_exception as e:
            with self._lock:
                self.failures += 1
                self.last_failure_time = time.time()
                if self.failures >= self.failure_threshold:
                    logger.warning(f'Circuit breaker: CLOSED -> OPEN (failures={self.failures})')
                    self.state = 'OPEN'
            raise

    def get_state(self) -> Dict:
        return {
            'state': self.state,
            'failures': self.failures,
            'failure_threshold': self.failure_threshold,
            'recovery_timeout': self.recovery_timeout,
        }


# OKX API 熔断器实例
okx_circuit_breaker = CircuitBreaker(failure_threshold=10, recovery_timeout=30)


# ==================== 幂等性 ====================

class IdempotencyManager:
    """幂等性管理器：防止重复操作

    使用内存缓存（生产环境可替换为 Redis）
    """

    def __init__(self, ttl_seconds=86400):
        self._cache: Dict[str, tuple] = {}  # key -> (result, expire_time)
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_seconds

    def _generate_key(self, *args, **kwargs) -> str:
        """生成幂等键"""
        data = str((args, sorted(kwargs.items())))
        return hashlib.md5(data.encode()).hexdigest()

    def execute(self, key: str, func: Callable, *args, **kwargs) -> Any:
        """幂等执行：相同 key 只执行一次"""
        with self._lock:
            # 清理过期缓存
            now = time.time()
            expired = [k for k, (_, exp) in self._cache.items() if exp < now]
            for k in expired:
                del self._cache[k]

            # 检查是否已执行
            if key in self._cache:
                result, _ = self._cache[key]
                logger.info(f'Idempotent hit: key={key[:8]}...')
                return result

        # 执行函数
        result = func(*args, **kwargs)

        with self._lock:
            self._cache[key] = (result, time.time() + self.ttl_seconds)

        return result

    def is_processed(self, key: str) -> bool:
        """检查是否已处理"""
        with self._lock:
            return key in self._cache


# 全局幂等管理器
idempotency_manager = IdempotencyManager(ttl_seconds=86400)


# ==================== 优雅关闭 ====================

class GracefulShutdown:
    """优雅关闭管理器"""

    def __init__(self):
        self._cleanup_handlers = []
        self._shutting_down = False
        self._lock = threading.Lock()

    def register_cleanup(self, handler: Callable, name: str = ''):
        """注册清理函数"""
        self._cleanup_handlers.append((name or handler.__name__, handler))
        logger.info(f'Registered cleanup handler: {name}')

    def shutdown(self):
        """执行优雅关闭"""
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True

        logger.info('Graceful shutdown started...')

        for name, handler in reversed(self._cleanup_handlers):
            try:
                logger.info(f'Running cleanup: {name}')
                handler()
            except Exception as e:
                logger.error(f'Cleanup {name} failed: {e}')

        logger.info('Graceful shutdown complete.')

    def setup_signal_handlers(self):
        """注册信号处理器"""
        def handler(signum, frame):
            logger.info(f'Received signal {signum}, initiating graceful shutdown...')
            self.shutdown()

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down


# 全局优雅关闭管理器
graceful_shutdown = GracefulShutdown()


# ==================== 资源限制 ====================

class ResourceLimiter:
    """资源限制器"""

    def __init__(self, max_memory_mb=512, max_cpu_seconds=300):
        self.max_memory_mb = max_memory_mb
        self.max_cpu_seconds = max_cpu_seconds

    def check_memory(self) -> Dict:
        """检查内存使用"""
        try:
            import psutil
            process = psutil.Process()
            mem_info = process.memory_info()
            mem_mb = mem_info.rss / 1024 / 1024
            pct = mem_mb / self.max_memory_mb * 100
            return {
                'memory_mb': round(mem_mb, 1),
                'max_mb': self.max_memory_mb,
                'usage_pct': round(pct, 1),
                'exceeded': mem_mb > self.max_memory_mb,
            }
        except ImportError:
            return {'error': 'psutil not installed', 'memory_mb': 0, 'usage_pct': 0, 'exceeded': False}

    def check_cpu(self) -> Dict:
        """检查 CPU 使用"""
        try:
            import psutil
            process = psutil.Process()
            cpu_pct = process.cpu_percent(interval=0.1)
            return {
                'cpu_pct': cpu_pct,
                'max_pct': 100,
                'exceeded': cpu_pct > 90,
            }
        except ImportError:
            return {'error': 'psutil not installed', 'cpu_pct': 0, 'exceeded': False}

    def get_status(self) -> Dict:
        """获取资源使用状态"""
        return {
            'memory': self.check_memory(),
            'cpu': self.check_cpu(),
        }


# 全局资源限制器
resource_limiter = ResourceLimiter(max_memory_mb=512, max_cpu_seconds=300)


# ==================== 装饰器便捷函数 ====================

def with_circuit_breaker(breaker: CircuitBreaker = None):
    """熔断器装饰器"""
    breaker = breaker or okx_circuit_breaker
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator


def with_idempotency(ttl_seconds=86400):
    """幂等性装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = idempotency_manager._generate_key(func.__name__, *args, **kwargs)
            return idempotency_manager.execute(key, func, *args, **kwargs)
        return wrapper
    return decorator
