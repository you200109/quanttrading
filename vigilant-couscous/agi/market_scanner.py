"""
AGI 全市场扫描 + 高频自适应系统

实现执行层的极致性能：
- 全市场扫描：同时监控 100+ 币种
- 机会排序：实时排序最佳交易机会
- 高频自适应：毫秒级决策调整
- 流动性感知：动态调整订单大小
- 冲击成本预估：大单拆分算法
"""

import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MEMORY = ROOT / "memory" / "agi"
MEMORY.mkdir(parents=True, exist_ok=True)


@dataclass
class MarketOpportunity:
    symbol: str
    action: str
    score: float
    expected_return: float
    risk: float
    liquidity: float
    confidence: float
    urgency: str
    reasoning: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class OrderSuggestion:
    symbol: str
    side: str
    quantity: float
    price: float
    order_type: str
    urgency: str
    split_into: int
    expected_slippage: float
    timestamp: datetime = field(default_factory=datetime.now)


class MarketScanner:
    """全市场扫描 + 高频自适应

    核心能力：
    1. 全市场扫描 - 同时监控大量币种
    2. 机会排序 - 多维度评分排序
    3. 高频自适应 - 实时调整决策
    4. 流动性感知 - 动态订单大小
    5. 冲击成本控制 - 大单拆分
    """

    TOP_CRYPTOS = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "MATIC/USDT",
        "LINK/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT",
        "FIL/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "NEAR/USDT",
    ]

    SCORE_WEIGHTS = {
        "expected_return": 0.30,
        "risk_adjusted": 0.25,
        "liquidity": 0.15,
        "confidence": 0.15,
        "trend_alignment": 0.10,
        "volatility_penalty": 0.05,
    }

    def __init__(self):
        self.opportunities: list[MarketOpportunity] = []
        self.price_cache: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.volume_cache: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.scan_history: list[dict] = []
        self.last_scan: datetime | None = None

    def scan_all_markets(self, symbols: list[str] = None,
                        market_data: dict[str, dict] = None) -> list[MarketOpportunity]:
        """全市场扫描"""
        symbols = symbols or self.TOP_CRYPTOS
        opportunities = []

        for symbol in symbols:
            try:
                if market_data and symbol in market_data:
                    data = market_data[symbol]
                else:
                    data = self._get_cached_data(symbol)

                if not data or not data.get('close'):
                    continue

                opp = self._analyze_opportunity(symbol, data)
                if opp and opp.score > 0.3:
                    opportunities.append(opp)

            except Exception as e:
                logger.debug(f"{symbol} 扫描跳过: {e}")

        opportunities.sort(key=lambda o: o.score, reverse=True)
        self.opportunities = opportunities
        self.last_scan = datetime.now()

        self.scan_history.append({
            "timestamp": datetime.now().isoformat(),
            "scanned": len(symbols),
            "opportunities": len(opportunities),
            "top_3": [{"symbol": o.symbol, "score": o.score, "action": o.action}
                      for o in opportunities[:3]],
        })

        logger.info(f"全市场扫描: {len(symbols)} 币种, {len(opportunities)} 个机会")
        return opportunities

    def get_top_opportunities(self, n: int = 5,
                             min_score: float = 0.5) -> list[MarketOpportunity]:
        """获取最佳交易机会"""
        return [o for o in self.opportunities[:n] if o.score >= min_score]

    def generate_orders(self, opportunities: list[MarketOpportunity],
                       capital: float = 100000) -> list[OrderSuggestion]:
        """生成订单建议"""
        orders = []
        remaining_capital = capital

        for opp in opportunities[:5]:
            allocation = remaining_capital * min(0.2, opp.score * 0.3)

            quantity = allocation / max(opp.expected_return * capital + capital, capital * 0.01) * 0.1
            quantity = max(0.001, min(quantity, allocation / 100))

            split_into = 1
            if allocation > capital * 0.05:
                split_into = min(5, max(1, int(allocation / (capital * 0.02))))

            expected_slippage = 0.001 + (allocation / capital) * 0.01

            order = OrderSuggestion(
                symbol=opp.symbol, side=opp.action,
                quantity=round(quantity, 6), price=0,
                order_type="limit" if opp.urgency == "low" else "market",
                urgency=opp.urgency, split_into=split_into,
                expected_slippage=round(expected_slippage, 4),
            )
            orders.append(order)
            remaining_capital -= allocation

        return orders

    def adaptive_adjust(self, opportunity: MarketOpportunity,
                       market_update: dict) -> MarketOpportunity:
        """高频自适应调整"""
        new_price = market_update.get('price', 0)
        new_volume = market_update.get('volume', 0)

        if new_price > 0:
            price_change = abs(new_price - opportunity.expected_return * 100000) / max(new_price, 1)
            if price_change > 0.02:
                opportunity.score *= 0.8
                opportunity.urgency = "high"
                opportunity.reasoning += f" | 价格突变 {price_change:.1%}"

        if new_volume > 0:
            avg_vol = np.mean(list(self.volume_cache.get(opportunity.symbol, deque([1]))))
            if new_volume > avg_vol * 3:
                opportunity.score *= 1.1
                opportunity.reasoning += " | 放量确认"

        return opportunity

    def estimate_market_impact(self, symbol: str, quantity: float,
                              side: str) -> dict:
        """预估市场冲击成本"""
        volumes = list(self.volume_cache.get(symbol, deque([1000])))
        avg_volume = np.mean(volumes) if volumes else 1000

        participation_rate = quantity / max(avg_volume, 1)

        if participation_rate < 0.01:
            impact = 0.0001
            recommendation = "可直接市价成交"
        elif participation_rate < 0.05:
            impact = 0.0005
            recommendation = "建议限价单"
        elif participation_rate < 0.1:
            impact = 0.002
            recommendation = "建议分 2-3 笔成交"
        else:
            impact = 0.01
            recommendation = "必须拆分大单，使用 TWAP 算法"

        return {
            "participation_rate": round(participation_rate, 4),
            "estimated_impact": round(impact, 4),
            "recommendation": recommendation,
            "suggested_splits": max(1, int(participation_rate / 0.02)),
        }

    def _analyze_opportunity(self, symbol: str, data: dict) -> MarketOpportunity | None:
        """分析单个币种的交易机会"""
        close = data.get('close', [])
        volume = data.get('volume', [])

        if len(close) < 20:
            return None

        self.price_cache[symbol].append(close[-1])
        if volume:
            self.volume_cache[symbol].append(volume[-1])

        returns = np.diff(close[-20:]) / close[-21:-1]
        expected_return = float(np.mean(returns) * 252)
        risk = float(np.std(returns) * np.sqrt(252))

        sma_short = np.mean(close[-5:])
        sma_long = np.mean(close[-20:])
        trend_alignment = (sma_short / sma_long - 1) * 10

        liquidity = float(np.mean(volume[-5:])) if volume else 1000
        liquidity_score = min(1.0, liquidity / 10000)

        if expected_return > 0.02 and trend_alignment > 0:
            action = "buy"
            confidence = min(0.9, 0.5 + expected_return * 5 + trend_alignment * 0.1)
        elif expected_return < -0.02 and trend_alignment < 0:
            action = "sell"
            confidence = min(0.9, 0.5 + abs(expected_return) * 5 + abs(trend_alignment) * 0.1)
        else:
            action = "hold"
            confidence = 0.3

        risk_adjusted = expected_return / max(risk, 0.01)
        volatility_penalty = max(0, 1 - risk * 2)

        score = (
            expected_return * 5 * self.SCORE_WEIGHTS["expected_return"] +
            risk_adjusted * self.SCORE_WEIGHTS["risk_adjusted"] +
            liquidity_score * self.SCORE_WEIGHTS["liquidity"] +
            confidence * self.SCORE_WEIGHTS["confidence"] +
            max(0, trend_alignment) * self.SCORE_WEIGHTS["trend_alignment"] +
            volatility_penalty * self.SCORE_WEIGHTS["volatility_penalty"]
        )

        urgency = "high" if score > 0.7 else ("medium" if score > 0.5 else "low")

        return MarketOpportunity(
            symbol=symbol, action=action, score=round(score, 4),
            expected_return=round(expected_return, 4), risk=round(risk, 4),
            liquidity=round(liquidity, 2), confidence=round(confidence, 2),
            urgency=urgency,
            reasoning=f"预期收益:{expected_return:.2%} 风险:{risk:.2%} 趋势:{trend_alignment:.2f}",
        )

    def _get_cached_data(self, symbol: str) -> dict | None:
        """获取缓存数据"""
        prices = list(self.price_cache.get(symbol, []))
        volumes = list(self.volume_cache.get(symbol, []))
        if not prices:
            return None
        return {"close": prices, "volume": volumes}

    def get_market_heatmap(self) -> dict:
        """获取市场热力图数据"""
        heatmap = {}
        for opp in self.opportunities[:20]:
            heatmap[opp.symbol] = {
                "score": opp.score,
                "action": opp.action,
                "expected_return": opp.expected_return,
                "risk": opp.risk,
            }
        return heatmap

    def _save(self):
        data = {
            "last_scan": self.last_scan.isoformat() if self.last_scan else None,
            "opportunities_count": len(self.opportunities),
            "top_opportunities": [
                {"symbol": o.symbol, "score": o.score, "action": o.action}
                for o in self.opportunities[:5]
            ],
            "last_updated": datetime.now().isoformat(),
        }
        (MEMORY / "market_scanner.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get_status(self) -> dict:
        return {
            "monitored_symbols": len(self.price_cache),
            "opportunities": len(self.opportunities),
            "last_scan": self.last_scan.isoformat() if self.last_scan else None,
            "top_5": [
                {"symbol": o.symbol, "score": o.score, "action": o.action}
                for o in self.opportunities[:5]
            ],
            "heatmap": self.get_market_heatmap(),
        }
