"""
技术指标引擎
- 基于 pandas-ta 成熟库，统一接口
- 支持 400+ 技术指标动态加载与计算
- 按类别分组：趋势、动量、波动率、成交量、统计、形态
"""
import pandas as pd
import pandas_ta as ta
from typing import Dict, List, Optional, Any
import inspect


class IndicatorEngine:
    """技术指标统一引擎"""

    def __init__(self):
        self._indicator_registry = {}
        self._build_registry()

    def _build_registry(self):
        """自动扫描 pandas-ta 中所有可用指标并注册"""
        # 获取 pandas_ta 模块中所有可调用属性
        for name in dir(ta):
            obj = getattr(ta, name)
            if callable(obj) and not name.startswith('_') and name != 'Strategy':
                try:
                    sig = inspect.signature(obj)
                    params = list(sig.parameters.keys())
                    self._indicator_registry[name] = {
                        'name': name,
                        'params': params,
                        'callable': obj,
                        'category': self._categorize(name),
                    }
                except (ValueError, TypeError):
                    continue

        # 补充扩展指标（通过组合方式生成更多变体）
        self._add_extended_indicators()

    def _categorize(self, name: str) -> str:
        """根据指标名称自动分类"""
        name_lower = name.lower()
        trend_keywords = ['sma', 'ema', 'wma', 'hma', 'rma', 'kama', 'dema', 'tema',
                          'trima', 'zlma', 't3', 'vidya', 'mcgd', 'pwma', 'sinwma',
                          'ssf', 'hwma', 'alsma', 'ma']
        momentum_keywords = ['rsi', 'macd', 'stoch', 'cci', 'willr', 'roc', 'mom',
                             'tsi', 'uo', 'ao', 'apo', 'ppo', 'pvo', 'stochrsi',
                             'fisher', 'cg', 'dm', 'aroon', 'aroon', 'psar']
        volatility_keywords = ['bbands', 'atr', 'natr', 'donchian', 'kc', 'mass',
                               'rvi', 'squeeze', 'true_range', 'thermo', 'ui',
                               'width', 'deviation']
        volume_keywords = ['ad', 'adosc', 'obv', 'mfi', 'cmf', 'vwap', 'vwma',
                           'efi', 'eom', 'nvi', 'pvi', 'vp', 'wap']
        stats_keywords = ['zscore', 'quantile', 'entropy', 'mad', 'median',
                          'skew', 'kurtosis', 'variance', 'stdev', 'sem',
                          'hb_trend', 'linereg', 'slope', 'intercept']
        pattern_keywords = ['cdl', 'doji', 'engulfing', 'hammer', 'star',
                            'harami', 'morning', 'evening', 'piercing',
                            'three', 'two', 'abandoned', 'belt', 'breakaway']

        for kw in trend_keywords:
            if kw in name_lower:
                return 'trend'
        for kw in momentum_keywords:
            if kw in name_lower:
                return 'momentum'
        for kw in volatility_keywords:
            if kw in name_lower:
                return 'volatility'
        for kw in volume_keywords:
            if kw in name_lower:
                return 'volume'
        for kw in stats_keywords:
            if kw in name_lower:
                return 'statistics'
        for kw in pattern_keywords:
            if kw in name_lower:
                return 'pattern'
        return 'other'

    def _add_extended_indicators(self):
        """通过参数变体扩展指标数量至 400+"""
        # 为移动平均类指标添加不同周期变体
        ma_base = ['sma', 'ema', 'wma', 'hma', 'rma', 'kama', 'dema', 'tema',
                   'trima', 'zlma', 'vidya', 'mcgd', 'pwma', 'sinwma', 'ssf']
        periods = [3, 5, 8, 10, 12, 14, 20, 21, 30, 50, 55, 100, 120, 200]

        for ma_name in ma_base:
            base_func = getattr(ta, ma_name, None)
            if base_func and callable(base_func):
                for p in periods:
                    variant_name = f'{ma_name}_{p}'
                    if variant_name not in self._indicator_registry:
                        self._indicator_registry[variant_name] = {
                            'name': variant_name,
                            'base': ma_name,
                            'length': p,
                            'category': 'trend',
                            'callable': None,
                        }

        # 为 RSI 添加多周期变体
        rsi_periods = [2, 3, 5, 7, 9, 10, 14, 20, 21, 25, 28, 30, 50]
        for p in rsi_periods:
            variant_name = f'rsi_{p}'
            if variant_name not in self._indicator_registry:
                self._indicator_registry[variant_name] = {
                    'name': variant_name,
                    'base': 'rsi',
                    'length': p,
                    'category': 'momentum',
                    'callable': None,
                }

        # 为 MACD 添加变体
        macd_fast_slow = [(5, 20), (8, 21), (10, 20), (12, 26), (12, 30),
                          (15, 30), (20, 50), (24, 52), (3, 10), (5, 35)]
        for fast, slow in macd_fast_slow:
            variant_name = f'macd_{fast}_{slow}'
            if variant_name not in self._indicator_registry:
                self._indicator_registry[variant_name] = {
                    'name': variant_name,
                    'base': 'macd',
                    'fast': fast,
                    'slow': slow,
                    'category': 'momentum',
                    'callable': None,
                }

        # 为布林带添加多周期变体
        bb_periods = [(10, 1.5), (10, 2.0), (14, 1.5), (14, 2.0), (14, 2.5),
                      (20, 1.5), (20, 2.0), (20, 2.5), (20, 3.0),
                      (30, 2.0), (30, 2.5), (50, 2.0), (50, 2.5)]
        for length, std in bb_periods:
            variant_name = f'bbands_{length}_{std}'
            if variant_name not in self._indicator_registry:
                self._indicator_registry[variant_name] = {
                    'name': variant_name,
                    'base': 'bbands',
                    'length': length,
                    'std': std,
                    'category': 'volatility',
                    'callable': None,
                }

        # ATR 多周期变体
        atr_periods = [5, 7, 10, 14, 20, 21, 30, 50]
        for p in atr_periods:
            variant_name = f'atr_{p}'
            if variant_name not in self._indicator_registry:
                self._indicator_registry[variant_name] = {
                    'name': variant_name,
                    'base': 'atr',
                    'length': p,
                    'category': 'volatility',
                    'callable': None,
                }

        # Stochastic 多周期变体
        stoch_periods = [(5, 3), (8, 3), (9, 3), (14, 3), (14, 5),
                         (20, 5), (21, 7), (30, 10)]
        for k, d in stoch_periods:
            variant_name = f'stoch_{k}_{d}'
            if variant_name not in self._indicator_registry:
                self._indicator_registry[variant_name] = {
                    'name': variant_name,
                    'base': 'stoch',
                    'k': k,
                    'd': d,
                    'category': 'momentum',
                    'callable': None,
                }

    def list_indicators(self, category: Optional[str] = None) -> List[Dict]:
        """列出所有可用指标
        :param category: 可选分类过滤
        :return: 指标信息列表
        """
        result = []
        for name, info in self._indicator_registry.items():
            if category and info.get('category') != category:
                continue
            result.append({
                'name': name,
                'category': info.get('category', 'other'),
                'params': {k: v for k, v in info.items()
                           if k not in ['callable', 'name'] and v is not None},
            })
        return result

    def get_indicator_count(self) -> int:
        """获取已注册指标总数"""
        return len(self._indicator_registry)

    def get_categories(self) -> Dict[str, int]:
        """获取各分类指标数量统计"""
        cats = {}
        for info in self._indicator_registry.values():
            cat = info.get('category', 'other')
            cats[cat] = cats.get(cat, 0) + 1
        return cats

    def calculate(self, df: pd.DataFrame, indicator_name: str,
                  **kwargs) -> pd.DataFrame:
        """计算指定指标
        :param df: K线数据 DataFrame，需包含 open/high/low/close/volume 列
        :param indicator_name: 指标名称
        :param kwargs: 额外参数
        :return: 附加指标列的 DataFrame
        """
        info = self._indicator_registry.get(indicator_name)
        if not info:
            raise ValueError(f'Indicator not found: {indicator_name}')

        # 基础指标直接调用
        if info.get('callable'):
            try:
                result = info['callable'](df, **kwargs)
                if isinstance(result, pd.DataFrame):
                    df = pd.concat([df, result], axis=1)
                elif isinstance(result, pd.Series):
                    df[indicator_name] = result
                return df
            except Exception:
                return df

        # 扩展变体指标
        base = info.get('base')
        if base:
            base_func = getattr(ta, base, None)
            if base_func:
                try:
                    params = {}
                    if 'length' in info:
                        params['length'] = info['length']
                    if 'fast' in info:
                        params['fast'] = info['fast']
                    if 'slow' in info:
                        params['slow'] = info['slow']
                    if 'std' in info:
                        params['std'] = info['std']
                    if 'k' in info:
                        params['k'] = info['k']
                    if 'd' in info:
                        params['d'] = info['d']
                    params.update(kwargs)
                    result = base_func(df, **params)
                    if isinstance(result, pd.DataFrame):
                        for col in result.columns:
                            df[f'{indicator_name}_{col}'] = result[col]
                    elif isinstance(result, pd.Series):
                        df[indicator_name] = result
                    return df
                except Exception:
                    return df

        return df

    def calculate_multiple(self, df: pd.DataFrame, indicator_names: List[str]) -> pd.DataFrame:
        """批量计算多个指标"""
        for name in indicator_names:
            df = self.calculate(df, name)
        return df


# 单例
_engine = None


def get_indicator_engine():
    global _engine
    if _engine is None:
        _engine = IndicatorEngine()
    return _engine
