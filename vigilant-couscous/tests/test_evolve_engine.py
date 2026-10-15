"""
evolve_engine 公共编排层单元测试（P3b）

覆盖：
- fetch_history：取数参数与委托（stub DataFetcher）
- run_ga：GA 装配/种子注入/配置口径（unified 与 multi 两套参数）
- validate_params：无数据/异常返回 None、正常返回结果 dict
- register_strategy：gh_strategy_library.json 写入结构
- 两个调用方经编排层的端到端行为（stub 取数，禁网）
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _synthetic_df(n=200, seed=3):
    np.random.seed(seed)
    t = np.arange(n)
    close = 50000 * (1 + 0.05 * np.sin(2 * np.pi * t / 25)) * (1 + np.random.randn(n) * 0.004)
    return pd.DataFrame({
        'close': close,
        'high': close * 1.002,
        'low': close * 0.998,
        'volume': 900 + np.random.rand(n) * 100,
    })


class TestFetchHistory:
    def test_delegates_to_fetcher_with_365_days(self, monkeypatch):
        import data.fetcher
        calls = {}

        class FakeFetcher:
            def __init__(self, okx_url=None):
                calls['okx_url'] = okx_url

            def fetch(self, symbol, start_date=None, end_date=None, source=None):
                calls['symbol'] = symbol
                calls['start_date'] = start_date
                calls['end_date'] = end_date
                calls['source'] = source
                return _synthetic_df(50)

        monkeypatch.setattr(data.fetcher, 'DataFetcher', FakeFetcher)
        from evolution import evolve_engine
        df = evolve_engine.fetch_history('ETH/USDT', days=365)
        assert len(df) == 50
        assert calls['symbol'] == 'ETH/USDT'
        assert calls['source'] == 'ccxt'
        assert calls['okx_url'] is not None
        # 365 天窗口
        from datetime import datetime
        d0 = datetime.strptime(calls['start_date'], '%Y-%m-%d')
        d1 = datetime.strptime(calls['end_date'], '%Y-%m-%d')
        assert (d1 - d0).days == 365


class TestRunGa:
    def test_returns_engine_and_best(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)  # 隔离 _internalize 的 memory/iterations 写入
        from evolution import evolve_engine

        def fitness_factory(data):
            def fitness(gene, _=None):
                return 0.5
            return fitness

        engine, best = evolve_engine.run_ga(
            _synthetic_df(), {"a": (1, 10)}, fitness_factory,
            generations=3, population=6)
        assert engine.generation == 3
        assert best is not None and best.fitness == 0.5
        assert engine.config.population_size == 6
        assert engine.config.elite_count == max(3, 6 // 8)  # 缺省 unified 口径
        assert engine.config.early_stop_generations == 80

    def test_multi_config_override(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from evolution import evolve_engine

        def ff(data):
            return lambda gene, _=None: 0.1

        engine, best = evolve_engine.run_ga(
            _synthetic_df(), {"a": (1, 10)}, ff,
            generations=2, population=20,
            elite_count=max(2, 20 // 10), early_stop_generations=30)
        assert engine.config.elite_count == 2
        assert engine.config.early_stop_generations == 30

    def test_seed_genes_injection(self, monkeypatch, tmp_path):
        """种子基因经 run_evolution 透传进初始种群并实际参与进化

        2026-10-16 P3b 修复验证：原实现在 initialize_population 之后注入种子，
        但 run_evolution 内部重新初始化把种子清空（静默失效）。
        恒定适应度下排序稳定，一代后精英前排即种子基因（确定性断言）。
        """
        monkeypatch.chdir(tmp_path)
        from evolution import evolve_engine

        def ff(data):
            return lambda gene, _=None: 0.1

        seeds = [{"params": {"a": 7}}, {"params": {"a": 9}}]
        engine, best = evolve_engine.run_ga(
            _synthetic_df(), {"a": (1, 10)}, ff,
            generations=1, population=6, seed_genes=seeds)
        # 一代后：精英保留（population[0:3] 由种子占据前二），且最优即种子
        assert best.id == "seed_0" and best.params == {"a": 7}
        assert engine.population[0].params == {"a": 7}
        assert engine.population[0].parent_ids == ["seed_0"]
        assert engine.population[1].params == {"a": 9}

    def test_ready_made_fitness_accepted(self, monkeypatch, tmp_path):
        """fitness_factory 统一为工厂语义：data -> fitness_func"""
        monkeypatch.chdir(tmp_path)
        from evolution import evolve_engine
        engine, best = evolve_engine.run_ga(
            _synthetic_df(), {"a": (1, 10)},
            lambda data: (lambda gene, _=None: 0.2),
            generations=1, population=4)
        assert best.fitness == 0.2


class TestValidateParams:
    def test_none_for_missing_data(self):
        from evolution import evolve_engine
        assert evolve_engine.validate_params(None, {"a": 1}, "x") is None
        assert evolve_engine.validate_params(pd.DataFrame(), {"a": 1}, "x") is None

    def test_returns_result_dict(self):
        from evolution import evolve_engine
        res = evolve_engine.validate_params(
            _synthetic_df(), {"rsi_period": 14, "sma_fast": 5, "sma_slow": 20,
                              "stop_loss": 0.05, "take_profit": 0.15}, "t")
        assert res is not None
        assert set(res) == {'passed', 'score', 'sharpe', 'return',
                            'max_drawdown', 'warnings', 'total_trades'}
        assert isinstance(res['passed'], bool)


class TestRegisterStrategy:
    def test_writes_library_entry(self, tmp_path):
        from evolution import evolve_engine
        params = {"rsi_period": 14, "sma_fast": 5, "stop_loss": 0.05}
        name = evolve_engine.register_strategy(
            params, 0.42, nexus_dir=tmp_path, source='test', passed=True)
        assert name.startswith('evolved_')
        lib = json.loads((tmp_path / 'gh_strategy_library.json').read_text(encoding='utf-8'))
        assert lib['total_strategies'] == 1
        entry = lib['strategies'][0]
        assert entry['name'] == name
        assert entry['source'] == 'test'
        assert entry['stars'] == int(0.42 * 1000)
        assert entry['backtest_passed'] is True
        assert entry['rsi_period'] == 14

    def test_appends_to_existing(self, tmp_path):
        from evolution import evolve_engine
        evolve_engine.register_strategy({"a": 1}, 0.5, nexus_dir=tmp_path)
        evolve_engine.register_strategy({"a": 2}, 0.6, nexus_dir=tmp_path, passed=False)
        lib = json.loads((tmp_path / 'gh_strategy_library.json').read_text(encoding='utf-8'))
        assert lib['total_strategies'] == 2
        assert lib['strategies'][1]['backtest_passed'] is False


class TestUnifiedDelegation:
    """unified_evolve 经编排层的端到端行为"""

    def test_run_evolution_delegates(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from strategy import unified_evolve
        data = _synthetic_df(300)
        engine, best = unified_evolve.run_evolution(data, generations=2, population=6)
        assert engine.generation == 2
        assert best is not None
        # 默认模板 7 参数
        assert set(best.params) == {"rsi_period", "sma_fast", "sma_slow",
                                    "stop_loss", "take_profit",
                                    "rsi_oversold", "rsi_overbought"}

    def test_validate_and_update_registers(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from strategy import unified_evolve
        unified_evolve.NEXUS = tmp_path  # 隔离策略库写入
        # fitness >= 0.3 且验证异常/无数据 → unified 口径放行入库
        n = unified_evolve._validate_and_update(
            {"rsi_period": 14}, 0.5, None, mode="test")
        assert n == 1
        lib = json.loads((tmp_path / 'gh_strategy_library.json').read_text(encoding='utf-8'))
        assert lib['strategies'][0]['source'] == 'self-evolution'

    def test_low_fitness_skips(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from strategy import unified_evolve
        unified_evolve.NEXUS = tmp_path
        assert unified_evolve._validate_and_update({"a": 1}, 0.1, None, "test") == 0
        assert not (tmp_path / 'gh_strategy_library.json').exists()


class TestMultiDimDelegation:
    """multi_dim_evolve 经编排层的端到端行为（stub 取数，禁网）"""

    def test_evolve_single_end_to_end(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from evolution.multi_dim_evolve import MultiDimEvolution, STRATEGY_TEMPLATES
        eng = MultiDimEvolution()
        monkeypatch.setattr(eng, '_fetch_data', lambda symbol: _synthetic_df(300))
        result = eng._evolve_single('BTC/USDT', 'sma_cross', generations=2, population=6)
        assert result['symbol'] == 'BTC/USDT'
        assert result['strategy'] == 'sma_cross'
        assert result['category'] == STRATEGY_TEMPLATES['sma_cross'].category
        assert isinstance(result['passed'], bool)
        assert 'params' in result and 'fitness' in result

    def test_evolve_single_data_failure(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from evolution.multi_dim_evolve import MultiDimEvolution
        eng = MultiDimEvolution()
        monkeypatch.setattr(eng, '_fetch_data', lambda symbol: pd.DataFrame())
        assert eng._evolve_single('BTC/USDT', 'sma_cross', 1, 4) == {"error": "数据获取失败"}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
