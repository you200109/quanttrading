"""
强化学习训练器 - PPO/DQN 交易 Agent

使用 Stable-Baselines3 在真实市场数据上训练 RL Agent，
替代传统遗传算法，实现在线自进化。
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    from stable_baselines3 import DQN, PPO
    from stable_baselines3.common.callbacks import BaseCallback
    from stable_baselines3.common.vec_env import DummyVecEnv
    HAS_SB3 = True
except ImportError:
    HAS_SB3 = False
    BaseCallback = object  # 占位基类，避免 NameError
    logger.warning("stable-baselines3 未安装，RL 训练功能不可用")

from .rl_environment import TradingEnvConfig, TradingEnvironment


class TrainingCallback(BaseCallback):
    """训练回调 - 记录训练进度"""

    def __init__(self, verbose=0):
        super().__init__(verbose)
        self.episode_rewards = []
        self.episode_lengths = []

    def _on_step(self) -> bool:
        if self.locals.get('dones'):
            for i, done in enumerate(self.locals['dones']):
                if done:
                    info = self.locals['infos'][i]
                    self.episode_rewards.append(info.get('portfolio_value', 0))
        return True


class RLTrainer:
    """RL 训练器

    支持 PPO 和 DQN 算法，在历史数据上训练交易策略。
    """

    def __init__(
        self,
        algorithm: str = "PPO",
        model_dir: str = "memory/nexus/rl_models"
    ):
        self.algorithm = algorithm
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.model = None
        self.env = None
        self.training_history: list[dict] = []

    def create_env(self, data: pd.DataFrame, config: TradingEnvConfig | None = None):
        """创建交易环境"""
        env_config = config or TradingEnvConfig(
            initial_capital=100000,
            window_size=60,
            max_position=1.0
        )

        def make_env():
            return TradingEnvironment(data, env_config)

        self.env = DummyVecEnv([make_env])
        return self.env

    def train(
        self,
        data: pd.DataFrame,
        total_timesteps: int = 100000,
        learning_rate: float = 0.0003,
        batch_size: int = 64,
        verbose: int = 1
    ) -> dict:
        """训练 RL Agent

        Args:
            data: 历史行情数据
            total_timesteps: 总训练步数
            learning_rate: 学习率
            batch_size: 批次大小
            verbose: 日志级别

        Returns:
            训练结果字典
        """
        if not HAS_SB3:
            logger.error("stable-baselines3 未安装")
            return {'error': 'SB3 not installed'}

        # 创建环境
        self.create_env(data)

        # 创建模型
        if self.algorithm == "PPO":
            self.model = PPO(
                "MlpPolicy",
                self.env,
                learning_rate=learning_rate,
                batch_size=batch_size,
                verbose=verbose,
                tensorboard_log=None
            )
        elif self.algorithm == "DQN":
            self.model = DQN(
                "MlpPolicy",
                self.env,
                learning_rate=learning_rate,
                batch_size=batch_size,
                verbose=verbose,
                tensorboard_log=None
            )
        else:
            raise ValueError(f"不支持的算法: {self.algorithm}")

        # 训练
        logger.info(f"开始训练 {self.algorithm}，总步数: {total_timesteps}")
        start_time = datetime.now()

        callback = TrainingCallback()
        self.model.learn(
            total_timesteps=total_timesteps,
            callback=callback,
            progress_bar=False
        )

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"训练完成，耗时: {elapsed:.1f} 秒")

        # 保存模型
        model_path = self.model_dir / f"{self.algorithm.lower()}_btc_{datetime.now().strftime('%Y%m%d_%H%M')}"
        self.model.save(str(model_path))
        logger.info(f"模型已保存: {model_path}")

        # 评估
        eval_result = self.evaluate(data)

        result = {
            'algorithm': self.algorithm,
            'total_timesteps': total_timesteps,
            'training_time': elapsed,
            'model_path': str(model_path),
            'evaluation': eval_result,
            'timestamp': datetime.now().isoformat()
        }

        self.training_history.append(result)

        # 保存训练历史
        with open(self.model_dir / 'training_history.json', 'w', encoding='utf-8') as f:
            json.dump(self.training_history, f, indent=2, ensure_ascii=False)

        return result

    def evaluate(self, data: pd.DataFrame, n_episodes: int = 5) -> dict:
        """评估模型表现

        Args:
            data: 评估数据
            n_episodes: 评估回合数

        Returns:
            评估结果
        """
        if self.model is None:
            return {'error': 'No model loaded'}

        eval_env = TradingEnvironment(data, TradingEnvConfig(window_size=60))

        total_returns = []
        total_trades = []
        win_rates = []

        for _episode in range(n_episodes):
            obs, _ = eval_env.reset()
            done = False

            while not done:
                action, _ = self.model.predict(obs, deterministic=True)
                obs, reward, done, _, info = eval_env.step(action)

            perf = eval_env.get_performance()
            total_returns.append(perf['total_return'])
            total_trades.append(perf['total_trades'])
            win_rates.append(perf['win_rate'])

        return {
            'avg_return': np.mean(total_returns),
            'std_return': np.std(total_returns),
            'max_return': np.max(total_returns),
            'min_return': np.min(total_returns),
            'avg_trades': np.mean(total_trades),
            'avg_win_rate': np.mean(win_rates),
            'n_episodes': n_episodes
        }

    def load_model(self, model_path: str):
        """加载已训练的模型"""
        if self.algorithm == "PPO":
            self.model = PPO.load(model_path)
        elif self.algorithm == "DQN":
            self.model = DQN.load(model_path)
        logger.info(f"模型已加载: {model_path}")

    def predict(self, observation: np.ndarray) -> int:
        """预测动作"""
        if self.model is None:
            return 3  # 默认持有
        action, _ = self.model.predict(observation, deterministic=True)
        return int(action)

    def get_training_summary(self) -> str:
        """获取训练摘要"""
        if not self.training_history:
            return "暂无训练记录"

        latest = self.training_history[-1]
        eval_result = latest.get('evaluation', {})

        return f"""
{'='*50}
  RL 训练摘要
{'='*50}
算法: {latest['algorithm']}
训练步数: {latest['total_timesteps']:,}
训练时间: {latest['training_time']:.1f} 秒

评估结果:
  平均收益: {eval_result.get('avg_return', 0):.2%}
  最大收益: {eval_result.get('max_return', 0):.2%}
  平均交易: {eval_result.get('avg_trades', 0):.0f} 次
  平均胜率: {eval_result.get('avg_win_rate', 0):.1%}
"""
