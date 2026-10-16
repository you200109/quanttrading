"""
强化学习交易环境 - OpenAI Gym 风格

用于训练 RL Agent 在加密货币市场中做出交易决策。
支持：
- 多时间框架观察
- 离散和连续动作空间
- 交易成本建模
- 风险调整奖励
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)

try:
    import gymnasium as gym
    from gymnasium import spaces
    HAS_GYM = True
except ImportError:
    HAS_GYM = False
    logger.warning("gymnasium 未安装，RL 环境将不可用")


@dataclass
class TradingEnvConfig:
    """交易环境配置"""
    initial_capital: float = 100000
    commission: float = 0.001  # 0.1% 手续费
    slippage: float = 0.0005   # 0.05% 滑点
    window_size: int = 60      # 观察窗口大小
    max_position: float = 1.0  # 最大仓位比例
    reward_scaling: float = 1.0
    risk_aversion: float = 0.1  # 风险厌恶系数


class TradingEnvironment(gym.Env if HAS_GYM else object):
    """
    加密货币交易强化学习环境

    观察空间：价格、成交量、技术指标的历史窗口
    动作空间：0=空仓, 1=买入, 2=卖出, 3=持有
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        data: pd.DataFrame,
        config: TradingEnvConfig | None = None,
        render_mode: str | None = None
    ):
        super().__init__()

        self.data = data
        self.config = config or TradingEnvConfig()
        self.render_mode = render_mode

        # 预计算技术指标
        self._precompute_indicators()

        # 状态变量
        self.current_step = 0
        self.capital = self.config.initial_capital
        self.position = 0.0
        self.entry_price = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.trade_history = []
        self.portfolio_history = []

        # 观察和动作空间
        n_features = self.features.shape[1] if hasattr(self, 'features') else 10

        if HAS_GYM:
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf,
                shape=(self.config.window_size, n_features),
                dtype=np.float32
            )
            self.action_space = spaces.Discrete(4)  # 0=空仓, 1=买入, 2=卖出, 3=持有

        self.max_steps = len(data) - self.config.window_size - 1

    def _precompute_indicators(self):
        """预计算技术指标"""
        df = self.data.copy()
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values
        n = len(close)

        # 收益率
        returns = np.diff(close, prepend=close[0]) / (close + 1e-8)

        close_s = pd.Series(close)

        # RSI (14)（K2：pandas-ta）
        rsi_series = ta.rsi(close_s, length=14)
        rsi = np.full(n, np.nan) if rsi_series is None else rsi_series.to_numpy()

        # MACD（K2：pandas-ta；列序 [MACD, 柱, 信号]）
        macd_df = ta.macd(close_s)
        if macd_df is None:
            macd = np.full(n, np.nan)
            macd_signal = np.full(n, np.nan)
        else:
            macd = macd_df.iloc[:, 0].to_numpy()
            macd_signal = macd_df.iloc[:, 2].to_numpy()
        macd_hist = macd - macd_signal

        # 布林带（K2：pandas-ta；列序 [BBL, BBM, BBU, BBB, BBP]）
        bb_df = ta.bbands(close_s, length=20, std=2.0)
        if bb_df is None:
            bb_upper = np.full(n, np.nan)
            bb_lower = np.full(n, np.nan)
        else:
            bb_upper = bb_df.iloc[:, 2].to_numpy()
            bb_lower = bb_df.iloc[:, 0].to_numpy()
        bb_position = (close - bb_lower) / (bb_upper - bb_lower + 1e-8)

        # ATR（K2：pandas-ta）
        atr_series = ta.atr(pd.Series(high), pd.Series(low), close_s, length=14)
        atr = np.full(n, np.nan) if atr_series is None else atr_series.to_numpy()

        # 成交量变化
        vol_sma_series = ta.sma(pd.Series(volume), length=20)
        vol_sma = np.full(n, np.nan) if vol_sma_series is None else vol_sma_series.to_numpy()
        vol_ratio = volume / (vol_sma + 1e-8)

        # 价格变化率
        price_change_5 = pd.Series(close).pct_change(5).values
        price_change_10 = pd.Series(close).pct_change(10).values

        # 组合特征矩阵
        self.features = np.column_stack([
            close / close[0],           # 归一化价格
            returns,                     # 收益率
            rsi / 100,                   # RSI 归一化
            macd / (close + 1e-8) * 100, # MACD 归一化
            macd_hist / (close + 1e-8) * 100,
            bb_position,                 # 布林带位置
            atr / (close + 1e-8),        # ATR 归一化
            vol_ratio,                   # 成交量比率
            price_change_5,              # 5日涨跌
            price_change_10,             # 10日涨跌
        ])

        # 填充 NaN
        self.features = np.nan_to_num(self.features, nan=0.0)
        self.prices = close

    def _get_observation(self) -> np.ndarray:
        """获取当前观察"""
        start = max(0, self.current_step - self.config.window_size + 1)
        end = self.current_step + 1
        obs = self.features[start:end]

        # 填充到固定窗口大小
        if len(obs) < self.config.window_size:
            padding = np.zeros((self.config.window_size - len(obs), obs.shape[1]))
            obs = np.vstack([padding, obs])

        return obs.astype(np.float32)

    def _get_portfolio_value(self) -> float:
        """计算当前组合价值"""
        price = self.prices[self.current_step]
        position_value = self.position * price
        return self.capital + position_value

    def reset(self, seed=None, options=None) -> tuple[np.ndarray, dict]:
        """重置环境"""
        super().reset(seed=seed)

        self.current_step = self.config.window_size
        self.capital = self.config.initial_capital
        self.position = 0.0
        self.entry_price = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.trade_history = []
        self.portfolio_history = [self.config.initial_capital]

        return self._get_observation(), {}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        """执行一步交易

        Args:
            action: 0=空仓, 1=买入, 2=卖出, 3=持有
        """
        price = self.prices[self.current_step]
        prev_value = self._get_portfolio_value()

        # 执行动作
        if action == 1 and self.position == 0:  # 买入
            max_invest = self.capital * self.config.max_position
            cost = max_invest * (1 + self.config.commission + self.config.slippage)
            if cost <= self.capital:
                self.position = max_invest / price
                self.entry_price = price
                self.capital -= cost
                self.total_trades += 1

        elif action == 2 and self.position > 0:  # 卖出
            revenue = self.position * price * (1 - self.config.commission - self.config.slippage)
            pnl = revenue - self.position * self.entry_price
            self.capital += revenue
            self.position = 0

            if pnl > 0:
                self.winning_trades += 1
            self.trade_history.append(pnl)

        # 移动到下一步
        self.current_step += 1
        done = self.current_step >= len(self.prices) - 1

        # 计算奖励（优化版）
        current_value = self._get_portfolio_value()
        step_return = (current_value - prev_value) / (prev_value + 1e-8)

        # 1. 基础收益奖励
        reward = step_return * 100  # 放大收益率信号

        # 2. 夏普比率奖励（基于最近交易）
        if len(self.trade_history) >= 3:
            recent = self.trade_history[-20:]
            avg_ret = np.mean(recent)
            std_ret = np.std(recent) if len(recent) > 1 else 0.01
            sharpe = avg_ret / (std_ret + 1e-8)
            reward += sharpe * 0.5  # 夏普比率越高越好

        # 3. 回撤惩罚
        if len(self.portfolio_history) > 10:
            recent_values = np.array(self.portfolio_history[-20:])
            peak = np.max(recent_values)
            current_dd = (peak - current_value) / (peak + 1e-8)
            reward -= current_dd * 2.0  # 回撤越大惩罚越重

        # 4. 胜率奖励
        if self.total_trades > 0:
            win_rate = self.winning_trades / self.total_trades
            reward += win_rate * 0.3

        # 5. 持仓奖励（鼓励持有仓位）
        if self.position > 0:
            reward += 0.01  # 持仓给予小额正向奖励

        # 6. 不交易惩罚（长时间空仓给予负奖励）
        steps_since_last_trade = self.current_step - self.config.window_size
        if self.total_trades == 0 and steps_since_last_trade > 50:
            reward -= 0.02  # 超过 50 步不交易开始惩罚

        # 7. 交易频率控制（避免过度交易）
        if self.total_trades > 0:
            trade_freq = self.total_trades / max(1, self.current_step - self.config.window_size)
            if trade_freq > 0.15:
                reward -= (trade_freq - 0.15) * 3.0

        # 6. 终止时综合奖励
        if done:
            total_return = (current_value - self.config.initial_capital) / self.config.initial_capital
            # 计算完整回测的夏普比率
            if len(self.trade_history) >= 3:
                final_sharpe = np.mean(self.trade_history) / (np.std(self.trade_history) + 1e-8) * np.sqrt(252)
                reward += final_sharpe * 2.0
            # 最终收益奖励
            reward += total_return * 20.0
            # 最大回撤惩罚
            values = np.array(self.portfolio_history)
            peak = np.maximum.accumulate(values)
            max_dd = np.max((peak - values) / (peak + 1e-8))
            reward -= max_dd * 10.0

        self.portfolio_history.append(current_value)

        info = {
            'portfolio_value': current_value,
            'position': self.position,
            'capital': self.capital,
            'price': price,
            'total_trades': self.total_trades,
            'win_rate': self.winning_trades / max(1, self.total_trades)
        }

        return self._get_observation(), reward, done, False, info

    def render(self):
        """渲染当前状态"""
        if self.render_mode == "human":
            value = self._get_portfolio_value()
            ret = (value - self.config.initial_capital) / self.config.initial_capital
            print(
                f"Step: {self.current_step} | "
                f"Price: ${self.prices[self.current_step]:,.2f} | "
                f"Value: ${value:,.2f} | "
                f"Return: {ret:+.2%} | "
                f"Position: {self.position:.4f} | "
                f"Trades: {self.total_trades}"
            )

    def get_performance(self) -> dict:
        """获取性能指标"""
        value = self._get_portfolio_value()
        total_return = (value - self.config.initial_capital) / self.config.initial_capital

        if len(self.trade_history) > 1:
            sharpe = np.mean(self.trade_history) / (np.std(self.trade_history) + 1e-8) * np.sqrt(252)
            max_dd = self._calculate_max_drawdown()
        else:
            sharpe = 0
            max_dd = 0

        return {
            'total_return': total_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'total_trades': self.total_trades,
            'win_rate': self.winning_trades / max(1, self.total_trades),
            'final_value': value
        }

    def _calculate_max_drawdown(self) -> float:
        """计算最大回撤"""
        values = np.array(self.portfolio_history)
        running_max = np.maximum.accumulate(values)
        drawdown = (running_max - values) / (running_max + 1e-8)
        return np.max(drawdown) if len(drawdown) > 0 else 0
