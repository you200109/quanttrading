"""Strategy lifecycle: candidate -> paper (forward test) -> ready_for_review -> approved.

No code here places real orders. 'approved' only records a human decision.
"""
import json
import os
import urllib.request
from datetime import date

from agent_utils import create_issue

STREAK_TO_PAPER = 3       # consecutive passing nights with the same params
MIN_PAPER_DAYS = 14       # forward-test length before asking a human
MAX_DRAWDOWN_PCT = -10.0  # demote at or below this
MAX_LAG_PCT = 15.0        # demote if this far behind buy-and-hold
FRESH = {"stage": "candidate", "streak": 0, "params": None,
         "frozen": None, "paper_start": None}


def load_state(pages_url):
    try:
        with urllib.request.urlopen(f"{pages_url}/data/state.json", timeout=15) as r:
            return {**FRESH, **json.load(r)}
    except Exception:
        return dict(FRESH)


def demotion_reason(fwd):
    if not fwd:
        return None
    dd, ret, bh = fwd.get("max_drawdown_pct"), fwd.get("return_pct"), fwd.get("bh_return_pct")
    if dd is not None and dd <= MAX_DRAWDOWN_PCT:
        return f"最大回撤 {dd}% 触及 {MAX_DRAWDOWN_PCT}% 红线"
    if ret is not None and bh is not None and bh - ret >= MAX_LAG_PCT:
        return f"收益落后买入持有 {round(bh - ret, 1)} 个百分点"
    return None


def step(state, passed, params, fwd, kill, approved, today):
    s, ev = dict(state), []
    if kill:
        if s["stage"] != "halted":
            ev.append("总开关已关闭，所有阶段暂停")
        s["stage"] = "halted"
        return s, ev
    if s["stage"] == "halted":
        s.update(FRESH)
        ev.append("总开关已恢复，从候选阶段重新开始")
    if s["stage"] == "candidate":
        if not passed:
            s.update(params=None, streak=0)
        elif params == s["params"]:
            s["streak"] += 1
        else:
            s.update(params=params, streak=1)
        if s["streak"] >= STREAK_TO_PAPER:
            s.update(stage="paper", frozen=params, paper_start=today)
            ev.append(f"策略 {params} 连续 {STREAK_TO_PAPER} 天通过检查，进入前向模拟盘")
    else:
        reason = demotion_reason(fwd)
        if reason:
            ev.append(f"策略 {s['frozen']} 被降级回候选：{reason}")
            s.update(FRESH)
        else:
            elapsed = (date.fromisoformat(today) - date.fromisoformat(s["paper_start"])).days
            if s["stage"] == "paper" and elapsed >= MIN_PAPER_DAYS:
                s["stage"] = "ready_for_review"
                ev.append(f"策略 {s['frozen']} 前向模拟满 {MIN_PAPER_DAYS} 天且未触发红线，等待人工批准")
            if s["stage"] == "ready_for_review" and approved == s["frozen"]:
                s["stage"] = "approved"
                ev.append(f"策略 {s['frozen']} 已由人工批准（仅记录，系统不会自动下实盘单）")
    return s, ev


def notify(events):
    if not events or not os.getenv("GITHUB_TOKEN"):
        return
    try:
        create_issue("[状态] " + events[0][:60], "\n".join(f"- {e}" for e in events), ["lifecycle"])
    except Exception as e:
        print("notify failed:", e)
