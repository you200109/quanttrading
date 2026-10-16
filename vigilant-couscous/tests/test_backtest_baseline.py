"""
回测模拟器黄金快照（P3b 合并基准；K2 指标重基线 2026-10-17）

固化 2026-10-16 P3b 启动时三处 RSI+SMA/SL/TP 模拟器的逐项输出：
- evolution/backtest_validator.py（实现基准）
- strategy/unified_evolve.py:_simulate（经 make_fitness 闭包）
- evolution/multi_dim_evolve.py:_run_sim（6 策略模板）

P3b 将 unified/multi 两处切换到 evolution/backtest_core.py 统一内核，
除两处"意图修复"（multi_dim 的 rsi/sma 指标数组恒零 bug）外，
当时所有断言保持逐字节不变——它是合并正确性的对照基准。

2026-10-17 K2（指标迁 pandas-ta，Cutler 式 → 库口径）为刻意重基线，
黄金值按新口径重新固化（历史值见 git history）：
- validator：random / rolling-window / osc-A 三组逐位不变（该数据上
  进出场条件未触发）；osc-B 的 rsi_oversold 25→40（仍在模板参数域
  15..40 内）后由 2 笔变 3 笔真实交易，紧止损/持仓天数/负收益机制
  覆盖保留；
- unified：4 个适应度全部重固化（RSI 直接参与信号）；
- multi_dim：macd_cross 重固化（MACD 口径变化）；bollinger / momentum /
  volume_surge 逐位不变（迁移为等价重排）。
"""
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# multi_dim_evolve 的 rsi_reversal / sma_cross 模板在 P3b 前的退化输出
# （_run_sim 把全零数组当 rsi/sma_f/sma_s 传给 signal_func）：
# rsi_reversal 恒买入且永不止盈（rsi>ob 恒假）→ 单笔持有到 SL/TP；
# sma_cross 交叉条件恒假 → 永不交易返回 0.01。
# P3b 已修复（传入真实指标数组），新黄金值见 tests/test_backtest_core.py。
INTENTIONAL_FIX_TEMPLATES = {"rsi_reversal", "sma_cross"}


def make_random_data(n=365, seed=42):
    """随机游走数据（validator 在此数据上零交易）"""
    np.random.seed(seed)
    dates = pd.date_range(end=datetime(2026, 1, 1), periods=n, freq='D')
    returns = np.random.randn(n) * 0.02
    close = 50000 * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.randn(n) * 0.01))
    low = close * (1 - np.abs(np.random.randn(n) * 0.01))
    volume = np.random.rand(n) * 1000 + 500
    return pd.DataFrame({'close': close, 'high': high, 'low': low, 'volume': volume}, index=dates)


def make_oscillating_data(n=365, seed=7):
    """确定性振荡数据（触发真实交易，覆盖交易循环/手续费/指标路径）"""
    np.random.seed(seed)
    dates = pd.date_range(end=datetime(2026, 1, 1), periods=n, freq='D')
    t = np.arange(n)
    wave = 50000 * (1 + 0.08 * np.sin(2 * np.pi * t / 30) + 0.03 * np.sin(2 * np.pi * t / 7))
    close = wave * (1 + np.random.randn(n) * 0.005)
    high = close * (1 + np.abs(np.random.randn(n) * 0.004))
    low = close * (1 - np.abs(np.random.randn(n) * 0.004))
    volume = 800 + 400 * np.abs(np.sin(2 * np.pi * t / 11)) + np.random.rand(n) * 200
    return pd.DataFrame({'close': close, 'high': high, 'low': low, 'volume': volume}, index=dates)


PARAMS_A = {"rsi_period": 14, "sma_fast": 5, "sma_slow": 20,
            "stop_loss": 0.05, "take_profit": 0.15,
            "rsi_oversold": 30, "rsi_overbought": 70}
