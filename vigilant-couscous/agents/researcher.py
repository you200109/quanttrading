"""
研究员 Agent - 400 指标版
多时间框架 × 核心指标 = 200+ 指标 + 衍生指标 + 形态识别

2026-10-17 K2：标准技术指标（RSI/MACD/布林带/ATR/OBV/MFI/CCI/WR/Stochastic/
ADX/PSAR/ROC/SMA/EMA）统一迁移至 pandas-ta 成熟库；收益率/波动率/峰谷距离/
量比/偏度峰度等派生统计与价格形态识别保留 pandas 原语（非指标公式）。
"""

import numpy as np
import pandas as pd
import pandas_ta as ta
from crewai import Agent


class ResearcherAgent:
    """市场研究员 Agent - 400 指标版"""

    # 多时间框架
    TIMEFRAMES = [3, 5, 7, 10, 14, 20, 50, 200]

    def __init__(self, llm=None, verbose: bool = False):
        self.llm = llm
        self.verbose = verbose
        self.agent = self._create_agent()
        self.indicators = {}

    def _create_agent(self) -> Agent:
        return Agent(
            role="市场研究员",
            goal="深入分析市场数据，识别高概率交易机会",
            backstory="你是一位经验丰富的量化研究员，精通 400+ 技术指标分析。",
            llm=self.llm, verbose=self.verbose, allow_delegation=False
        )

    def analyze(self, symbol: str, data: pd.DataFrame) -> dict:
        signals = self._calculate_signals(data)
        trend = self._identify_trend(data)
        return {
            "symbol": symbol, "timestamp": pd.Timestamp.now(),
            "signals": signals, "trend": trend,
            "confidence": self._calculate_confidence(signals, trend),
            "recommendation": self._generate_recommendation(signals, trend)
        }

    def _nan_series(self, like) -> pd.Series:
        """与输入等索引的全 NaN 序列（pandas-ta 数据不足返回 None 时的占位）"""
        return pd.Series(np.nan, index=like.index)

    def _calc_rsi(self, close, period):
        """RSI（pandas-ta；K2 由手写 Cutler 式迁移）
        口径说明见 evolution/backtest_core.calc_rsi docstring。"""
        r = ta.rsi(close, length=int(period))
        return self._nan_series(close) if r is None else r

    def _calc_macd(self, close, fast=12, slow=26, sig=9):
        """MACD（pandas-ta；列序 [MACD, 柱, 信号] → 返回 (线, 信号, 柱)）"""
        m = ta.macd(close, fast=int(fast), slow=int(slow), signal=int(sig))
        if m is None:
            nan = self._nan_series(close)
            return nan, nan, nan
        return m.iloc[:, 0], m.iloc[:, 2], m.iloc[:, 1]

    def _calc_bb(self, close, period=20, std=2):
        """布林带（pandas-ta；返回 上轨/下轨/中轨/%B/带宽，顺序同旧实现）
        带宽 = 库输出 BBB（100*(u-l)/mid）÷ 100，保持旧口径不带 ×100。"""
        b = ta.bbands(close, length=int(period), std=float(std))
        if b is None:
            nan = self._nan_series(close)
            return nan, nan, nan, nan, nan
        return b.iloc[:, 2], b.iloc[:, 0], b.iloc[:, 1], b.iloc[:, 4], b.iloc[:, 3] / 100

    def _calc_atr(self, high, low, close, period=14):
        """ATR（pandas-ta Wilder RMA 口径）"""
        a = ta.atr(high, low, close, length=int(period))
        return self._nan_series(close) if a is None else a

    def _calculate_signals(self, data: pd.DataFrame) -> dict:
        """计算 200+ 技术指标（多时间框架）"""
        close = data['close']
        high = data['high'] if 'high' in data.columns else close
        low = data['low'] if 'low' in data.columns else close
        volume = data['volume'] if 'volume' in data.columns else pd.Series(1, index=close.index)
        n = len(close)
        latest = close.iloc[-1]
        result = {}

        # === 多时间框架指标 ===
        for tf in self.TIMEFRAMES:
            if n < tf + 1:
                continue
            p = str(tf)

            # RSI
            rsi = self._calc_rsi(close, tf)
            result[f'rsi_{p}'] = round(rsi.iloc[-1], 2)

            # SMA（K2：pandas-ta）
            sma = ta.sma(close, length=tf)
            if sma is None:
                sma = self._nan_series(close)
            result[f'sma_{p}'] = round(sma.iloc[-1], 2)
            result[f'price_vs_sma_{p}'] = round(latest / sma.iloc[-1] - 1, 4) if sma.iloc[-1] > 0 else 0

            # EMA（K2：pandas-ta）
            ema = ta.ema(close, length=tf)
            if ema is None:
                ema = self._nan_series(close)
            result[f'ema_{p}'] = round(ema.iloc[-1], 2)

            # 布林带
            if tf >= 5:
                bb_u, bb_l, bb_m, bb_pos, bb_w = self._calc_bb(close, tf)
                result[f'bb_pos_{p}'] = round(bb_pos.iloc[-1], 2)
                result[f'bb_width_{p}'] = round(bb_w.iloc[-1], 4)

            # ATR
            if tf >= 5:
                atr = self._calc_atr(high, low, close, tf)
                result[f'atr_{p}'] = round(atr.iloc[-1], 2)
                result[f'atr_pct_{p}'] = round(atr.iloc[-1] / latest * 100, 2)

            # 收益率
            ret = close.pct_change(tf)
            result[f'return_{p}'] = round(ret.iloc[-1], 4)

            # 波动率
            if tf >= 5:
                vol = close.pct_change().rolling(tf).std() * np.sqrt(365)
                result[f'vol_{p}'] = round(vol.iloc[-1], 4) if not vol.empty else 0

            # 最高/最低
            hh = high.rolling(tf).max()
            ll = low.rolling(tf).min()
            result[f'hh_dist_{p}'] = round((hh.iloc[-1] - latest) / latest, 4)
            result[f'll_dist_{p}'] = round((latest - ll.iloc[-1]) / latest, 4)

        # === 成交量指标（K2：滚动均值出自 pandas-ta） ===
        vol_sma = ta.sma(volume, length=20)
        vol_ma5 = ta.sma(volume, length=5)
        if vol_sma is None:
            vol_sma = self._nan_series(volume)
        if vol_ma5 is None:
            vol_ma5 = self._nan_series(volume)
        result['vol_ratio'] = round((volume / vol_sma).iloc[-1], 2)
        result['vol_trend'] = round(vol_ma5.iloc[-1] / vol_sma.iloc[-1] - 1, 4)

        # OBV（K2：pandas-ta；平盘日不再计 -volume，首值为 NaN）
        obv = ta.obv(close, volume)
        if obv is None:
            obv = self._nan_series(close)
        result['obv_change'] = round(obv.pct_change(20).iloc[-1], 4) if n >= 20 else 0

        # MFI（K2：pandas-ta）
        mfi = ta.mfi(high, low, close, volume, length=14)
        result['mfi'] = round(float(mfi.iloc[-1]), 2) if mfi is not None else 0

        # === 动量指标 ===
        # CCI（K2：pandas-ta）
        cci = ta.cci(high, low, close, length=20)
        result['cci'] = round(float(cci.iloc[-1]), 2) if cci is not None else 0

        # Williams %R（K2：pandas-ta）
        wr = ta.willr(high, low, close, length=14)
        result['wr'] = round(float(wr.iloc[-1]), 2) if wr is not None else 0

        # Stochastic（K2：pandas-ta；smooth_k=1 使 %K 为原始值、%D 为 SMA3，同旧口径）
        st = ta.stoch(high, low, close, k=14, d=3, smooth_k=1)
        if st is not None:
            result['stoch_k'] = round(float(st.iloc[-1, 0]), 2)
            result['stoch_d'] = round(float(st.iloc[-1, 1]), 2)
        else:
            result['stoch_k'] = result['stoch_d'] = 0

        # ROC（K2：pandas-ta）
        for p in [5, 10, 20]:
            roc = ta.roc(close, length=p)
            result[f'roc_{p}'] = round(float(roc.iloc[-1]), 2) if roc is not None else 0

        # === 趋势指标 ===
        # ADX（K2：pandas-ta Wilder 口径；列序 [ADX, ADXR, DMP, DMN]）
        adx_df = ta.adx(high, low, close, length=14)
        if adx_df is not None:
            result['adx'] = round(float(adx_df.iloc[-1, 0]), 2)
            result['plus_di'] = round(float(adx_df.iloc[-1, 2]), 2)
            result['minus_di'] = round(float(adx_df.iloc[-1, 3]), 2)
        else:
            result['adx'] = result['plus_di'] = result['minus_di'] = 0

        # 抛物线 SAR
        sar = self._calc_psar(high, low, close)
        result['psar_dist'] = round((latest - sar.iloc[-1]) / latest, 4) if not sar.empty else 0

        # === MACD 多周期 ===
        for fast, slow, sig in [(12, 26, 9), (5, 35, 5), (8, 17, 9)]:
            macd, macd_sig, macd_hist = self._calc_macd(close, fast, slow, sig)
            key = f'macd_{fast}_{slow}'
            result[f'{key}_line'] = round(macd.iloc[-1], 4)
            result[f'{key}_signal'] = round(macd_sig.iloc[-1], 4)
            result[f'{key}_hist'] = round(macd_hist.iloc[-1], 4)

        # === 价格形态识别 ===
        result.update(self._detect_patterns(close, high, low))

        # === 统计指标 ===
        returns = close.pct_change().dropna()
        if len(returns) > 20:
            result['skewness'] = round(returns.rolling(20).skew().iloc[-1], 4)
            result['kurtosis'] = round(returns.rolling(20).kurt().iloc[-1], 4)
            result['autocorr_1'] = round(returns.autocorr(1) if len(returns) > 1 else 0, 4)
            result['autocorr_5'] = round(returns.autocorr(5) if len(returns) > 5 else 0, 4)

        # === 衍生指标 ===
        # SMA 交叉信号
        for fast, slow in [(5, 20), (10, 50), (20, 200)]:
            if n >= slow:
                sma_f = ta.sma(close, length=fast)
                sma_s = ta.sma(close, length=slow)
                if sma_f is None or sma_s is None:
                    continue
                result[f'sma_cross_{fast}_{slow}'] = 1 if sma_f.iloc[-1] > sma_s.iloc[-1] else -1

        # RSI 背离
        if n >= 20:
            rsi14 = self._calc_rsi(close, 14)
            price_high_20 = close.rolling(20).max()
            rsi_high_20 = rsi14.rolling(20).max()
            result['rsi_divergence'] = 1 if close.iloc[-1] >= price_high_20.iloc[-1] * 0.98 and rsi14.iloc[-1] < rsi_high_20.iloc[-1] * 0.8 else 0

        # 波动率锥
        for p in [5, 10, 20]:
            if n >= p:
                vol_p = returns.rolling(p).std().iloc[-1] * np.sqrt(365)
                result[f'vol_cone_{p}'] = round(vol_p, 4) if not np.isnan(vol_p) else 0

        # 总指标数
        result['total_indicators'] = len(result)
        return result

    def _calc_psar(self, high, low, close):
        """抛物线 SAR（K2：pandas-ta；长/短仓两列 SAR 合并为单列）"""
        p = ta.psar(high, low, close)
        if p is None:
            return self._nan_series(close)
        return p.iloc[:, 0].combine_first(p.iloc[:, 1])

    def _detect_patterns(self, close, high, low):
        """检测价格形态"""
        patterns = {}
        n = len(close)
        if n < 20:
            return patterns

        # 双底
        recent = close.iloc[-20:]
        min_idx = recent.idxmin()
        min_val = recent.min()
        before_min = recent[:min_idx]
        if len(before_min) > 3:
            first_min = before_min.min()
            if abs(first_min - min_val) / min_val < 0.03:
                patterns['double_bottom'] = 1

        # 双顶
        max_idx = recent.idxmax()
        max_val = recent.max()
        before_max = recent[:max_idx]
        if len(before_max) > 3:
            first_max = before_max.max()
            if abs(first_max - max_val) / max_val < 0.03:
                patterns['double_top'] = 1

        # 连续涨跌
        up_days = sum(1 for i in range(1, min(10, n)) if close.iloc[-i] > close.iloc[-i-1])
        down_days = sum(1 for i in range(1, min(10, n)) if close.iloc[-i] < close.iloc[-i-1])
        patterns['up_streak'] = up_days
        patterns['down_streak'] = down_days

        # 突破信号
        hh20 = high.rolling(20).max()
        ll20 = low.rolling(20).min()
        patterns['breakout_up'] = 1 if close.iloc[-1] > hh20.iloc[-2] else 0
        patterns['breakout_down'] = 1 if close.iloc[-1] < ll20.iloc[-2] else 0

        return patterns

    def _identify_trend(self, data: pd.DataFrame) -> str:
        close = data['close']
        sma20 = ta.sma(close, length=20)
        sma50 = ta.sma(close, length=50)
        if sma20 is None or sma50 is None:
            return "震荡"
        if sma20.iloc[-1] > sma50.iloc[-1] and close.iloc[-1] > sma20.iloc[-1]:
            return "强势上涨"
        elif sma20.iloc[-1] > sma50.iloc[-1]:
            return "温和上涨"
        elif sma20.iloc[-1] < sma50.iloc[-1] and close.iloc[-1] < sma20.iloc[-1]:
            return "强势下跌"
        elif sma20.iloc[-1] < sma50.iloc[-1]:
            return "温和下跌"
        else:
            return "震荡"

    def _calculate_confidence(self, signals: dict, trend: str) -> float:
        score = 0.5
        rsi = signals.get('rsi_14', 50)
        if rsi < 25: score += 0.15
        elif rsi < 35: score += 0.08
        elif rsi > 75: score -= 0.15
        elif rsi > 65: score -= 0.08

        macd_hist = signals.get('macd_12_26_hist', 0)
        if macd_hist > 0: score += 0.12
        else: score -= 0.12

        bb_pos = signals.get('bb_pos_20', 0.5)
        if bb_pos < 0.1: score += 0.10
        elif bb_pos > 0.9: score -= 0.10

        vol_ratio = signals.get('vol_ratio', 1)
        if vol_ratio > 1.5: score += 0.04 if '上涨' in trend else -0.04

        mfi = signals.get('mfi', 50)
        if mfi < 20: score += 0.08
        elif mfi > 80: score -= 0.08

        cci = signals.get('cci', 0)
        if cci < -200: score += 0.07
        elif cci > 200: score -= 0.07

        wr = signals.get('wr', -50)
        if wr < -80: score += 0.07
        elif wr > -20: score -= 0.07

        adx = signals.get('adx', 0)
        if adx > 25: score += 0.03 if '上涨' in trend else -0.03

        mom5 = signals.get('return_5', 0)
        mom20 = signals.get('return_20', 0)
        if mom5 > 0 and mom20 > 0: score += 0.08
        elif mom5 < 0 and mom20 < 0: score -= 0.08

        support = signals.get('ll_dist_20', 0.1)
        resistance = signals.get('hh_dist_20', 0.1)
        if support < 0.02: score += 0.06
        if resistance < 0.02: score -= 0.06

        atr_pct = signals.get('atr_pct_14', 0)
        if atr_pct > 5: score -= 0.03

        roc = signals.get('roc_10', 0)
        if roc > 5: score += 0.05
        elif roc < -5: score -= 0.05

        if '强势上涨' in trend: score += 0.03
        elif '强势下跌' in trend: score -= 0.03

        # 形态信号
        if signals.get('double_bottom', 0): score += 0.05
        if signals.get('double_top', 0): score -= 0.05
        if signals.get('breakout_up', 0): score += 0.08
        if signals.get('breakout_down', 0): score -= 0.08

        return round(max(0, min(1, score)), 2)

    def _generate_recommendation(self, signals: dict, trend: str) -> str:
        buy_score = 0
        sell_score = 0

        rsi = signals.get('rsi_14', 50)
        if rsi < 30: buy_score += 2
        elif rsi < 40: buy_score += 1
        elif rsi > 70: sell_score += 2
        elif rsi > 60: sell_score += 1

        macd_hist = signals.get('macd_12_26_hist', 0)
        if macd_hist > 0: buy_score += 1
        else: sell_score += 1

        bb_pos = signals.get('bb_pos_20', 0.5)
        if bb_pos < 0.2: buy_score += 2
        elif bb_pos > 0.8: sell_score += 2

        cci = signals.get('cci', 0)
        if cci < -100: buy_score += 2
        elif cci > 100: sell_score += 2

        wr = signals.get('wr', -50)
        if wr < -80: buy_score += 1
        elif wr > -20: sell_score += 1

        mfi = signals.get('mfi', 50)
        if mfi < 20: buy_score += 1
        elif mfi > 80: sell_score += 1

        mom5 = signals.get('return_5', 0)
        mom20 = signals.get('return_20', 0)
        if mom5 > 0.02: buy_score += 1
        elif mom5 < -0.02: sell_score += 1
        if mom20 > 0.05: buy_score += 1
        elif mom20 < -0.05: sell_score += 1

        support = signals.get('ll_dist_20', 0.1)
        resistance = signals.get('hh_dist_20', 0.1)
        if support < 0.02: buy_score += 2
        if resistance < 0.02: sell_score += 2

        vol_ratio = signals.get('vol_ratio', 1)
        if vol_ratio > 1.2:
            buy_score += 1
            sell_score += 1

        adx = signals.get('adx', 0)
        if adx > 25:
            if '上涨' in trend: buy_score += 1
            elif '下跌' in trend: sell_score += 1

        if signals.get('double_bottom', 0): buy_score += 2
        if signals.get('double_top', 0): sell_score += 2
        if signals.get('breakout_up', 0): buy_score += 3
        if signals.get('breakout_down', 0): sell_score += 3

        if buy_score >= 5: return "强烈买入"
        elif buy_score >= 3: return "买入"
        elif sell_score >= 5: return "强烈卖出"
        elif sell_score >= 3: return "卖出"
        else: return "观望"
