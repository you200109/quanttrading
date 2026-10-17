import importlib.util
from pathlib import Path

# 显式按文件路径加载（零全局 sys.path 污染——勿改回 sys.path.insert：
# 会让模块名 `strategy` 被劫持，殃及 test_nexus_paths.py，已实测三次）
_here = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "research_strategy_ids", _here.parent / "research" / "strategy.py")
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
decode, encode = _mod.decode, _mod.encode


def test_roundtrip_all_families():
    cases = {"sma": {"fast": 10, "slow": 60},
             "rsi": {"window": 14, "lower": 30, "upper": 70},
             "bbands": {"window": 20, "k": 2.35},
             "breakout": {"enter": 20, "leave": 10}}
    for name, p in cases.items():
        assert decode(encode(name, p)) == (name, p)


def test_encode_is_order_independent():
    assert encode("rsi", {"upper": 70, "lower": 30, "window": 14}) == "rsi:lower=30,upper=70,window=14"


def test_legacy_id():
    assert decode("10/60") == ("sma", {"fast": 10, "slow": 60})
