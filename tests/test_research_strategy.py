import importlib.util
from pathlib import Path

import pandas as pd
import pytest

# 显式按文件路径加载 research/strategy.py（不污染全局 sys.path——
# tests/ 里既有 conftest/test_nexus_paths.py 依赖 `strategy` 解析到 vc 包，
# 若把 research/ 插进 sys.path[0]，模块名 `strategy` 会被 research/strategy.py 劫持）
_here = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "research_strategy", _here.parent / "research" / "strategy.py")
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sma_signals = _mod.sma_signals


def _series():
    down = list(range(60, 20, -1))
    up = list(range(20, 70))
    return pd.Series(down + up + down)


def test_has_entries_and_exits():
    e, x = sma_signals(_series(), 3, 8)
    assert e.sum() >= 1 and x.sum() >= 1


def test_never_enter_and_exit_same_bar():
    e, x = sma_signals(_series(), 3, 8)
    assert not (e & x).any()


def test_fast_must_be_smaller():
    with pytest.raises(ValueError):
        sma_signals(_series(), 10, 5)
