"""
请求限速器
- 控制 OKX API 请求频率，避免触发限流
- OKX 限速：40 次/2s（按 User ID）
- 使用滑动窗口算法
"""
import time
import threading
from collections import deque
import logging

logger = logging.getLogger('RateLimiter')


class RateLimiter:
    """滑动窗口限速器"""

    def __init__(self, max_calls=35, window_seconds=2):
        """
        :param max_calls: 窗口内最大请求数（留 5 次余量）
        :param window_seconds: 窗口大小（秒）
        """
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.calls = deque()
        self.lock = threading.Lock()

    def acquire(self):
        """获取一个请求配额，如果超限则等待"""
        with self.lock:
            now = time.time()
            
            # 清理过期记录
            while self.calls and self.calls[0] < now - self.window_seconds:
                self.calls.popleft()
            
            if len(self.calls) >= self.max_calls:
                # 计算需要等待的时间
                wait_time = self.window_seconds - (now - self.calls[0])
                if wait_time > 0:
                    logger.info(f'Rate limit reached, waiting {wait_time:.2f}s')
                    time.sleep(wait_time)
                    # 重新清理
                    now = time.time()
                    while self.calls and self.calls[0] < now - self.window_seconds:
                        self.calls.popleft()
            
            self.calls.append(now)

    def get_status(self):
        """获取当前限速状态"""
        with self.lock:
            now = time.time()
            while self.calls and self.calls[0] < now - self.window_seconds:
                self.calls.popleft()
            return {
                'current_calls': len(self.calls),
                'max_calls': self.max_calls,
                'window_seconds': self.window_seconds,
            }


# 全局限速器实例（OKX 公共 API：40 次/2s，留余量设为 35）
okx_rate_limiter = RateLimiter(max_calls=35, window_seconds=2)
