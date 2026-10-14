"""
自进化交易系统 - 策略模块

基于 backtrader + vectorbt 的策略框架，支持：
- 多策略并行运行
- 策略参数自动优化
- 策略表现评估与排名
"""

from .base_strategy import BaseStrategy

__all__ = ["BaseStrategy"]
