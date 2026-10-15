"""
基础单元测试
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_import_main():
    """测试 FastAPI 应用可导入"""
    from backend.main import app
    assert app.title == 'QuantTrading API'


def test_indicator_engine():
    """测试指标引擎初始化"""
    from backend.indicators.indicator_engine import get_indicator_engine
    e = get_indicator_engine()
    assert e.get_indicator_count() > 400
    cats = e.get_categories()
    assert 'trend' in cats
    assert 'momentum' in cats


def test_backtest_engine():
    """测试回测引擎基本功能"""
    from backend.core.backtest_engine import get_backtest_engine
    e = get_backtest_engine()
    assert e.initial_capital == 100000
    assert e.stop_loss_pct == 5.0
    assert e.max_position_pct == 0.95
    assert e.max_drawdown_pct == 20.0


def test_rate_limiter():
    """测试限速器"""
    from backend.core.rate_limiter import RateLimiter
    rl = RateLimiter(max_calls=5, window_seconds=1)
    for _ in range(5):
        rl.acquire()
    status = rl.get_status()
    assert status['current_calls'] == 5


def test_auth_middleware():
    """测试认证中间件路径判断"""
    from backend.core.auth import is_protected
    assert is_protected('/api/orders/pending') == True
    assert is_protected('/api/fills') == True
    assert is_protected('/api/klines/BTC-USDT') == False
    assert is_protected('/api/indicators') == False
    assert is_protected('/health') == False
