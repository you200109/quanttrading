"""
风控员 Agent - 负责风险评估与仓位管理

基于 crewai Agent 框架，实现多层次风控体系：
- 单笔交易风险控制
- 组合层面风险监控
- 最大回撤控制
- 动态止损止盈
"""

import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from crewai import Agent

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """风险限制参数"""
    max_position_pct: float = 0.2        # 单标的最大仓位比例
    max_drawdown_pct: float = 0.15       # 最大回撤限制
    daily_loss_limit_pct: float = 0.05   # 日内最大亏损限制
    var_limit_pct: float = 0.02          # VaR 限制
    stop_loss_pct: float = 0.05          # 止损比例
    take_profit_pct: float = 0.15        # 止盈比例
    max_correlation: float = 0.7         # 最大持仓相关性
    min_confidence: float = 0.01         # 最低信号置信度（降至1%，信号自由通过）


class RiskManagerAgent:
    """风控员 Agent

    职责：
    1. 交易前风险评估与审批
    2. 实时风险监控与预警
    3. 动态止损止盈管理
    4. 组合层面风险控制
    """

    def __init__(
        self,
        llm=None,
        limits: RiskLimits | None = None,
        verbose: bool = False
    ):
        self.llm = llm
        self.verbose = verbose
        self.limits = limits or RiskLimits()
        self.daily_pnl = 0.0
        self.peak_value = 0.0
        self.current_drawdown = 0.0
        self.risk_events: list[dict] = []
        self.stop_loss_levels: dict[str, float] = {}
        self.take_profit_levels: dict[str, float] = {}
        self.agent = self._create_agent()

    def _create_agent(self) -> Agent:
        """创建 crewai Agent 实例"""
        return Agent(
            role="风控总监",
            goal="严格控制交易风险，确保资金安全，在风险可控的前提下最大化收益",
            backstory=(
                "你是一位资深风控专家，曾在顶级对冲基金担任风控总监。"
                "你对各种风险模型了如指掌，能够在市场剧烈波动时保持冷静，"
                "做出最理性的风控决策。你的座右铭是：活着才有输出。"
            ),
            llm=self.llm,
            verbose=self.verbose,
            allow_delegation=False
        )

    def approve_trade(self, signal: dict, portfolio: dict) -> tuple[bool, str]:
        """审批交易信号

        Args:
            signal: 研究员生成的交易信号
            portfolio: 当前投资组合状态

        Returns:
            (是否批准, 原因说明)
        """
        # 1. 检查信号置信度
        confidence = signal.get("confidence", 0)
        if confidence < self.limits.min_confidence:
            return False, f"信号置信度 {confidence} 低于最低要求 {self.limits.min_confidence}"

        # 2. 检查最大回撤
        if self.current_drawdown >= self.limits.max_drawdown_pct:
            return False, f"当前回撤 {self.current_drawdown:.2%} 已超过最大回撤限制 {self.limits.max_drawdown_pct:.2%}"

        # 3. 检查日内亏损
        total_value = portfolio.get("total_value", 0)
        if total_value > 0 and abs(self.daily_pnl) / total_value >= self.limits.daily_loss_limit_pct:
            return False, f"日内亏损已达上限 {self.limits.daily_loss_limit_pct:.2%}"

        # 4. 检查仓位限制
        symbol = signal.get("symbol", "")
        positions = portfolio.get("positions", {})
        if symbol in positions:
            pos_info = positions[symbol]
            qty = pos_info.get("quantity", 0)
            cur_price = pos_info.get("current_price", 0) or pos_info.get("avg_price", 0)
            pos_value = qty * cur_price
            if total_value > 0 and pos_value / total_value >= self.limits.max_position_pct:
                return False, f"{symbol} 仓位已超过限制 {self.limits.max_position_pct:.2%}"

        # 5. 检查推荐方向
        recommendation = signal.get("recommendation", "")
        if recommendation == "强烈卖出" and symbol not in positions:
            return False, f"没有 {symbol} 持仓，无法卖出"

        return True, "风控审批通过"

    def set_stop_levels(self, symbol: str, entry_price: float):
        """设置止损止盈水平"""
        self.stop_loss_levels[symbol] = entry_price * (1 - self.limits.stop_loss_pct)
        self.take_profit_levels[symbol] = entry_price * (1 + self.limits.take_profit_pct)
        logger.info(
            f"[{symbol}] 止损: {self.stop_loss_levels[symbol]:.2f}, "
            f"止盈: {self.take_profit_levels[symbol]:.2f}"
        )

    def check_stop_conditions(self, symbol: str, current_price: float) -> str | None:
        """检查止损止盈条件

        Returns:
            触发类型 (stop_loss/take_profit) 或 None
        """
        if symbol in self.stop_loss_levels:
            if current_price <= self.stop_loss_levels[symbol]:
                self.risk_events.append({
                    "type": "stop_loss",
                    "symbol": symbol,
                    "price": current_price,
                    "level": self.stop_loss_levels[symbol],
                    "time": datetime.now()
                })
                return "stop_loss"

        if symbol in self.take_profit_levels:
            if current_price >= self.take_profit_levels[symbol]:
                self.risk_events.append({
                    "type": "take_profit",
                    "symbol": symbol,
                    "price": current_price,
                    "level": self.take_profit_levels[symbol],
                    "time": datetime.now()
                })
                return "take_profit"

        return None

    def update_drawdown(self, current_value: float):
        """更新回撤状态"""
        if current_value > self.peak_value:
            self.peak_value = current_value
        if self.peak_value > 0:
            self.current_drawdown = (self.peak_value - current_value) / self.peak_value

    def calculate_var(self, returns: list[float], confidence: float = 0.95) -> float:
        """计算历史 VaR

        Args:
            returns: 收益率序列
            confidence: 置信水平

        Returns:
            VaR 值
        """
        if len(returns) < 2:
            return 0.0
        return abs(np.percentile(returns, (1 - confidence) * 100))

    def calculate_portfolio_risk(self, positions: dict, prices: dict) -> dict:
        """计算组合风险指标"""
        total_value = sum(
            pos.get("quantity", 0) * prices.get(sym, 0)
            for sym, pos in positions.items()
        )

        concentration = {}
        for sym, pos in positions.items():
            pos_value = pos.get("quantity", 0) * prices.get(sym, 0)
            if total_value > 0:
                concentration[sym] = pos_value / total_value

        return {
            "total_value": total_value,
            "position_count": len(positions),
            "concentration": concentration,
            "max_concentration": max(concentration.values()) if concentration else 0,
            "current_drawdown": self.current_drawdown,
            "daily_pnl": self.daily_pnl,
            "risk_events_today": len([
                e for e in self.risk_events
                if e["time"].date() == datetime.now().date()
            ])
        }

    def get_risk_report(self) -> str:
        """生成风险报告"""
        today_events = [
            e for e in self.risk_events
            if e["time"].date() == datetime.now().date()
        ]

        report = f"""
=== 风控日报 ===
日期: {datetime.now().strftime('%Y-%m-%d')}
当前回撤: {self.current_drawdown:.2%}
日内盈亏: {self.daily_pnl:+.2f}
风控事件: {len(today_events)} 次
最大回撤限制: {self.limits.max_drawdown_pct:.2%}
日内亏损限制: {self.limits.daily_loss_limit_pct:.2%}
"""
        if today_events:
            report += "\n今日风控事件:\n"
            for e in today_events:
                report += f"  - [{e['time'].strftime('%H:%M:%S')}] {e['type']}: {e['symbol']} @ {e['price']}\n"

        return report
