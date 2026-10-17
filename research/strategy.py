"""Signal functions. Pure pandas, no network, easy to unit-test.

Each returns (entries, exits) boolean Series. The backtest engine (vectorbt)
ignores repeated entries while in a position and exits while flat.
"""
import pandas as pd


def sma_signals(close: pd.Series, fast: int, slow: int):
    if fast >= slow:
        raise ValueError("fast must be smaller than slow")
    above = close.rolling(fast).mean() > close.rolling(slow).mean()
    prev = above.shift(1, fill_value=False)
    return above & ~prev, ~above & prev


def rsi_signals(close: pd.Series, window: int, lower: float, upper: float):
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss)
    return rsi < lower, rsi > upper


def bbands_signals(close: pd.Series, window: int, k: float):
    mid = close.rolling(window).mean()
    sd = close.rolling(window).std()
    return close < mid - k * sd, close > mid


def breakout_signals(close: pd.Series, enter: int, leave: int):
    prev = close.shift(1)
    return close > prev.rolling(enter).max(), close < prev.rolling(leave).min()


SIGNALS = {"sma": sma_signals, "rsi": rsi_signals,
           "bbands": bbands_signals, "breakout": breakout_signals}


def encode(name, params):
    """Stable text id for a strategy, e.g. 'breakout:enter=20,leave=10'."""
    return name + ":" + ",".join(f"{k}={params[k]}" for k in sorted(params))


def decode(strategy_id):
    if ":" not in strategy_id:  # legacy 'fast/slow' ids from the nightly SMA demo
        fast, slow = strategy_id.split("/")
        return "sma", {"fast": int(fast), "slow": int(slow)}
    name, _, rest = strategy_id.partition(":")
    params = {}
    for pair in rest.split(","):
        k, _, v = pair.partition("=")
        params[k] = float(v) if "." in v else int(v)
    return name, params
