"""Run after nightly.py: pick a leaderboard winner, forward-test it, advance the lifecycle.

Uses daily bars (the timeframe the weekly search validated on); the workflow
sets TIMEFRAME=1d BARS=600 for this step.
"""
import json
import os
from datetime import datetime, timezone

import pandas as pd

from lifecycle import load_state, notify, step
from nightly import OUT, PAGES_URL, fetch_close, num, stats
from search import backtest
from strategy import decode, encode

LIVE_STAGES = ("paper", "ready_for_review", "approved")
MIN_FWD_BARS = 7  # too little forward data proves nothing, so no verdict yet


def forward(close, tf_s, state):
    if state["stage"] not in LIVE_STAGES or not state["frozen"]:
        return None
    start = close.index.searchsorted(pd.Timestamp(state["paper_start"], tz="UTC"))
    if len(close) - start < MIN_FWD_BARS:
        return None
    name, params = decode(state["frozen"])
    out = stats(backtest(close, tf_s, name, params, start))
    out["bh_return_pct"] = num((close.iloc[-1] / close.iloc[start] - 1) * 100)
    return out


def pick_winner():
    """-> (family, frozen_id, passed, evidence_date) from the latest weekly leaderboard."""
    path = OUT / "leaderboard.json"
    if not path.exists():
        return None, None, False, None
    board = json.loads(path.read_text())
    for row in board["rows"]:  # sorted by out-of-sample Sharpe
        if row["passed"]:
            return row["name"], encode(row["name"], row["params_by_fold"][-1]), True, board["generated_at"][:10]
    return None, None, False, board["generated_at"][:10]


def main():
    report = json.loads((OUT / "report.json").read_text())
    close, tf_s = fetch_close()
    state = load_state(PAGES_URL)
    fwd = forward(close, tf_s, state)
    family, frozen_id, passed, evidence = pick_winner()
    fresh = evidence is not None and evidence != state.get("last_evidence")
    now = datetime.now(timezone.utc)
    state, events = step(state, passed, family, fwd,
                         os.getenv("KILL_SWITCH") == "1",
                         os.getenv("APPROVED_PARAMS", "").strip(),
                         now.strftime("%Y-%m-%d"), fresh, frozen_id)
    if fresh:
        state["last_evidence"] = evidence
    state["forward"] = fwd if state["stage"] in LIVE_STAGES else None
    state["updated"] = now.isoformat(timespec="seconds")
    state["events"] = (state.get("events", []) + [f"{now:%Y-%m-%d} {e}" for e in events])[-20:]
    report["lifecycle"] = state
    (OUT / "state.json").write_text(json.dumps(state, ensure_ascii=False))
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False))
    notify(events)
    print("stage:", state["stage"], "streak:", state["streak"], events)


if __name__ == "__main__":
    main()
