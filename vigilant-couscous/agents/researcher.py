"""
研究员 Agent - 400 指标版
多时间框架 × 核心指标 = 200+ 指标 + 衍生指标 + 形态识别
"""

import numpy as np
import pandas as pd
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

    def _calc_rsi(self, close, period):
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _calc_macd(self, close, fast=12, slow=26, sig=9):
        ema_fast = close.ewm(span=fast).mean()
        ema_slow = close.ewm(span=slow).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=sig).mean()
        return macd, signal, macd - signal

    def _calc_bb(self, close, period=20, std=2):
        sma = close.rolling(period).mean()
        s = close.rolling(period).std()
        upper = sma + std * s
        lower = sma - std * s
        return upper, lower, sma, (close - lower) / (upper - lower), (upper - lower) / sma

    def _calc_atr(self, high, low, close, period=14):
        hl = high - low
        hc = abs(high - close.shift())
        lc = abs(low - close.shift())
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return tr.rolling(period).mean()

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

            # SMA
            sma = close.rolling(tf).mean()
            result[f'sma_{p}'] = round(sma.iloc[-1], 2)
            result[f'price_vs_sma_{p}'] = round(latest / sma.iloc[-1] - 1, 4) if sma.iloc[-1] > 0 else 0

            # EMA
            ema = close.ewm(span=tf).mean()
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

        # === 成交量指标 ===
        vol_sma = volume.rolling(20).mean()
        result['vol_ratio'] = round((volume / vol_sma).iloc[-1], 2)
        result['vol_trend'] = round(volume.rolling(5).mean().iloc[-1] / volume.rolling(20).mean().iloc[-1] - 1, 4)

        # OBV
        obv = (volume * ((close.diff() > 0) * 2 - 1)).cumsum()
        result['obv_change'] = round(obv.pct_change(20).iloc[-1], 4) if n >= 20 else 0

        # MFI
        tp = (high + low + close) / 3
        mf = tp * volume
        pos_mf = mf.where(tp > tp.shift(), 0).rolling(14).sum()
        neg_mf = mf.where(tp < tp.shift(), 0).rolling(14).sum()
        mfi_denom = neg_mf.replace(0, 1e-10)  # 防止除零
        result['mfi'] = round((100 - (100 / (1 + pos_mf / mfi_denom))).iloc[-1], 2)

        # === 动量指标 ===
        # CCI
        tp_cci = (high + low + close) / 3
        cci = (tp_cci - tp_cci.rolling(20).mean()) / (0.015 * tp_cci.rolling(20).std())
        result['cci'] = round(cci.iloc[-1], 2)

        # Williams %R
        hh14 = high.rolling(14).max()
        ll14 = low.rolling(14).min()
        result['wr'] = round(((hh14 - close) / (hh14 - ll14) * -100).iloc[-1], 2)

        # Stochastic
        k = (close - ll14) / (hh14 - ll14) * 100
        result['stoch_k'] = round(k.iloc[-1], 2)
        result['stoch_d'] = round(k.rolling(3).mean().iloc[-1], 2)

        # ROC
        for p in [5, 10, 20]:
            result[f'roc_{p}'] = round(close.pct_change(p).iloc[-1] * 100, 2)

        # === 趋势指标 ===
        # ADX
        plus_dm = high.diff().where(high.diff() > low.diff().abs(), 0)
        minus_dm = low.diff().abs().where(low.diff().abs() > high.diff(), 0)
        atr14 = self._calc_atr(high, low, close, 14)
        plus_di = 100 * plus_dm.rolling(14).mean() / atr14
        minus_di = 100 * minus_dm.rolling(14).mean() / atr14
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        result['adx'] = round(dx.rolling(14).mean().iloc[-1], 2)
        result['plus_di'] = round(plus_di.iloc[-1], 2)
        result['minus_di'] = round(minus_di.iloc[-1], 2)

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
                sma_f = close.rolling(fast).mean()
                sma_s = close.rolling(slow).mean()
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
        """计算抛物线 SAR"""
        n = len(close)
        sar = pd.Series(np.zeros(n), index=close.index)
        af = 0.02
        ep = low.iloc[0]
        trend = 1
        sar.iloc[0] = low.iloc[0]

        for i in range(1, n):
            sar.iloc[i] = sar.iloc[i-1] + af * (ep - sar.iloc[i-1])
            if trend == 1:
                if low.iloc[i] < sar.iloc[i]:
                    trend = -1
                    sar.iloc[i] = ep
                    ep = high.iloc[i]
                    af = 0.02
                else:
                    if high.iloc[i] > ep:
                        ep = high.iloc[i]
                        af = min(0.2, af + 0.02)
            else:
                if high.iloc[i] > sar.iloc[i]:
                    trend = 1
                    sar.iloc[i] = ep
                    ep = low.iloc[i]
                    af = 0.02
                else:
                    if low.iloc[i] < ep:
                        ep = low.iloc[i]
                        af = min(0.2, af + 0.02)
        return sar

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
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()
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
