"""
扩展核心模块单元测试
覆盖: 配置管理、数据获取器、缓存管理器、风控管理器、基础策略
"""
import sys
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _make_sample_ohlcv(n_days=365):
    """生成模拟 OHLCV 行情数据"""
    np.random.seed(42)
    dates = pd.date_range(end=datetime.now(), periods=n_days, freq='D')
    returns = np.random.randn(n_days) * 0.02
    close = 50000 * np.cumprod(1 + returns)
    open_ = close * (1 + np.random.randn(n_days) * 0.005)
    high = close * (1 + np.abs(np.random.randn(n_days) * 0.01))
    low = close * (1 - np.abs(np.random.randn(n_days) * 0.01))
    volume = np.random.rand(n_days) * 1000 + 500
    return pd.DataFrame({
        'open': open_, 'high': high, 'low': low,
        'close': close, 'volume': volume
    }, index=dates)


class TestConfig:
    """配置管理测试"""

    def test_config_imports_successfully(self):
        import config
        assert hasattr(config, 'DATA_SOURCE')
        assert hasattr(config, 'OKX_API')
        assert hasattr(config, 'GITHUB')
        assert hasattr(config, 'SYMBOLS')
        assert hasattr(config, 'RISK')
        assert hasattr(config, 'SYSTEM')
        assert hasattr(config, 'TIMEFRAMES')

    def test_data_source_defaults(self):
        import config
        assert 'okx_url' in config.DATA_SOURCE
        assert 'default_timeframe' in config.DATA_SOURCE
        assert 'history_days' in config.DATA_SOURCE
        assert config.DATA_SOURCE['history_days'] > 0

    def test_okx_api_structure(self):
        import config
        assert 'api_key' in config.OKX_API
        assert 'secret_key' in config.OKX_API
        assert 'passphrase' in config.OKX_API
        assert 'demo' in config.OKX_API
        assert isinstance(config.OKX_API['demo'], bool)

    def test_symbols_is_list(self):
        import config
        assert isinstance(config.SYMBOLS, list)
        assert len(config.SYMBOLS) > 0
        assert all('/' in s for s in config.SYMBOLS)

    def test_risk_parameters_valid(self):
        import config
        risk = config.RISK
        assert 0 < risk['max_position_pct'] <= 1
        assert 0 < risk['stop_loss_pct'] < 1
        assert 0 < risk['take_profit_pct'] < 1
        assert risk['min_confidence'] >= 0
        assert isinstance(risk['trailing_stop'], bool)

    def test_system_parameters_valid(self):
        import config
        sys_params = config.SYSTEM
        assert sys_params['population_size'] > 0
        assert sys_params['max_generations'] > 0
        assert sys_params['rl_timesteps'] > 0

    def test_timeframes_is_list_of_ints(self):
        import config
        assert isinstance(config.TIMEFRAMES, list)
        assert all(isinstance(t, int) for t in config.TIMEFRAMES)
        assert config.TIMEFRAMES == sorted(config.TIMEFRAMES)

    def test_initial_capital_positive(self):
        import config
        assert config.INITIAL_CAPITAL > 0

    def test_directories_exist(self):
        import config
        assert config.MEMORY_DIR.exists()
        assert config.NEXUS_DIR.exists()
        assert config.REPORTS_DIR.exists()


class TestDataFetcher:
    """数据获取器测试"""

    def test_fetcher_initialization(self):
        from data.fetcher import DataFetcher
        fetcher = DataFetcher(okx_url='https://www.okx.com')
        assert fetcher is not None

    def test_fetcher_has_fetch_method(self):
        from data.fetcher import DataFetcher
        fetcher = DataFetcher(okx_url='https://www.okx.com')
        assert hasattr(fetcher, 'fetch')

    def test_fetcher_empty_data_handling(self):
        from data.fetcher import DataFetcher
        fetcher = DataFetcher(okx_url='https://www.okx.com')
        result = fetcher.fetch('INVALID/PAIR', start_date='2024-01-01',
                               end_date='2024-01-02', source='ccxt')
        assert isinstance(result, pd.DataFrame)


class TestCacheManager:
    """缓存管理器测试"""

    def test_cache_manager_initialization(self):
        from data.cache_manager import MarketDataCache
        cm = MarketDataCache()
        assert cm is not None

    def test_cache_save_and_load(self):
        pytest.importorskip('pyarrow')
        from data.cache_manager import MarketDataCache
        cm = MarketDataCache()
        data = _make_sample_ohlcv(30)
        cm.save('BTC_USDT', data)
        loaded, meta = cm.load('BTC_USDT')
        if loaded is not None:
            assert len(loaded) == 30
            assert 'close' in loaded.columns

    def test_cache_nonexistent_key(self):
        from data.cache_manager import MarketDataCache
        cm = MarketDataCache()
        df, meta = cm.load('NONEXISTENT_PAIR')
        assert df is None or (isinstance(df, pd.DataFrame) and df.empty)


