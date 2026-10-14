"""
策略回测引擎
- 支持多种策略：均线交叉、RSI超卖、布林带突破、MACD背离
- 基于历史K线数据进行事件驱动回测
- 输出收益统计、交易记录、绩效指标
"""
import pandas as pd
import numpy as np
import pandas_ta as ta
import logging
from typing import Dict, List, Optional

logger = logging.getLogger('BacktestEngine')


class BacktestEngine:
    """策略回测引擎"""

    def __init__(self, initial_capital=100000, commission_rate=0.001, slippage=0.0001):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage

    def run(self, df: pd.DataFrame, strategy: str, params: Dict) -> Dict:
        """运行回测
        :param df: K线数据，需包含 open/high/low/close/volume 列
        :param strategy: 策略名称
        :param params: 策略参数
        :return: 回测结果
        """
        logger.info(f'Running backtest: {strategy} with params {params}')

        # 生成信号
        signals = self._generate_signals(df, strategy, params)
        if signals is None:
            return {'code': 1, 'msg': f'Unknown strategy: {strategy}'}

        # 模拟交易
        result = self._simulate_trades(df, signals)
        result['strategy'] = strategy
        result['params'] = params

        logger.info(f'Backtest complete: {result["total_trades"]} trades, return: {result["total_return_pct"]:.2f}%')
        return result

    def _generate_signals(self, df: pd.DataFrame, strategy: str, params: Dict) -> Optional[pd.Series]:
        """生成交易信号：1=买入，-1=卖出，0=持有"""
        if strategy == 'ma_cross':
            fast = int(params.get('fast', 5))
            slow = int(params.get('slow', 20))
            df['ma_fast'] = ta.sma(df['close'], length=fast)
            df['ma_slow'] = ta.sma(df['close'], length=slow)
            df['signal'] = 0
            df.loc[df['ma_fast'] > df['ma_slow'], 'signal'] = 1
            df.loc[df['ma_fast'] < df['ma_slow'], 'signal'] = -1
            # 只在交叉时产生信号
            df['prev_signal'] = df['signal'].shift(1).fillna(0)
            signals = df['signal'].where(df['signal'] != df['prev_signal'], 0)
            return signals

        elif strategy == 'rsi_oversold':
            period = int(params.get('period', 14))
            threshold = float(params.get('threshold', 30))
            df['rsi'] = ta.rsi(df['close'], length=period)
            df['signal'] = 0
            df.loc[df['rsi'] < threshold, 'signal'] = 1
            df.loc[df['rsi'] > (100 - threshold), 'signal'] = -1
            signals = df['signal'].where(df['signal'] != df['signal'].shift(1).fillna(0), 0)
            return signals

        elif strategy == 'bbands_break':
            length = int(params.get('length', 20))
            std = float(params.get('std', 2.0))
            bbands = ta.bbands(df['close'], length=length, std=std)
            df['bb_upper'] = bbands.iloc[:, 0]
            df['bb_lower'] = bbands.iloc[:, 2]
            df['signal'] = 0
            df.loc[df['close'] > df['bb_upper'], 'signal'] = 1
            df.loc[df['close'] < df['bb_lower'], 'signal'] = -1
            signals = df['signal'].where(df['signal'] != df['signal'].shift(1).fillna(0), 0)
            return signals

        elif strategy == 'macd_divergence':
            fast = int(params.get('fast', 12))
            slow = int(params.get('slow', 26))
            signal = int(params.get('signal', 9))
            macd = ta.macd(df['close'], fast=fast, slow=slow, signal=signal)
            df['macd_line'] = macd.iloc[:, 0]
            df['macd_signal'] = macd.iloc[:, 1]
            df['macd_hist'] = macd.iloc[:, 2]
            df['signal'] = 0
            df.loc[df['macd_hist'] > 0, 'signal'] = 1
            df.loc[df['macd_hist'] < 0, 'signal'] = -1
            signals = df['signal'].where(df['signal'] != df['signal'].shift(1).fillna(0), 0)
            return signals

        return None

    def _simulate_trades(self, df: pd.DataFrame, signals: pd.Series) -> Dict:
        """模拟交易，计算收益"""
        capital = self.initial_capital
        position = 0
        entry_price = 0
        trades = []
        equity_curve = []

        for i in range(len(df)):
            signal = signals.iloc[i] if i < len(signals) else 0
            close_price = df['close'].iloc[i]
            timestamp = df['ts'].iloc[i] if 'ts' in df.columns else i

            # 买入信号
            if signal == 1 and position == 0:
                entry_price = close_price * (1 + self.slippage)
                shares = capital / entry_price
                commission = capital * self.commission_rate
                capital -= commission
                position = shares
                trades.append({
                    'time': str(timestamp),
                    'side': 'buy',
                    'price': round(entry_price, 2),
                    'shares': round(shares, 6),
                    'commission': round(commission, 2),
                })

            # 卖出信号
            elif signal == -1 and position > 0:
                exit_price = close_price * (1 - self.slippage)
                proceeds = position * exit_price
                commission = proceeds * self.commission_rate
                capital += proceeds - commission
                pnl = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    'time': str(timestamp),
                    'side': 'sell',
                    'price': round(exit_price, 2),
                    'shares': round(position, 6),
                    'commission': round(commission, 2),
                    'pnl_pct': round(pnl, 2),
                })
                position = 0

            # 记录权益曲线
            equity = capital + position * close_price
            equity_curve.append({
                'time': str(timestamp),
                'equity': round(equity, 2),
            })

        # 最终收益
        final_price = df['close'].iloc[-1]
        if position > 0:
            capital += position * final_price

        total_return = (capital - self.initial_capital) / self.initial_capital * 100
        buy_hold_return = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100

        # 计算最大回撤
        equity_values = [e['equity'] for e in equity_curve]
        peak = equity_values[0] if equity_values else self.initial_capital
        max_drawdown = 0
        for v in equity_values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100
            if dd > max_drawdown:
                max_drawdown = dd

        # 计算夏普比率（简化版）
        if len(equity_values) > 1:
            returns = pd.Series(equity_values).pct_change().dropna()
            if returns.std() > 0:
                sharpe = returns.mean() / returns.std() * np.sqrt(252)
            else:
                sharpe = 0
        else:
            sharpe = 0

        return {
            'code': 0,
            'initial_capital': self.initial_capital,
            'final_capital': round(capital, 2),
            'total_return_pct': round(total_return, 2),
            'buy_hold_return_pct': round(buy_hold_return, 2),
            'max_drawdown_pct': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe, 2),
            'total_trades': len(trades),
            'win_rate': round(len([t for t in trades if t.get('pnl_pct', 0) > 0]) / max(len([t for t in trades if t.get('pnl_pct') is not None]), 1) * 100, 2) if any(t.get('pnl_pct') is not None for t in trades) else 0,
            'trades': trades[-50:],  # 最近50笔交易
            'equity_curve': equity_curve[-100:],  # 最近100个点
        }


# 单例
_backtest_engine = None


def get_backtest_engine():
    global _backtest_engine
    if _backtest_engine is None:
        _backtest_engine = BacktestEngine()
    return _backtest_engine
