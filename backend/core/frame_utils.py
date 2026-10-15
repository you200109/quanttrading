"""K线数据 → DataFrame 统一转换

历史背景：routes.py / vc_routes.py 中曾有 4 份逐字重复的转换逻辑
（含已删除的 backend/core/vc_adapter.py）。统一收敛到此模块，
转换规则（列名/数值化/时间索引）与原实现完全一致，保证行为不变。
"""

from typing import Any, Sequence

import pandas as pd

# OKX K线原始列序：ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm
CANDLE_COLUMNS = ['ts', 'open', 'high', 'low', 'close', 'vol', 'volCcy', 'volCcyQuote', 'confirm']
NUMERIC_COLUMNS = ['open', 'high', 'low', 'close', 'vol']


def candles_to_frame(raw: Sequence[Sequence[Any]]) -> pd.DataFrame:
    """把 OKX get_candlesticks 原始返回转为带时间索引的数值化 DataFrame

    规则（与原 4 份重复实现一致）：
    1. 固定 9 列列名
    2. open/high/low/close/vol 数值化（非法值 → NaN）
    3. ts 列（毫秒字符串/数字）→ datetime 索引
    """
    df = pd.DataFrame(raw, columns=CANDLE_COLUMNS)
    for c in NUMERIC_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['ts'] = pd.to_datetime(df['ts'].astype(float), unit='ms')
    return df
