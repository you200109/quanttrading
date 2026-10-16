"""
多时间框架融合分析器

将 8 个时间框架（3/5/7/10/14/20/50/200）深度集成到分析管道，
实现多周期信号共振检测、加权评分和趋势一致性验证。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


@dataclass
class TimeframeSignal:
    period: int
    trend: str
    strength: float
    rsi: float
    macd_signal: str
    volume_ratio: float
    support: float
    resistance: float


@dataclass
class ResonanceResult:
    symbol: str
    timestamp: datetime
    signals: dict[int, TimeframeSignal] = field(default_factory=dict)
    resonance_score: float = 0.0
    consensus_trend: str = "neutral"
    confidence: float = 0.0
    entry_zones: list[float] = field(default_factory=list)
    exit_zones: list[float] = field(default_factory=list)
    divergence_warnings: list[str] = field(default_factory=list)


class MultiTimeframeAnalyzer:
    TIMEFRAME_WEIGHTS = {
        3: 0.08, 5: 0.10, 7: 0.12, 10: 0.14,
        14: 0.16, 20: 0.16, 50: 0.14, 200: 0.10,
    }

    def __init__(self, data: pd.DataFrame, symbol: str = "BTC/USDT"):
        self.data = data
        self.symbol = symbol
        self.timeframes = [3, 5, 7, 10, 14, 20, 50, 200]

    def analyze(self) -> ResonanceResult:
        result = ResonanceResult(symbol=self.symbol, timestamp=datetime.now())
        for period in self.timeframes:
            if len(self.data) < period + 1:
                continue
            result.signals[period] = self._analyze_single_timeframe(period)
        result.resonance_score = self._calculate_resonance(result.signals)
        result.consensus_trend = self._determine_consensus(result.signals)
        result.confidence = self._calculate_confidence(result)
        result.entry_zones, result.exit_zones = self._identify_zones(result.signals)
        result.divergence_warnings = self._detect_divergence(result.signals)
        return result

    def _analyze_single_timeframe(self, period: int) -> TimeframeSignal:
        close = self.data['close'].values
        high = self.data['high'].values
        low = self.data['low'].values
        volume = self.data['volume'].values
        recent_close = close[-period:]
        recent_high = high[-period:]
        recent_low = low[-period:]
        recent_volume = volume[-period:]
        current_price = recent_close[-1]
        rsi = self._calc_rsi(recent_close)
        macd_sig = self._calc_macd_signal(recent_close)
        np.mean(recent_close[-min(period//2, len(recent_close)):])
        sma_long = np.mean(recent_close)
        if current_price > sma_long * 1.02:
            trend, strength = "bullish", min(1.0, (current_price - sma_long) / sma_long * 10)
        elif current_price < sma_long * 0.98:
            trend, strength = "bearish", min(1.0, (sma_long - current_price) / sma_long * 10)
        else:
            trend, strength = "neutral", 0.5
        vol_ratio = recent_volume[-1] / (np.mean(recent_volume) + 1e-8)
        return TimeframeSignal(period=period, trend=trend, strength=strength,
                               rsi=rsi, macd_signal=macd_sig, volume_ratio=vol_ratio,
                               support=np.min(recent_low), resistance=np.max(recent_high))

    def _calc_rsi(self, prices: np.ndarray, window: int = 14) -> float:
        """RSI 末值（pandas-ta；数据不足/退化（全平）时回退 50.0）

        K2（2026-10-17）：原实现为手写 Cutler 式窗口均值，现委托 pandas-ta。
        """
        if len(prices) < window + 1:
            return 50.0
        r = ta.rsi(pd.Series(np.asarray(prices, dtype=float)), length=window)
        if r is None:
            return 50.0
        value = r.iloc[-1]
        return 50.0 if pd.isna(value) else float(value)

    def _calc_macd_signal(self, prices: np.ndarray) -> str:
        """MACD 金叉/死叉信号（pandas-ta）

        K2 修复：原实现用 np.full(9, macd_val) 的 EMA 当信号线——信号线与
        MACD 线恒等，恒返回 "hold"（真 bug）。现按标准口径：信号线 = MACD
        线的 9 周期 EMA。ta.macd 要求 len >= slow + signal - 1（12/26/9 → 34）。
        """
        if len(prices) < 34:
            return "hold"
        m = ta.macd(pd.Series(np.asarray(prices, dtype=float)), fast=12, slow=26, signal=9)
        if m is None:
            return "hold"
        macd_val, sig_val = m.iloc[-1, 0], m.iloc[-1, 2]
        if pd.isna(macd_val) or pd.isna(sig_val):
            return "hold"
        macd_val, sig_val = float(macd_val), float(sig_val)
        return "buy" if macd_val > sig_val else ("sell" if macd_val < sig_val else "hold")

    def _calculate_resonance(self, signals: dict[int, TimeframeSignal]) -> float:
        if not signals:
            return 0.0
        bullish_count = sum(1 for s in signals.values() if s.trend == "bullish")
        bearish_count = sum(1 for s in signals.values() if s.trend == "bearish")
        total = len(signals)
        base_score = (max(bullish_count, bearish_count) / total) * 60
        short_trends = [signals[p].trend for p in [3,5,7] if p in signals]
        long_trends = [signals[p].trend for p in [50,200] if p in signals]
        alignment_bonus = 0
        if short_trends and long_trends:
            sc = max(set(short_trends), key=short_trends.count)
            lc = max(set(long_trends), key=long_trends.count)
            if sc == lc and sc != "neutral":
                alignment_bonus = 25
        vol_bonus = min(sum(3 for s in signals.values() if s.volume_ratio > 1.5), 15)
        return min(100, base_score + alignment_bonus + vol_bonus)

    def _determine_consensus(self, signals: dict[int, TimeframeSignal]) -> str:
        trends = [s.trend for s in signals.values()]
        bullish = trends.count("bullish")
        bearish = trends.count("bearish")
        total = len(trends)
        if bullish > total * 0.5:
            return "bullish"
        if bearish > total * 0.5:
            return "bearish"
        if bullish > bearish:
            return "slightly_bullish"
        if bearish > bullish:
            return "slightly_bearish"
        return "neutral"

    def _calculate_confidence(self, result: ResonanceResult) -> float:
        if not result.signals:
            return 0.0
        trends = [s.trend for s in result.signals.values()]
        dominant = max(set(trends), key=trends.count)
        consistency = trends.count(dominant) / len(trends)
        avg_strength = np.mean([s.strength for s in result.signals.values()])
        rsi_values = [s.rsi for s in result.signals.values()]
        rsi_extreme = abs(np.mean(rsi_values) - 50) / 50
        confidence = consistency * 0.4 + avg_strength * 0.3 + rsi_extreme * 0.2 + (result.resonance_score / 100) * 0.1
        return min(1.0, max(0.0, confidence))

    def _identify_zones(self, signals: dict[int, TimeframeSignal]) -> tuple[list[float], list[float]]:
        supports = [s.support for s in signals.values()]
        resistances = [s.resistance for s in signals.values()]
        return sorted({round(x, 2) for x in supports})[-3:], sorted({round(x, 2) for x in resistances})[:3]

    def _detect_divergence(self, signals: dict[int, TimeframeSignal]) -> list[str]:
        warnings = []
        for sp in [3, 5, 7]:
            for lp in [50, 200]:
                if sp in signals and lp in signals:
                    ss, ls = signals[sp], signals[lp]
                    if ss.trend == "bullish" and ls.trend == "bearish":
                        warnings.append(f"背离: {sp}日看涨 vs {lp}日看跌，短期反弹可能不可持续")
                    if ss.trend == "bearish" and ls.trend == "bullish":
                        warnings.append(f"背离: {sp}日看跌 vs {lp}日看涨，可能是回调买入机会")
                    if ss.rsi > 70 and ls.rsi < 50:
                        warnings.append(f"RSI背离: {sp}日超买({ss.rsi:.0f}) vs {lp}日中性({ls.rsi:.0f})")
                    if ss.rsi < 30 and ls.rsi > 50:
                        warnings.append(f"RSI背离: {sp}日超卖({ss.rsi:.0f}) vs {lp}日中性({ls.rsi:.0f})")
        return warnings

    def get_trade_recommendation(self, result: ResonanceResult) -> dict:
        rec = {"symbol": result.symbol, "timestamp": result.timestamp.isoformat(),
               "action": "hold", "confidence": result.confidence,
               "resonance_score": result.resonance_score,
               "consensus_trend": result.consensus_trend,
               "entry_zones": result.entry_zones, "exit_zones": result.exit_zones,
               "warnings": result.divergence_warnings, "reasoning": []}
        if result.resonance_score >= 70 and result.consensus_trend in ["bullish", "slightly_bullish"]:
            rec["action"] = "buy"
            rec["reasoning"].append(f"多周期共振看涨 (评分: {result.resonance_score:.0f})")
        elif result.resonance_score >= 70 and result.consensus_trend in ["bearish", "slightly_bearish"]:
            rec["action"] = "sell"
            rec["reasoning"].append(f"多周期共振看跌 (评分: {result.resonance_score:.0f})")
        elif result.resonance_score >= 50 and result.confidence >= 0.6:
            if "bullish" in result.consensus_trend:
                rec["action"] = "buy"
                rec["reasoning"].append("中等共振 + 高置信度看涨")
            elif "bearish" in result.consensus_trend:
                rec["action"] = "sell"
                rec["reasoning"].append("中等共振 + 高置信度看跌")
        if result.divergence_warnings:
            rec["action"] = "hold"
            rec["reasoning"].append("存在时间框架背离，建议观望")
        if not rec["reasoning"]:
            rec["reasoning"].append("无明确多周期共振信号，建议观望")
        return rec

    def get_signal_matrix(self, result: ResonanceResult) -> pd.DataFrame:
        rows = []
        for period in sorted(result.signals.keys()):
            s = result.signals[period]
            rows.append({"周期": f"{period}日", "趋势": s.trend, "强度": f"{s.strength:.2f}",
                         "RSI": f"{s.rsi:.0f}", "MACD": s.macd_signal,
                         "量比": f"{s.volume_ratio:.2f}",
                         "支撑": f"${s.support:,.2f}", "阻力": f"${s.resistance:,.2f}"})
        return pd.DataFrame(rows)