# K2（2026-10-17）：rsi_oversold 25→40 —— 适配 pandas-ta RSI 口径（EWM 收敛段
# 更浅，25 下振荡数据不再触发入场）；40 仍在模板参数域 15..40 内。
PARAMS_B = {"rsi_period": 10, "sma_fast": 3, "sma_slow": 15,
            "stop_loss": 0.03, "take_profit": 0.10,
            "rsi_oversold": 40, "rsi_overbought": 75}


class TestValidatorBaseline:
    """backtest_validator 输出基准（P3b 冻结；K2 按 pandas-ta 口径重固化，见文件头）"""

    def test_random_data_zero_trades(self):
        from evolution.backtest_validator import BacktestValidator
        v = BacktestValidator(make_random_data(), initial_capital=100000)
        r = v.validate_strategy(PARAMS_A, "baseline")
        assert r.total_trades == 0
        assert r.total_return == 0
        assert r.score == pytest.approx(15.0)
        assert r.passed is False

    def test_rolling_window(self):
        from evolution.backtest_validator import BacktestValidator
        v = BacktestValidator(make_random_data(), initial_capital=100000)
        res = v.rolling_window_validation(PARAMS_A, windows=3)
        assert res["pass_rate"] == 0.0
        assert res["stable"] is False
        assert len(res["window_results"]) == 3

    def test_oscillating_params_a_zero_trades(self):
        from evolution.backtest_validator import BacktestValidator
        v = BacktestValidator(make_oscillating_data(), initial_capital=100000)
        r = v.validate_strategy(PARAMS_A, "osc")
        assert r.total_trades == 0
        assert r.score == pytest.approx(15.0)

    def test_oscillating_params_b_three_trades(self):
        """振荡数据 + 紧止损参数：3 笔真实交易，指标/手续费/评分为负
        （K2 重基线：RSI 阈值 25→40 适配库口径后由 2 笔变 3 笔）"""
        from evolution.backtest_validator import BacktestValidator
        v = BacktestValidator(make_oscillating_data(), initial_capital=100000)
        r = v.validate_strategy(PARAMS_B, "osc_b")
        assert r.total_trades == 3
        assert r.total_return == pytest.approx(-0.037058188806417744, rel=1e-9)
        assert r.sharpe_ratio == pytest.approx(-1.6482592218167025, rel=1e-9)
        assert r.max_drawdown == pytest.approx(0.040325631334611034, rel=1e-9)
        assert r.win_rate == 0.0
        assert r.profit_factor == 0.0
        assert r.calmar_ratio == pytest.approx(-0.9189733276383416, rel=1e-9)
        assert r.sortino_ratio == pytest.approx(-0.46716808508314206, rel=1e-9)
        assert r.avg_holding_days == pytest.approx(36.333333333333336, rel=1e-9)
        assert r.passed is False
        assert r.score == pytest.approx(-19.218093876654937, rel=1e-9)


class TestUnifiedFitnessBaseline:
    """unified_evolve._simulate 适应度基准（P3b 冻结；K2 按 pandas-ta 口径重固化）"""

    @pytest.fixture(scope="class")
    def genes(self):
        from evolution.learning_loop import StrategyGene
        g1 = StrategyGene(id="g1", params=dict(PARAMS_A))
        p2 = dict(PARAMS_A)
        p2.update(rsi_period=7, sma_fast=3, sma_slow=15, stop_loss=0.08, take_profit=0.25)
        g2 = StrategyGene(id="g2", params=p2)
        return g1, g2

    def test_random_data(self, genes):
        from strategy.unified_evolve import make_fitness
        fitness = make_fitness(make_random_data())
        assert fitness(genes[0]) == pytest.approx(0.3906603837270322, rel=1e-9)
        assert fitness(genes[1]) == pytest.approx(0.4388633106280774, rel=1e-9)

    def test_oscillating_data(self, genes):
        from strategy.unified_evolve import make_fitness
        fitness = make_fitness(make_oscillating_data())
        assert fitness(genes[0]) == pytest.approx(0.47517729262019914, rel=1e-9)
        assert fitness(genes[1]) == pytest.approx(0.6101740711484093, rel=1e-9)


