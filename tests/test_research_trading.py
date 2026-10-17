import importlib.util
from pathlib import Path

# 显式按文件路径加载（零全局 sys.path 污染——勿改回 sys.path.insert：
# 会让模块名 `strategy` 被劫持，殃及 test_nexus_paths.py，已实测多次）
_here = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "research_trading", _here.parent / "research" / "trading.py")
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
plan_order = _mod.plan_order


def test_buys_when_long_signal_and_flat():
    action, amount, _ = plan_order(True, 0.0, 100.0, 500.0, 1000.0)
    assert action == "buy" and amount == 5.0


def test_buy_is_capped_by_max_usdt():
    action, amount, _ = plan_order(True, 0.0, 100.0, 5000.0, 1000.0)
    assert action == "buy" and amount == 10.0


def test_sells_everything_when_signal_flat():
    action, amount, _ = plan_order(False, 2.5, 100.0, 0.0, 1000.0)
    assert action == "sell" and amount == 2.5


def test_holds_when_aligned():
    assert plan_order(True, 3.0, 100.0, 0.0, 1000.0)[0] == "hold"
    assert plan_order(False, 0.0, 100.0, 900.0, 1000.0)[0] == "hold"


def test_dust_counts_as_flat():
    assert plan_order(False, 1e-9, 100.0, 900.0, 1000.0, min_amount=1e-5)[0] == "hold"
    assert plan_order(True, 1e-9, 100.0, 900.0, 1000.0, min_amount=1e-5)[0] == "buy"


def test_too_little_cash_holds():
    assert plan_order(True, 0.0, 100.0, 1.0, 1000.0, min_cost=5.0)[0] == "hold"
    assert plan_order(True, 0.0, 100.0, 0.0, 1000.0)[0] == "hold"
