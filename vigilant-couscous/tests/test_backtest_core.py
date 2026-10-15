"""
backtest_core 统一回测内核单元测试（P3b）

覆盖：
1. 指标层：calc_rsi / calc_sma 与原 unified_evolve 内联算法逐字节一致
2. 执行层：simulate 的信号协议（hold/buy/sell/('buy', frac)）、
   SL/TP 优先于信号、position 互斥分流、手续费、收盘强平
3. 评分层：fitness_score 公式不变量
4. 合并等价性：multi_dim/unified 经内核的输出与黄金快照一致
5. P3b 意图修复：rsi_reversal / sma_cross 模板新黄金值
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from evolution import backtest_core  # noqa: E402

sys.path.insert(0, str(ROOT / 'tests'))
from test_backtest_baseline import (  # noqa: E402
    MD_PARAMS, make_oscillating_data, make_random_data,
)


class TestCalcRsi:
    """calc_rsi 与原 unified_evolve._simulate 内联算法一致"""

    def test_matches_inline_implementation(self):
        close = make_random_data(120)['close'].values
        for period in (7, 14, 30):
            seg = close
            delta = np.diff(seg, prepend=seg[0])
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            avg_gain = np.array([np.mean(gain[max(0, i - period + 1):i + 1]) for i in range(len(seg))])
            avg_loss = np.array([np.mean(loss[max(0, i - period + 1):i + 1]) for i in range(len(seg))])
            rs = np.divide(avg_gain, avg_loss, out=np.ones(len(seg)) * 100, where=avg_loss != 0)
            expected = 100 - (100 / (1 + rs))
            got = backtest_core.calc_rsi(seg, period)
            assert np.array_equal(expected, got), f"period={period} RSI 不一致"

    def test_empty_and_flat(self):
        assert len(backtest_core.calc_rsi(np.array([]), 14)) == 0
        flat = np.full(50, 100.0)
        # 无涨跌：avg_gain=avg_loss=0 → rs=100 → rsi≈99.01（与原实现一致）
        assert backtest_core.calc_rsi(flat, 14)[-1] == pytest.approx(99.00990099009901)


class TestCalcSma:
    def test_matches_pandas_rolling(self):
        close = make_random_data(80)['close'].values
        for period in (3, 5, 20):
            expected = pd.Series(close).rolling(period).mean().values
            got = backtest_core.calc_sma(close, period)
            assert np.array_equal(expected, got, equal_nan=True)

    def test_warmup_nan(self):
        got = backtest_core.calc_sma(np.arange(10, dtype=float), 3)
        assert np.isnan(got[0]) and np.isnan(got[1])
        assert got[2] == pytest.approx(1.0)


def _hold_signal(i, rsi, sma_f, sma_s, vol, position):
    return 'hold'


def _always_buy(i, rsi, sma_f, sma_s, vol, position):
    return 'buy'


class TestSimulate:
    """simulate 执行层语义"""

    def test_hold_no_trades(self):
        close = np.linspace(100, 200, 50)
        res = backtest_core.simulate(close, 10, _hold_signal, 0.05, 0.15, 0.2)
        assert res.trades == []
        assert res.final_capital == 100000.0
        assert len(res.equity_curve) == 41  # 起始 + 每 bar

    def test_buy_only_closes_at_end(self):
        # 温和上涨且不触 TP：全程单笔，收盘强平
        close = np.linspace(100, 110, 50)
        res = backtest_core.simulate(close, 10, _always_buy, 0.05, 0.15, 0.2)
        assert len(res.trades) == 1
        entry = close[10]
        assert res.trades[0] == pytest.approx((close[-1] - entry) / entry)  # 收盘强平
        # 20% 仓位，无手续费：80000 + 20000*(末价/入场价)
        assert res.final_capital == pytest.approx(80000 + 20000 * (close[-1] / entry))

    def test_stop_loss_priority_over_signal(self):
        # 持续下跌：第 2 bar 即触及 -5% 止损，先于信号逻辑
        close = np.array([100.0, 90.0, 85.0, 84.0])
        bought = []

        def sig(i, rsi, sma_f, sma_s, vol, position):
            if not bought:
                bought.append(i)
                return 'buy'
            return 'hold'
        res = backtest_core.simulate(close, 1, sig, 0.05, 0.15, 0.5)
        assert len(res.trades) == 1
        assert res.trades[0] == pytest.approx((85 - 90) / 90)
        assert res.final_capital > 0

    def test_sl_tp_exit_skips_signal_same_bar(self):
        # 验证 SL/TP 平仓当 bar 不重新入场（与原实现 continue 语义一致）
        close = np.array([100.0, 95.0, 90.0, 91.0])
        calls = []

        def sig(i, rsi, sma_f, sma_s, vol, position):
            calls.append(i)
            return 'buy'
        backtest_core.simulate(close, 1, sig, 0.04, 0.15, 0.5)
        # bar1 买入，bar2 -5.3% 触及止损 → continue（bar2 不调用 signal）
        assert 2 not in calls
        assert 1 in calls and 3 in calls

    def test_commission(self):
        close = np.array([100.0, 110.0])
        res = backtest_core.simulate(close, 0, _always_buy, 0.05, 0.15, 0.5, commission=0.01)
        # 买入付 1%：invest=50000，扣 50500；卖出收 109%：position=500股×110×0.99
        expected = 100000 - 50000 * 1.01 + (50000 / 100) * 110 * 0.99
        assert res.final_capital == pytest.approx(expected)

    def test_tuple_buy_frac(self):
        def sig(i, rsi, sma_f, sma_s, vol, position):
            return ('buy', 0.5)
        close = np.array([100.0, 100.0])
        res = backtest_core.simulate(close, 0, sig, 0.05, 0.15, 0.1)
        assert res.final_capital == pytest.approx(100000.0)  # 平收，无费

    def test_sell_only_when_holding(self):
        # 空仓时 sell 信号无效
        close = np.array([100.0, 101.0, 102.0])

        def sig(i, rsi, sma_f, sma_s, vol, position):
            return 'sell'
        res = backtest_core.simulate(close, 0, sig, 0.05, 0.15, 0.5)
        assert res.trades == []

    def test_position_aware_signal(self):
        # unified 结构：空仓判买、持仓判卖（互斥分流，可当日再入场）
        close = np.array([100.0, 101.0, 102.0, 101.5])

        def sig(i, rsi, sma_f, sma_s, vol, position):
            return 'buy' if position == 0 else 'sell'
        res = backtest_core.simulate(close, 0, sig, 0.05, 0.15, 0.5)
        assert res.trades == [pytest.approx(0.01), pytest.approx((101.5 - 102) / 102)]


class TestFitnessScore:
    def test_empty_trades_zero(self):
        assert backtest_core.fitness_score([], 100000.0) == 0.0

    def test_all_wins_beats_all_losses(self):
        # 公式上限 1.0（收益 0.3 + 夏普 0.2 + 回撤 0.2 + 胜率 0.2 + 频次 0.1）
        wins = backtest_core.fitness_score([0.05] * 10, 110000.0)
        losses = backtest_core.fitness_score([-0.05] * 10, 90000.0)
        assert 0.0 < losses < wins < 1.0

    def test_formula_bounds(self):
        # 收益封顶 [-0.5, 1.0]，夏普钳制 [-3, 3]
        score = backtest_core.fitness_score([5.0, -3.0, 0.1], 200000.0)
        assert 0.0 <= score <= 1.0


class TestKernelEquivalence:
    """合并等价性：unified_evolve 经 make_fitness（4 折滚动）的输出
    == 手工按 fold 调内核的复现结果"""

    def test_unified_fitness_equals_manual_fold_computation(self):
        from strategy.unified_evolve import make_fitness
        from evolution.learning_loop import StrategyGene
        data = make_random_data()
        fitness = make_fitness(data)
        gene = StrategyGene(id="g1", params={
            "rsi_period": 14, "sma_fast": 5, "sma_slow": 20,
            "stop_loss": 0.05, "take_profit": 0.15,
            "rsi_oversold": 30, "rsi_overbought": 70})

        close = data['close'].values
        n = len(close)

        def _signal(i, rsi_arr, sf, ss, _vol, position):
            if np.isnan(sf[i]) or np.isnan(ss[i]):
                return 'hold'
            if position > 0:
                if rsi_arr[i] > 70:
                    return 'sell'
                if sf[i] < ss[i] and sf[i-1] >= ss[i-1]:
                    return 'sell'
                return 'hold'
            if rsi_arr[i] < 30:
                return ('buy', 0.2 * 0.85)
            if sf[i] > ss[i] and sf[i-1] <= ss[i-1]:
                return ('buy', 0.2 * 0.65)
            return 'hold'

        # 复现 make_fitness 的 4 折滚动验证
        folds, seg_len = 4, n // 4
        scores = []
        for k in range(folds):
            start = k * seg_len
            end = n if k == folds - 1 else (k + 1) * seg_len
            seg = close[start:end]
            rsi = backtest_core.calc_rsi(seg, 14)
            sma_f = backtest_core.calc_sma(seg, 5)
            sma_s = backtest_core.calc_sma(seg, 20)
            res = backtest_core.simulate(seg, 20, _signal, 0.05, 0.15, 0.2,
                                         rsi=rsi, sma_f=sma_f, sma_s=sma_s)
            if len(res.trades) >= 2:
                scores.append(backtest_core.fitness_score(res.trades, res.final_capital))

        # rsi_period=14≥7, sma_fast=5≥3, sl=0.05≥0.03 → 复杂度惩罚为 0
        expected = max(0.01, float(np.mean(scores)) - float(np.std(scores)) * 0.3)
        assert fitness(gene) == pytest.approx(expected, rel=1e-12)


# P3b 意图修复后的新黄金值（原退化值：rsi_reversal 0.328/0.449、sma_cross 0.01/0.01）
MD_FIXED_GOLDEN = {
    "random": {"rsi_reversal": 0.5858220899993972, "sma_cross": 0.5230769663084993},
    "oscillating": {"rsi_reversal": 0.7086015970638209, "sma_cross": 0.25478294723813977},
}


class TestIntentionalFixes:
    """P3b 修复：multi_dim 指标数组恒零 → 传入真实 RSI/SMA"""

    @pytest.mark.parametrize("dataset", ["random", "oscillating"])
    @pytest.mark.parametrize("template", ["rsi_reversal", "sma_cross"])
    def test_fixed_template_golden(self, dataset, template):
        from evolution.multi_dim_evolve import MultiDimEvolution, STRATEGY_TEMPLATES
        from evolution.learning_loop import StrategyGene
        data = make_random_data() if dataset == "random" else make_oscillating_data()
        eng = MultiDimEvolution()
        ff = eng._make_fitness(data, STRATEGY_TEMPLATES[template])
        gene = StrategyGene(id=f"md_{template}", params=dict(MD_PARAMS))
        assert ff(gene) == pytest.approx(MD_FIXED_GOLDEN[dataset][template], rel=1e-9)

    def test_rsi_template_trades_more_than_degenerate(self):
        """修复后 rsi_reversal 应产生多笔交易（原退化为单笔持有）"""
        from evolution.multi_dim_evolve import MultiDimEvolution
        data = make_oscillating_data()
        eng = MultiDimEvolution()
        close = data['close'].values
        rsi = backtest_core.calc_rsi(close, 14)

        def sig(i, rsi_arr, sf, ss, vol, position):
            return 'buy' if rsi_arr[i] < 30 else ('sell' if rsi_arr[i] > 70 else 'hold')

        res = backtest_core.simulate(close, 14, sig, 0.05, 0.15, 0.2, rsi=rsi)
        assert len(res.trades) >= 3

    def test_sma_cross_template_actually_trades(self):
        """修复后 sma_cross 应产生交易（原恒返回 0.01）"""
        from evolution import backtest_core as bc
        data = make_oscillating_data()
        close = data['close'].values
        sma_f = bc.calc_sma(close, 5)
        sma_s = bc.calc_sma(close, 20)

        def sig(i, rsi, sf, ss, vol, position):
            return ('buy' if sf[i] > ss[i] and sf[i-1] <= ss[i-1] else
                    'sell' if sf[i] < ss[i] and sf[i-1] >= ss[i-1] else 'hold')

        res = bc.simulate(close, 20, sig, 0.05, 0.15, 0.2, sma_f=sma_f, sma_s=sma_s)
        assert len(res.trades) >= 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
