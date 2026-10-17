"""Weekly strategy search (Optuna) with expanding-window walk-forward.

Parameters are re-optimised on each training window and judged only on the next
unseen block, so out-of-sample numbers describe the whole search procedure.
A hurdle that grows with the number of families tried guards against luck.
Run with TIMEFRAME=1d BARS=1500 (set in the workflow). Needs no API key.
"""
import json
import math
import os
from datetime import date, datetime, timezone

import numpy as np
import optuna
import pandas as pd
import vectorbt as vbt

from agent_utils import create_issue, issue_titles
from metrics import hurdle, sharpe
from nightly import FEES, OUT, SLIPPAGE, fetch_close, num
from strategy import SIGNALS

FOLDS, TRAIN_START, MIN_TRADES = 4, 0.5, 10
TRIALS = int(os.getenv("TRIALS", "40"))
SPACES = {
    "sma": lambda t: {"fast": t.suggest_int("fast", 5, 60),
                      "slow": t.suggest_int("slow", 30, 250)},
    "rsi": lambda t: {"window": t.suggest_int("window", 5, 30),
                      "lower": t.suggest_int("lower", 15, 40),
                      "upper": t.suggest_int("upper", 55, 85)},
    "bbands": lambda t: {"window": t.suggest_int("window", 10, 60),
                         "k": t.suggest_float("k", 1.0, 3.0)},
    "breakout": lambda t: {"enter": t.suggest_int("enter", 10, 100),
                           "leave": t.suggest_int("leave", 5, 50)},
}


def backtest(close, tf_s, name, params, start, end=None):
    e, x = SIGNALS[name](close, **params)  # causal signals on the full series
    sl = slice(start, end)
    return vbt.Portfolio.from_signals(
        close.iloc[sl], e.iloc[sl], x.iloc[sl], init_cash=10_000,
        fees=FEES, slippage=SLIPPAGE, freq=pd.Timedelta(seconds=tf_s))


def optimise(close, tf_s, name, end, ppy):
    def objective(trial):
        p = SPACES[name](trial)
        if name == "sma" and p["fast"] >= p["slow"]:
            return -10.0
        s = sharpe(backtest(close, tf_s, name, p, 0, end).returns(), ppy)
        return s if math.isfinite(s) else -10.0

    study = optuna.create_study(direction="maximize",
                                sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=TRIALS)
    return study.best_params


def main():
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    close, tf_s = fetch_close()
    n = len(close)
    if n < 600:
        raise RuntimeError(f"数据不足：只有 {n} 根K线")
    ppy = 365 * 86400 / tf_s
    edges = [int(v) for v in np.linspace(int(n * TRAIN_START), n, FOLDS + 1)]
    start0 = edges[0]

    rows, curves = [], {}
    for name in SPACES:
        rets, picks, trades = [], [], 0
        for a, b in zip(edges[:-1], edges[1:]):
            p = optimise(close, tf_s, name, a, ppy)
            pf = backtest(close, tf_s, name, p, a, b)
            rets.append(pf.returns())
            trades += int(pf.trades.count())
            picks.append({k: round(v, 2) if isinstance(v, float) else v for k, v in p.items()})
        r = pd.concat(rets)
        eq = (1 + r).cumprod()
        curves[name] = eq
        rows.append({"name": name, "oos_sharpe": num(sharpe(r, ppy)),
                     "oos_return_pct": num((eq.iloc[-1] - 1) * 100),
                     "oos_max_dd_pct": num((eq / eq.cummax() - 1).min() * 100),
                     "trades": trades, "params_by_fold": picks})
        print(name, rows[-1]["oos_sharpe"], rows[-1]["oos_return_pct"])

    years = len(r) / ppy
    h = round(hurdle(years, len(SPACES)), 2)
    for row in rows:
        s = row["oos_sharpe"]
        row["passed"] = bool(s is not None and s >= h and row["trades"] >= MIN_TRADES)
    rows.sort(key=lambda x: x["oos_sharpe"] if x["oos_sharpe"] is not None else -99, reverse=True)

    bh = close.iloc[start0:] / close.iloc[start0]
    idx = bh.index[::max(1, len(bh) // 200)]

    def series(s):
        return [round(float(v), 4) for v in s.reindex(idx, method="ffill").fillna(1.0).values]

    now = datetime.now(timezone.utc)
    board = {
        "generated_at": now.isoformat(timespec="seconds"),
        "symbol": os.getenv("SYMBOL", "BTC/USDT"), "timeframe": os.getenv("TIMEFRAME", "1h"),
        "bars": n, "hurdle": h,
        "method": {"folds": FOLDS, "trials_per_fold": TRIALS, "families": len(SPACES),
                   "oos_years": round(years, 2), "fees_per_side": FEES, "slippage": SLIPPAGE,
                   "note": "每个折叠独立回测，折叠边界处仓位清零"},
        "buy_hold": {"return_pct": num((bh.iloc[-1] - 1) * 100),
                     "sharpe": num(sharpe(bh.pct_change().dropna(), ppy))},
        "rows": rows,
        "equity": {"t": [t.strftime("%Y-%m-%d") for t in idx], "buy_hold": series(bh),
                   **{k: series(v) for k, v in curves.items()}},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "leaderboard.json").write_text(json.dumps(board, ensure_ascii=False))

    winners = [r for r in rows if r["passed"]]
    if winners and os.getenv("GITHUB_TOKEN"):
        iso = date.today().isocalendar()
        top = winners[0]
        title = f"[搜索] {iso[0]}-W{iso[1]:02d} 通过门槛：{top['name']}"
        body = (f"- 样本外夏普 {top['oos_sharpe']}（门槛 {h}）\n"
                f"- 样本外收益 {top['oos_return_pct']}%，买入持有 {board['buy_hold']['return_pct']}%\n"
                f"- 最大回撤 {top['oos_max_dd_pct']}%，交易 {top['trades']} 次\n"
                f"- 各折叠选出的参数：{json.dumps(top['params_by_fold'], ensure_ascii=False)}\n\n"
                "> 只表示通过统计门槛，不代表会盈利。仍需走候选、前向模拟、人工批准的流程。")
        try:
            if title not in issue_titles():
                create_issue(title, body, ["search"])
        except Exception as e:
            print("issue failed:", e)
    print("hurdle", h, "winners", [w["name"] for w in winners])


if __name__ == "__main__":
    main()
