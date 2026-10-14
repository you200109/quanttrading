"""
自进化交易系统 - 进化引擎模块

实现 400 轮迭代 + 7 天内化的自进化学习循环：
- 策略基因编码与变异
- 适应度评估与自然选择
- 强化学习在线进化

说明: GitHub 学习能力已统一整合到根目录 learning_engine.py
"""

from .learning_loop import EvolutionEngine
from .rl_environment import TradingEnvConfig, TradingEnvironment

try:
    from .rl_trainer import RLTrainer
except (ImportError, NameError):
    RLTrainer = None  # SB3 未安装时降级

__all__ = [
    "EvolutionEngine",
    "TradingEnvironment",
    "TradingEnvConfig",
    "RLTrainer",
]
