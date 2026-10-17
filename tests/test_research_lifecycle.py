import importlib.util
import sys
from pathlib import Path

# 显式按文件路径加载（零全局 sys.path 污染——直插 research/ 会劫持模块名
# `strategy`，殃及 test_nexus_paths.py；同 test_research_agent.py 口径）
_here = Path(__file__).resolve().parent
_research = _here.parent / "research"

_s1 = importlib.util.spec_from_file_location(
    "research_agent_utils", _research / "agent_utils.py")
assert _s1 is not None and _s1.loader is not None
_au = importlib.util.module_from_spec(_s1)
_s1.loader.exec_module(_au)
sys.modules["agent_utils"] = _au  # lifecycle 顶层 `from agent_utils import ...`

_s2 = importlib.util.spec_from_file_location(
    "research_lifecycle", _research / "lifecycle.py")
assert _s2 is not None and _s2.loader is not None
_lc = importlib.util.module_from_spec(_s2)
_s2.loader.exec_module(_lc)
FRESH, STREAK_TO_PAPER, step = _lc.FRESH, _lc.STREAK_TO_PAPER, _lc.step

ID = "breakout:enter=20,leave=10"
PAPER = {**FRESH, "stage": "paper", "frozen": ID, "paper_start": "2026-11-01"}
GOOD = {"max_drawdown_pct": -3.0, "return_pct": 2.0, "bh_return_pct": 1.0}


def run(state, passed=True, params="breakout", fwd=None, kill=False,
        approved="", today="2026-11-05", fresh=True, frozen_id=ID):
    return step(state, passed, params, fwd, kill, approved, today, fresh, frozen_id)


def test_promotes_after_enough_fresh_passes():
    s = dict(FRESH)
    for _ in range(STREAK_TO_PAPER):
        s, _ = run(s)
    assert s["stage"] == "paper" and s["frozen"] == ID


def test_stale_evidence_does_not_count():
    s = dict(FRESH)
    for _ in range(5):
        s, _ = run(s, fresh=False)
    assert s["stage"] == "candidate" and s["streak"] == 0


def test_family_change_or_failure_resets_streak():
    s, _ = run(dict(FRESH))
    s, _ = run(s, params="rsi", frozen_id="rsi:lower=30,upper=70,window=14")
    assert s["streak"] == 1 and s["params"] == "rsi"
    s, _ = run(s, passed=False, params=None, frozen_id=None)
    assert s["streak"] == 0 and s["params"] is None


def test_kill_switch_halts_then_restarts():
    s, ev = run(PAPER, kill=True)
    assert s["stage"] == "halted" and ev
    s, _ = run(s)
    assert s["stage"] == "candidate" and s["frozen"] is None


def test_demotes_on_drawdown():
    bad = {"max_drawdown_pct": -12.0, "return_pct": -5.0, "bh_return_pct": 1.0}
    s, ev = run(PAPER, fwd=bad)
    assert s["stage"] == "candidate" and any("降级" in e for e in ev)


def test_review_then_human_approval():
    s, ev = run(PAPER, fwd=GOOD, today="2026-11-20")
    assert s["stage"] == "ready_for_review" and ID in ev[0]
    s, _ = run(s, fwd=GOOD, today="2026-11-21", approved="")
    assert s["stage"] == "ready_for_review"  # 不批不准
    s, _ = run(s, fwd=GOOD, today="2026-11-22", approved=ID)
    assert s["stage"] == "approved"
