"""Run after nightly.py: forward-test frozen params and advance the lifecycle."""
import json
import os
from datetime import datetime, timezone

import pandas as pd

from lifecycle import load_state, notify, step
from nightly import OUT, PAGES_URL, fetch_close, num, simulate, stats

LIVE_STAGES = ("paper", "ready_for_review", "approved")


def forward(close, tf_s, state):
    if state["stage"] not in LIVE_STAGES or not state["frozen"]:
        return None
    start = close.index.searchsorted(pd.Timestamp(state["paper_start"], tz="UTC"))
    if len(close) - start < 24:
        return None
    fast, slow = map(int, state["frozen"].split("/"))
    out = stats(simulate(close, tf_s, fast, slow, start))
    out["bh_return_pct"] = num((close.iloc[-1] / close.iloc[start] - 1) * 100)
    return out


def main():
    report = json.loads((OUT / "report.json").read_text())
    close, tf_s = fetch_close()
    state = load_state(PAGES_URL)
    fwd = forward(close, tf_s, state)
    now = datetime.now(timezone.utc)
    params = f"{report['params']['fast']}/{report['params']['slow']}"
    state, events = step(state, report["gate"]["passed"], params, fwd,
                         os.getenv("KILL_SWITCH") == "1",
                         os.getenv("APPROVED_PARAMS", "").strip(),
                         now.strftime("%Y-%m-%d"))
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