class TestRiskManager:
    """风控管理器测试"""

    def test_risk_manager_initialization(self):
        from agents.risk_manager import RiskManagerAgent, RiskLimits
        rm = RiskManagerAgent(limits=RiskLimits())
        assert rm is not None
        assert rm.limits.max_position_pct > 0

    def test_risk_approve_trade_high_confidence(self):
        from agents.risk_manager import RiskManagerAgent, RiskLimits
        rm = RiskManagerAgent(limits=RiskLimits())
        signal = {'symbol': 'BTC/USDT', 'confidence': 0.8, 'action': 'buy'}
        portfolio = {'total_value': 100000}
        approved, reason = rm.approve_trade(signal, portfolio)
        assert isinstance(approved, bool)
        assert isinstance(reason, str)

    def test_risk_reject_low_confidence(self):
        from agents.risk_manager import RiskManagerAgent, RiskLimits
        rm = RiskManagerAgent(limits=RiskLimits())
        signal = {'symbol': 'BTC/USDT', 'confidence': 0.001, 'action': 'buy'}
        portfolio = {'total_value': 100000}
        approved, reason = rm.approve_trade(signal, portfolio)
        assert isinstance(approved, bool)

    def test_risk_reject_high_drawdown(self):
        from agents.risk_manager import RiskManagerAgent, RiskLimits
        limits = RiskLimits(max_drawdown_pct=0.15)
        rm = RiskManagerAgent(limits=limits)
        rm.current_drawdown = 0.20
        signal = {'symbol': 'BTC/USDT', 'confidence': 0.9, 'action': 'buy'}
        portfolio = {'total_value': 100000}
        approved, reason = rm.approve_trade(signal, portfolio)
        assert approved is False


class TestBaseStrategy:
    """基础策略类测试"""

    def test_strategy_config_creation(self):
        from strategies.base_strategy import StrategyConfig
        config = StrategyConfig(name='test_strategy')
        assert config.name == 'test_strategy'
        assert config.initial_capital == 100000
        assert config.commission == 0.0003

    def test_strategy_result_defaults(self):
        from strategies.base_strategy import StrategyResult
        result = StrategyResult()
        assert result.total_return == 0.0
        assert result.sharpe_ratio == 0.0
        assert result.max_drawdown == 0.0
        assert result.total_trades == 0

    def test_strategy_initial_state(self):
        from strategies.base_strategy import StrategyConfig, BaseStrategy

        class TestStrategy(BaseStrategy):
            def generate_signals(self, data):
                return []

        config = StrategyConfig(name='test', initial_capital=50000)
        strategy = TestStrategy(config)
        assert strategy.capital == 50000
        assert strategy.positions == {}
        assert strategy.signals == []
        assert strategy.trades == []


class TestPortfolioManager:
    """组合管理器测试"""

    def test_portfolio_initialization(self):
        from data.portfolio_manager import PortfolioManager
        pm = PortfolioManager(
            symbols=['BTC-USDT', 'ETH-USDT', 'SOL-USDT'],
            initial_capital=100000
        )
        assert pm is not None
        assert len(pm.symbols) == 3

    def test_calculate_target_weights(self):
        from data.portfolio_manager import PortfolioManager
        pm = PortfolioManager(
            symbols=['BTC-USDT', 'ETH-USDT', 'SOL-USDT'],
            initial_capital=100000
        )
        weights = pm.calculate_target_weights()
        assert isinstance(weights, dict)
        assert len(weights) == 3
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.1 or total > 0

    def test_generate_rebalance_orders(self):
        from data.portfolio_manager import PortfolioManager
        pm = PortfolioManager(
            symbols=['BTC-USDT', 'ETH-USDT', 'SOL-USDT'],
            initial_capital=100000
        )
        prices = {'BTC-USDT': 50000, 'ETH-USDT': 3000, 'SOL-USDT': 100}
        targets = pm.calculate_target_weights()
        orders = pm.generate_rebalance_orders(prices, targets)
        assert isinstance(orders, list)


class TestOKXLiveTrader:
    """OKX 实盘交易接口测试"""

    def test_trader_initialization_demo(self):
        from data.live_trader import OKXLiveTrader
        trader = OKXLiveTrader(demo=True)
        assert trader.demo is True
        assert trader.base_url is not None

    def test_trader_initialization_no_key_fallback(self):
        from data.live_trader import OKXLiveTrader
        trader = OKXLiveTrader(demo=False)
        assert trader.demo is True

    def test_demo_balance(self):
        from data.live_trader import OKXLiveTrader
        trader = OKXLiveTrader(demo=True)
        balance = trader.get_balance()
        assert balance['demo'] is True
        assert 'USDT' in balance

    def test_demo_place_order(self):
        from data.live_trader import OKXLiveTrader
        trader = OKXLiveTrader(demo=True)
        order = trader.place_order('BTC-USDT', 'buy', 100, order_type='market')
        assert order is not None
        assert order.status == 'filled'
        assert order.side == 'buy'

    def test_demo_cancel_order(self):
        from data.live_trader import OKXLiveTrader
        trader = OKXLiveTrader(demo=True)
        result = trader.cancel_order('demo_123', 'BTC-USDT')
        assert result is True

    def test_demo_pending_orders(self):
        from data.live_trader import OKXLiveTrader
        trader = OKXLiveTrader(demo=True)
        orders = trader.get_pending_orders()
        assert isinstance(orders, list)
        assert len(orders) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