MD_PARAMS = {
    'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70,
    'ema_fast': 12, 'ema_slow': 26, 'signal_period': 9,
    'bb_period': 20, 'bb_std': 2.0,
    'sma_fast': 5, 'sma_slow': 20,
    'lookback': 10, 'threshold': 0.02,
    'vol_ma_period': 20, 'vol_multiple': 2.0, 'price_threshold': 0.02,
    'stop_loss': 0.05, 'take_profit': 0.15, 'position_size': 0.2,
}

# K2（2026-10-17）重固化：macd_cross 随 MACD 指标口径变化；
# bollinger / momentum / volume_surge 逐位不变（迁移为等价重排）。
MD_GOLDEN = {
    "random": {
        "macd_cross": 0.557633795682836,
        "bollinger_breakout": 0.5709983506783467,
        "momentum_breakout": 0.3724462928626322,
        "volume_surge": 0.01,
    },
    "oscillating": {
        "macd_cross": 0.6927347543904294,
        "bollinger_breakout": 0.7568282321646582,
        "momentum_breakout": 0.6945880319056587,
        "volume_surge": 0.01,
    },
}

# P3b 合并前 multi_dim 退化输出存档（跳过用例）：rsi_reversal 恒零数组单笔
# 持有、sma_cross 交叉恒假返回 0.01。
MD_PRE_MERGE_GOLDEN = {
    "random": {"rsi_reversal": 0.3284867268507995, "sma_cross": 0.01},
    "oscillating": {"rsi_reversal": 0.44940995793164473, "sma_cross": 0.01},
}


class TestMultiDimBaseline:
    """multi_dim_evolve 模板适应度基准

    rsi_reversal / sma_cross 为 P3b 意图修复项（指标数组恒零 bug），
    切换内核后由 test_backtest_core.py 用新值固化。
    K2（2026-10-17 指标迁 pandas-ta）：macd_cross 随 MACD 口径变化重固化；
    bollinger / momentum / volume_surge 逐位不变。
    """

    @pytest.mark.parametrize("dataset", ["random", "oscillating"])
    @pytest.mark.parametrize("template", ["macd_cross", "bollinger_breakout",
                                          "momentum_breakout", "volume_surge"])
    def test_templates_golden(self, dataset, template):
        from evolution.multi_dim_evolve import MultiDimEvolution, STRATEGY_TEMPLATES
        from evolution.learning_loop import StrategyGene
        data = make_random_data() if dataset == "random" else make_oscillating_data()
        eng = MultiDimEvolution()
        ff = eng._make_fitness(data, STRATEGY_TEMPLATES[template])
        gene = StrategyGene(id=f"md_{template}", params=dict(MD_PARAMS))
        assert ff(gene) == pytest.approx(MD_GOLDEN[dataset][template], rel=1e-9)

    @pytest.mark.skip(reason='P3b 已修复指标恒零 bug，新黄金值见 test_backtest_core.py')
    @pytest.mark.parametrize("dataset", ["random", "oscillating"])
    @pytest.mark.parametrize("template", sorted(INTENTIONAL_FIX_TEMPLATES))
    def test_intentional_fix_templates_pre_merge(self, dataset, template):
        """P3b 合并前的退化输出存档（已跳过）：rsi_reversal 0.328/0.449、sma_cross 0.01/0.01。"""
        from evolution.multi_dim_evolve import MultiDimEvolution, STRATEGY_TEMPLATES
        from evolution.learning_loop import StrategyGene
        data = make_random_data() if dataset == "random" else make_oscillating_data()
        eng = MultiDimEvolution()
        ff = eng._make_fitness(data, STRATEGY_TEMPLATES[template])
        gene = StrategyGene(id=f"md_{template}", params=dict(MD_PARAMS))
        assert ff(gene) == pytest.approx(MD_PRE_MERGE_GOLDEN[dataset][template], rel=1e-9)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
