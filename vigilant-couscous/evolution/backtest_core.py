"""
回测执行内核 - P3b 合并产物

背景：仓库曾有三处逐字重复的 RSI+SMA/SL/TP 回测模拟循环——
1. evolution/backtest_validator.py:_run_backtest（实现基准，保留不改，
   其特有的逐 bar RSI 重算、单边逻辑、holding_days 语义由
   tests/test_backtest_baseline.py 固化）
2. strategy/unified_evolve.py:_simulate（4 折滚动验证的抗过拟合适应度）
3. evolution/multi_dim_evolve.py:_run_sim（6 策略模板的通用 signal_fn 驱动）

本模块把后两处收敛为单一内核：
- 指标层：calc_rsi / calc_sma（向量化，与 unified 原算法逐字节一致）
- 执行层：simulate()——signal_fn 驱动的统一资金曲线循环，
  SL/TP 止盈止损、手续费、仓位比例、复利模型全部参数化
- 评分层：fitness_score()——原两份逐字相同的适应度公式

signal_fn 协议：signal_fn(i, rsi, sma_f, sma_s, vol, position) 返回
  None/'hold'            无动作
  'buy'                  以 size_frac 比例买入（仅空仓时生效）
  'sell'                 平掉持仓（仅持仓时生效）
  ('buy', frac)          以 frac 比例买入（unified 的置信度仓位）

position 参数用于复现原 unified_evolve 的"空仓判买、持仓判卖"互斥结构
（信号函数可按持仓状态返回不同动作）；position-agnostic 的信号函数
（如 multi_dim 各模板）忽略该参数即可。
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SimResult:
    """一次模拟的原始输出（指标计算由调用方负责）"""
    trades: list[float] = field(default_factory=list)      # 每笔已平仓交易的 pnl 比例
    equity_curve: list[float] = field(default_factory=list)  # 每 bar 收盘组合价值（含起始）
    final_capital: float = 0.0
    n_bars: int = 0


def calc_rsi(close: np.ndarray, period: int) -> np.ndarray:
    """向量化 RSI

    与 strategy/unified_evolve.py:_simulate 原算法逐字节一致：
    delta = diff(prepend=首值)，增益/损失窗口为 [max(0, i-period+1), i]，
    早期 bar 使用扩展窗口；avg_loss 为 0 时 rs 取 100。
    """
    seg = np.asarray(close, dtype=float)
    m = len(seg)
    if m == 0:
        return np.array([])
    delta = np.diff(seg, prepend=seg[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = np.array([np.mean(gain[max(0, i - period + 1):i + 1]) for i in range(m)])
    avg_loss = np.array([np.mean(loss[max(0, i - period + 1):i + 1]) for i in range(m)])
    rs = np.divide(avg_gain, avg_loss, out=np.ones(m) * 100, where=avg_loss != 0)
    return 100 - (100 / (1 + rs))


def calc_sma(close: np.ndarray, period: int) -> np.ndarray:
    """简单移动平均（前 period-1 个 bar 为 NaN，与原实现一致）"""
    return pd.Series(np.asarray(close, dtype=float)).rolling(period).mean().values


def _parse_signal(sig, default_frac: float) -> tuple[str, float]:
    """归一化 signal_fn 返回值为 (action, size_frac)"""
    if not sig or sig == 'hold':
        return 'hold', default_frac
    if isinstance(sig, tuple):
        action = sig[0]
        frac = sig[1] if len(sig) > 1 else default_frac
        return action, frac
    return sig, default_frac


def simulate(
    close: np.ndarray,
    start: int,
    signal_fn,
    stop_loss: float,
    take_profit: float,
    size_frac: float,
    *,
    commission: float = 0.0,
    initial_capital: float = 100000.0,
    rsi: np.ndarray | None = None,
    sma_f: np.ndarray | None = None,
    sma_s: np.ndarray | None = None,
    vol: np.ndarray | None = None,
) -> SimResult:
    """统一回测执行循环

    Args:
        close: 收盘价序列
        start: 循环起始 bar（指标预热期）
        signal_fn: 信号函数，协议见模块 docstring
        stop_loss / take_profit: 止损 / 止盈比例
        size_frac: 默认单笔仓位比例（占当前可用资金）
        commission: 双边手续费率（默认 0，unified/multi 原实现均无手续费）
        initial_capital: 起始资金
        rsi / sma_f / sma_s / vol: 指标数组，缺省传全零（signal_fn 不用时无影响）

    Returns:
        SimResult（trades 为每笔平仓 pnl 比例列表；资金口径见调用方）
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    rsi = np.zeros(n) if rsi is None else rsi
    sma_f = np.zeros(n) if sma_f is None else sma_f
    sma_s = np.zeros(n) if sma_s is None else sma_s
    vol = np.zeros(n) if vol is None else vol

    capital = float(initial_capital)
    position = 0.0
    entry = 0.0
    trades: list[float] = []
    equity_curve = [capital]

    for i in range(start, n):
        price = close[i]
        if position > 0:
            pnl = (price - entry) / entry
            if pnl <= -stop_loss or pnl >= take_profit:
                capital += position * price * (1 - commission)
                trades.append(pnl)
                position = 0
                equity_curve.append(capital)
                continue
        action, frac = _parse_signal(signal_fn(i, rsi, sma_f, sma_s, vol, position), size_frac)
        if position == 0 and action == 'buy':
            invest = capital * frac
            position = invest / price
            entry = price
            capital -= invest * (1 + commission)
        elif position > 0 and action == 'sell':
            pnl = (price - entry) / entry
            capital += position * price * (1 - commission)
            trades.append(pnl)
            position = 0
        equity_curve.append(capital + position * price)

    if position > 0:
        trades.append((close[-1] - entry) / entry)
        capital += position * close[-1] * (1 - commission)

    return SimResult(trades=trades, equity_curve=equity_curve,
                     final_capital=capital, n_bars=n)


def fitness_score(trades: list[float], final_capital: float,
                  initial_capital: float = 100000.0) -> float:
    """适应度评分

    原 strategy/unified_evolve.py:_simulate 与
    evolution/multi_dim_evolve.py:_run_sim 逐字相同的公式：
    收益 30% + 夏普(钳制[-3,3]) 20% + 回撤 20% + 胜率 20% + 交易频次 10%。
    """
    if not trades:
        return 0.0
    total_ret = (final_capital - initial_capital) / initial_capital
    capped = np.clip(np.array(trades), -0.5, 0.5)
    avg, std = np.mean(capped), np.std(capped)
    sharpe = (avg / std * np.sqrt(252)) if std > 0 else 0
    sharpe = max(-3.0, min(3.0, sharpe))
    cum = np.cumprod(1 + capped)
    peak = np.maximum.accumulate(cum)
    mdd = np.max((peak - cum) / (peak + 1e-8))
    wr = sum(1 for t in trades if t > 0) / len(trades)
    total_ret = max(-0.5, min(1.0, total_ret))
    return (total_ret * 0.30 + max(0, sharpe) / 3 * 0.20 + (1 - mdd) * 0.20
            + wr * 0.20 + min(1, len(trades) / 15) * 0.10)
