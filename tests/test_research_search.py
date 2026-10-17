import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

# 显式按文件路径加载（零全局 sys.path 污染——同 test_research_agent.py /
# test_research_lifecycle.py 口径：直插 research/ 会劫持模块名 `strategy`，
# 殃及 tests/test_nexus_paths.py，已实测三次，不再踩）
_here = Path(__file__).resolve().parent
_research = _here.parent / "research"


def _load(py_name, real_name):
    spec = importlib.util.spec_from_file_location(py_name, _research / real_name)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_metrics = _load("research_metrics_search", "metrics.py")
_strategy = _load("research_strategy_search", "strategy.py")
hurdle, sharpe = _metrics.hurdle, _metrics.sharpe
SIGNALS = _strategy.SIGNALS

PARAMS = {"sma": {"fast": 5, "slow": 20},
          "rsi": {"window": 14, "lower": 30, "upper": 70},
          "bbands": {"window": 20, "k": 2.0},
          "breakout": {"enter": 20, "leave": 10}}


def _walk():
    rng = np.random.default_rng(7)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 600))))


def test_every_family_emits_exclusive_boolean_signals():
    close = _walk()
    for name, fn in SIGNALS.items():
        e, x = fn(close, **PARAMS[name])
        assert e.dtype == bool and x.dtype == bool and len(e) == len(close), name
        assert not (e & x).any(), name
        assert e.any() and x.any(), name


def test_hurdle_behaviour():
    assert hurdle(2.0, 4) > hurdle(8.0, 4)   # more data, lower bar
    assert hurdle(2.0, 8) > hurdle(2.0, 4)   # more families, higher bar
    assert hurdle(1000.0, 4) == 0.5          # floor
    assert hurdle(0, 4) == float("inf")


def test_sharpe_basics():
    assert sharpe(pd.Series([0.0] * 10), 365) == 0.0
    assert sharpe(pd.Series([0.01, -0.005] * 50), 365) > 0
