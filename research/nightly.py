"""Nightly walk-forward backtest -> site/data/report.json + history.json.

Open-source stack: ccxt (OKX public data, no API key), vectorbt (backtest).
Parameters are chosen on the first 70% of data and judged on the last 30%.
"""
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd
import vectorbt as vbt

from strategy import sma_signals

SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
TIMEFRAME = os.getenv("TIMEFRAME", "1h")
BARS = int(os.getenv("BARS", "2000"))
PAGES_URL = os.getenv("PAGES_URL", "").rstrip("/")
FEES, SLIPPAGE, TRAIN_FRAC, CASH = 0.001, 0.0005, 0.7, 10_000
GRID = [(f, s) for f in range(5, 55, 5) for s in range(20, 220, 20) if f < s]
OUT = Path(__file__).parent / "site" / "data"


def fetch_close() -> pd.Series:
    ex = ccxt.okx({"enableRateLimit": True})
    tf_s = ex.parse_timeframe(TIMEFRAME)
    since = ex.milliseconds() - BARS * tf_s * 1000
    rows = []
    for _ in range(60):
        batch = ex.fetch_ohlcv(SYMBOL, TIMEFRAME, since=since, limit=100)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + tf_s * 1000
        if len(rows) >= BARS or len(batch) < 2:
            break
    df = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"])
    df = df.drop_duplicates("ts")
    close = pd.Series(df["c"].astype(float).values,
                      index=pd.to_datetime(df["ts"], unit="ms", utc=True))
    return close.iloc[:-1], tf_s  # drop the unfinished candle


def simulate(close, tf_s, fast, slow, start, end=None):
    e, x = sma_signals(close, fast, slow)  # signals on full series: no warm-up gap
    sl = slice(start, end)
    return vbt.Portfolio.from_signals(
        close.iloc[sl], e.iloc[sl], x.iloc[sl], init_cash=CASH,
        fees=FEES, slippage=SLIPPAGE, freq=pd.Timedelta(seconds=tf_s))


def num(v, nd=2):
    v = float(v)
    return round(v, nd) if np.isfinite(v) else None


def stats(pf):
    return {"return_pct": num(pf.total_return() * 100),
            "max_drawdown_pct": num(pf.max_drawdown() * 100),
            "sharpe": num(pf.sharpe_ratio()),
            "trades": int(pf.trades.count())}


def load_history():
    if not PAGES_URL:
        return []
    try:
        with urllib.request.urlopen(f"{PAGES_URL}/data/history.json",
                                    timeout=15) as r:
            return json.load(r)
    except Exception:
        return []


def main():
    close, tf_s = fetch_close()
    split = int(len(close) * TRAIN_FRAC)

    def train_sharpe(p):
        v = simulate(close, tf_s, *p, 0, split).sharpe_ratio()
        return float(v) if np.isfinite(v) else -np.inf

    fast, slow = max(GRID, key=train_sharpe)
    train = stats(simulate(close, tf_s, fast, slow, 0, split))
    pf = simulate(close, tf_s, fast, slow, split)
    test = stats(pf)

    bh = close.iloc[split:] / close.iloc[split] * CASH
    bh_ret = num((bh.iloc[-1] / CASH - 1) * 100)
    t_sh, tr_sh = test["sharpe"], train["sharpe"]
    passed = bool(t_sh is not None and tr_sh is not None
                  and t_sh >= 0.5 and test["trades"] >= 10 and t_sh >= 0.5 * tr_sh)

    step = max(1, len(bh) // 300)
    val = pf.value().iloc[::step]
    now = datetime.now(timezone.utc)
    report = {
        "generated_at": now.isoformat(timespec="seconds"),
        "symbol": SYMBOL, "timeframe": TIMEFRAME, "bars": len(close),
        "assumptions": {"fees_per_side": FEES, "slippage": SLIPPAGE},
        "params": {"fast": fast, "slow": slow},
        "train": train, "test": test, "buy_hold_return_pct": bh_ret,
        "gate": {"passed": passed,
                 "rule": "样本外夏普 ≥ 0.5、交易 ≥ 10 次、且不低于样本内夏普的一半"},
        "equity": {"t": [t.strftime("%m-%d %H:%M") for t in val.index],
                   "strategy": [round(float(v), 2) for v in val.values],
                   "buy_hold": [round(float(v), 2)
                                for v in bh.reindex(val.index).values]},
    }
    hist = load_history()
    hist.append({"date": now.strftime("%Y-%m-%d"), "fast": fast, "slow": slow,
                 "test_return_pct": test["return_pct"], "test_sharpe": t_sh,
                 "buy_hold_return_pct": bh_ret, "passed": passed})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False))
    (OUT / "history.json").write_text(json.dumps(hist[-365:], ensure_ascii=False))
    print(f"SMA({fast},{slow}) test={test} buy&hold={bh_ret}% gate={passed}")


if __name__ == "__main__":
    main()
