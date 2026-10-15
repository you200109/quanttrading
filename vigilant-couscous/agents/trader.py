"""
交易员 Agent - 负责策略执行与订单管理

基于 crewai Agent 框架，集成 backtrader/ccxt 进行
策略执行、订单管理和持仓跟踪。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

try:
    from crewai import Agent
except ImportError:
    Agent = None

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """订单数据结构"""
    symbol: str
    side: str  # buy / sell
    order_type: str  # market / limit
    quantity: float
    price: float | None = None
    status: str = "pending"
    order_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    filled_at: datetime | None = None
    filled_price: float | None = None


@dataclass
class Position:
    """持仓数据结构"""
    symbol: str
    quantity: float
    avg_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class TraderAgent:
    """交易执行员 Agent

    职责：
    1. 接收研究员的交易信号并执行
    2. 订单管理与成交追踪
    3. 持仓监控与盈亏计算
    4. 滑点控制和执行质量评估
    """

    def __init__(
        self,
        llm=None,
        initial_capital: float = 100000,
        max_position_pct: float = 0.2,
        verbose: bool = False
    ):
        self.llm = llm
        self.verbose = verbose
        self.capital = initial_capital
        self.available_capital = initial_capital
        self.max_position_pct = max_position_pct
        self.positions: dict[str, Position] = {}
        self.orders: list[Order] = []
        self.order_history: list[Order] = []
        self.agent = self._create_agent()

    def _create_agent(self):
        """创建 crewai Agent 实例"""
        if Agent is None:
            return None
        return Agent(
            role="交易执行员",
            goal="精准执行交易策略，优化订单执行质量，最大化风险调整后收益",
            backstory=(
                "你是一位经验丰富的交易员，精通订单执行、"
                "流动性管理和交易成本优化。你对市场微观结构"
                "有深刻理解，能够在各种市场条件下高效执行交易。"
            ),
            llm=self.llm,
            verbose=self.verbose,
            allow_delegation=False
        )

    def execute_signal(self, signal: dict, current_price: float = 0) -> Order | None:
        """执行交易信号

        Args:
            signal: 研究员生成的交易信号
            current_price: 当前价格（用于计算仓位）

        Returns:
            生成的订单，如果被风控拒绝则返回 None
        """
        recommendation = signal.get("recommendation", "观望")
        symbol = signal.get("symbol", "")
        confidence = signal.get("confidence", 0)

        if recommendation == "观望":
            logger.info(f"[{symbol}] 信号为观望，不执行交易")
            return None

        # 根据建议确定交易方向
        if "买入" in recommendation:
            side = "buy"
            quantity = self._calculate_position_size(symbol, confidence, current_price)
        elif "卖出" in recommendation:
            side = "sell"
            quantity = self._get_position_quantity(symbol)
        else:
            return None

        if quantity <= 0:
            logger.info(f"[{symbol}] 计算仓位为0，跳过")
            return None

        order = Order(
            symbol=symbol,
            side=side,
            order_type="market",
            quantity=quantity
        )

        self.orders.append(order)
        logger.info(f"[{symbol}] 生成订单: {side} {quantity:.4f} 个")
        return order

    def _calculate_position_size(self, symbol: str, confidence: float, current_price: float = 100) -> float:
        """计算仓位大小

        基于凯利公式变体，结合置信度动态调整仓位
        增加组合总仓位上限约束，防止多币种叠加超仓
        """
        # 计算当前已占用仓位价值
        current_position_value = sum(
            p.quantity * (p.current_price or p.avg_price)
            for s, p in self.positions.items() if s != symbol
        )
        total_equity = self.available_capital + current_position_value
        current_exposure_pct = current_position_value / total_equity if total_equity > 0 else 0

        # 组合总仓位上限（60%），单标的上限（20%）
        max_total_pct = 0.6
        remaining_pct = max(0, max_total_pct - current_exposure_pct)
        effective_max_pct = min(self.max_position_pct, remaining_pct)

        if effective_max_pct <= 0:
            return 0  # 总仓位已满

        max_position_value = self.available_capital * effective_max_pct
        # 置信度越高，仓位越大（0.5~1.0 倍最大仓位）
        position_multiplier = 0.5 + confidence * 0.5
        position_value = max_position_value * position_multiplier

        # 基于实际价格计算数量（加密货币不需要整手）
        quantity = position_value / current_price if current_price > 0 else position_value / 100

        return max(0, quantity)

    def _get_position_quantity(self, symbol: str) -> float:
        """获取当前持仓数量"""
        if symbol in self.positions:
            return self.positions[symbol].quantity
        return 0

    def update_position(self, order: Order, fill_price: float):
        """更新持仓信息"""
        symbol = order.symbol

        if order.side == "buy":
            if symbol in self.positions:
                pos = self.positions[symbol]
                total_cost = pos.avg_price * pos.quantity + fill_price * order.quantity
                pos.quantity += order.quantity
                pos.avg_price = total_cost / pos.quantity
            else:
                self.positions[symbol] = Position(
                    symbol=symbol,
                    quantity=order.quantity,
                    avg_price=fill_price,
                    current_price=fill_price
                )
            # 更新当前价格
            self.positions[symbol].current_price = fill_price
            self.available_capital -= fill_price * order.quantity
        else:
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos.realized_pnl += (fill_price - pos.avg_price) * min(order.quantity, pos.quantity)
                pos.quantity -= order.quantity
                self.available_capital += fill_price * order.quantity
                if pos.quantity <= 0:
                    del self.positions[symbol]

        order.status = "filled"
        order.filled_at = datetime.now()
        order.filled_price = fill_price
        self.order_history.append(order)
        self.orders.remove(order)

    def mark_to_market(self, prices: dict[str, float]):
        """按市价更新持仓估值

        Args:
            prices: {symbol: current_price} 字典
        """
        for symbol, pos in self.positions.items():
            if symbol in prices:
                pos.current_price = prices[symbol]
                pos.unrealized_pnl = (pos.current_price - pos.avg_price) * pos.quantity

    def get_portfolio_summary(self) -> dict:
        """获取投资组合摘要"""
        total_position_value = sum(
            p.quantity * p.current_price for p in self.positions.values()
        )
        total_pnl = sum(
            p.unrealized_pnl + p.realized_pnl for p in self.positions.values()
        )

        return {
            "capital": self.capital,
            "available_capital": self.available_capital,
            "position_value": total_position_value,
            "total_value": self.available_capital + total_position_value,
            "total_pnl": total_pnl,
            "total_return": (self.available_capital + total_position_value - self.capital) / self.capital,
            "position_count": len(self.positions),
            "positions": {
                s: {
                    "quantity": p.quantity,
                    "avg_price": p.avg_price,
                    "current_price": p.current_price,
                    "pnl": p.unrealized_pnl + p.realized_pnl
                }
                for s, p in self.positions.items()
            }
        }
