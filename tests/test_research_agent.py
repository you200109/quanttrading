import importlib.util
from pathlib import Path

# 显式按文件路径加载 research/agent_utils.py（零全局 sys.path 污染——
# sys.path 直插 research/ 会把模块名 `strategy` 劫持为 research/strategy.py，
# 殃及 tests/test_nexus_paths.py 的 vc 包导入，已实测；异步口径与
# test_research_strategy.py 一致）
_here = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "research_agent_utils", _here.parent / "research" / "agent_utils.py")
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
permissive = _mod.permissive
weekly_stats = _mod.weekly_stats


def test_permissive_filters():
    ok = {"license": {"spdx_id": "MIT"}}
    assert permissive(ok)
    assert not permissive({"license": {"spdx_id": "GPL-3.0"}})
    assert not permissive({"license": None})
    assert not permissive({**ok, "fork": True})
    assert not permissive({**ok, "archived": True})


def test_weekly_stats():
    row = {"fast": 10, "slow": 60, "test_return_pct": 4, "buy_hold_return_pct": 2}
    h = [{**row, "test_sharpe": 1.0, "passed": True},
         {**row, "test_sharpe": 0.0, "test_return_pct": -2, "passed": False}]
    s = weekly_stats(h)
    assert s["pass_rate"] == 0.5 and s["avg_test_sharpe"] == 0.5
    assert s["distinct_params"] == 1
    assert weekly_stats([]) == {}
