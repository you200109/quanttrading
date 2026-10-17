"""SMA crossover signals. Pure pandas, no network, easy to unit-test."""
import pandas as pd


def sma_signals(close: pd.Series, fast: int, slow: int):
    if fast >= slow:
        raise ValueError("fast must be smaller than slow")
    above = close.rolling(fast).mean() > close.rolling(slow).mean()
    prev = above.shift(1, fill_value=False)
    return above & ~prev, ~above & prev  # entries, exits
