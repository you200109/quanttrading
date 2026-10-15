"""
vc 模块深度整合适配器
使 vigilant-couscous 的 strategy/trading 模块复用主系统 OKX 数据服务和回测引擎
"""
import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger('QuantTrading.vc_adapter')

# 将 vc 目录加入 sys.path
VC_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'vigilant-couscous'))
if VC_ROOT not in sys.path:
    sys.path.insert(0, VC_ROOT)


class VCDataAdapter:
    """适配器：将主系统 OKX 数据服务适配为 vc 模块可用的接口"""

    def __init__(self):
        from backend.core.okx_data_service import get_data_service
        self._svc = get_data_service()

    def fetch(self, symbol, start_date=None, end_date=None, source='ccxt', **kwargs):
        """复用主系统数据服务获取K线数据，返回 vc 模块期望的 DataFrame 格式"""
        import pandas as pd
        # 将 vc 格式 symbol (BTC/USDT) 转为主系统格式 (BTC-USDT)
        inst_id = symbol.replace('/', '-')
        bar = kwargs.get('bar', '1D')
        limit = kwargs.get('limit', '300')
        raw = self._svc.get_candlesticks(inst_id, bar, limit)
        if not raw:
            return pd.DataFrame()
        cols = ['ts', 'open', 'high', 'low', 'close', 'vol', 'volCcy', 'volCcyQuote', 'confirm']
        df = pd.DataFrame(raw, columns=cols)
        for c in ['open', 'high', 'low', 'close', 'vol']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df['ts'] = pd.to_datetime(df['ts'].astype(float), unit='ms')
        return df

    def get_ticker(self, symbol):
        """获取实时行情"""
        inst_id = symbol.replace('/', '-') if '/' in symbol else symbol
        return self._svc.get_ticker(inst_id)

    def get_orderbook(self, symbol, depth=5):
        """获取盘口深度"""
        inst_id = symbol.replace('/', '-') if '/' in symbol else symbol
        return self._svc.get_orderbook(inst_id, str(depth))


class VCBacktestAdapter:
    """适配器：将主系统回测引擎适配为 vc 模块可用的接口"""

    def __init__(self):
        from backend.core.backtest_engine import get_backtest_engine
        self._engine = get_backtest_engine()

    def run(self, df, strategy, params):
        """复用主系统回测引擎"""
        return self._engine.run(df, strategy, params)


def get_vc_data_adapter():
    """获取 vc 数据适配器单例"""
    if not hasattr(get_vc_data_adapter, '_instance'):
        get_vc_data_adapter._instance = VCDataAdapter()
    return get_vc_data_adapter._instance


def get_vc_backtest_adapter():
    """获取 vc 回测适配器单例"""
    if not hasattr(get_vc_backtest_adapter, '_instance'):
        get_vc_backtest_adapter._instance = VCBacktestAdapter()
    return get_vc_backtest_adapter._instance
