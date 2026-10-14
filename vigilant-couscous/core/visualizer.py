"""
可视化仪表盘 - 回测报告、策略对比、资金曲线

提供 Chart.js 兼容的 JSON 数据，供 Web 控制台渲染。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent


@dataclass
class ChartData:
    """图表数据"""
    labels: list[str]
    datasets: list[dict[str, Any]]
    title: str = ""
    chart_type: str = "line"


class Visualizer:
    """可视化数据生成器"""

    COLORS = [
        "#58a6ff", "#3fb950", "#f85149", "#d29922", "#a371f7",
        "#79c0ff", "#56d364", "#ff7b72", "#e3b341", "#bc8cff",
    ]

    def generate_equity_curve(self, trades: list[dict],
                              initial_capital: float = 100000) -> ChartData:
        """生成资金曲线"""
        if not trades:
            return ChartData(labels=[], datasets=[], title="资金曲线")

        equity = [initial_capital]
        labels = ["起始"]
        for i, trade in enumerate(trades):
            pnl = trade.get("pnl", 0)
            equity.append(equity[-1] + pnl)
            labels.append(trade.get("symbol", f"交易{i+1}")[:8])

        return ChartData(
            labels=labels,
            datasets=[{
                "label": "资金曲线",
                "data": [round(e, 2) for e in equity],
                "borderColor": self.COLORS[0],
                "backgroundColor": f"{self.COLORS[0]}20",
                "fill": True,
                "tension": 0.3,
            }],
            title="资金曲线",
            chart_type="line",
        )

    def generate_pnl_distribution(self, trades: list[dict]) -> ChartData:
        """生成盈亏分布"""
        if not trades:
            return ChartData(labels=[], datasets=[], title="盈亏分布")

        pnls = [t.get("pnl_pct", 0) * 100 for t in trades]
        wins = [p for p in pnls if p > 0]
        [p for p in pnls if p <= 0]

        return ChartData(
            labels=[f"交易{i+1}" for i in range(len(pnls))],
            datasets=[{
                "label": "盈亏(%)",
                "data": [round(p, 2) for p in pnls],
                "backgroundColor": [
                    self.COLORS[1] if p > 0 else self.COLORS[2]
                    for p in pnls
                ],
            }],
            title=f"盈亏分布 (胜率: {len(wins)/max(len(pnls),1):.0%})",
            chart_type="bar",
        )

    def generate_strategy_comparison(self, strategies: list[dict]) -> ChartData:
        """生成策略对比"""
        if not strategies:
            return ChartData(labels=[], datasets=[], title="策略对比")

        names = [s.get("name", "unknown")[:15] for s in strategies[:8]]
        fitness = [s.get("fitness", 0) for s in strategies[:8]]
        sharpe = [s.get("sharpe", 0) for s in strategies[:8]]
        win_rate = [s.get("win_rate", 0) * 100 for s in strategies[:8]]

        return ChartData(
            labels=names,
            datasets=[
                {
                    "label": "适应度",
                    "data": [round(f, 4) for f in fitness],
                    "borderColor": self.COLORS[0],
                    "backgroundColor": f"{self.COLORS[0]}40",
                },
                {
                    "label": "夏普比率",
                    "data": [round(s, 2) for s in sharpe],
                    "borderColor": self.COLORS[1],
                    "backgroundColor": f"{self.COLORS[1]}40",
                },
                {
                    "label": "胜率(%)",
                    "data": [round(w, 1) for w in win_rate],
                    "borderColor": self.COLORS[3],
                    "backgroundColor": f"{self.COLORS[3]}40",
                },
            ],
            title="策略对比",
            chart_type="radar",
        )

    def generate_drawdown_chart(self, equity_curve: list[float]) -> ChartData:
        """生成回撤曲线"""
        if not equity_curve:
            return ChartData(labels=[], datasets=[], title="回撤曲线")

        peak = np.maximum.accumulate(equity_curve)
        drawdowns = [(p - e) / p * 100 for p, e in zip(peak, equity_curve, strict=False)]

        return ChartData(
            labels=[f"{i}" for i in range(len(drawdowns))],
            datasets=[{
                "label": "回撤(%)",
                "data": [round(d, 2) for d in drawdowns],
                "borderColor": self.COLORS[2],
                "backgroundColor": f"{self.COLORS[2]}20",
                "fill": True,
            }],
            title=f"回撤曲线 (最大: {max(drawdowns):.1f}%)",
            chart_type="line",
        )

    def generate_evolution_progress(self, evolution_history: list[dict]) -> ChartData:
        """生成进化进度"""
        if not evolution_history:
            return ChartData(labels=[], datasets=[], title="进化进度")

        cycles = [e.get("cycle", i) for i, e in enumerate(evolution_history)]
        improvements = [e.get("improvement", 0) for e in evolution_history]

        cumulative = np.cumsum(improvements)

        return ChartData(
            labels=[f"周期{c}" for c in cycles],
            datasets=[
                {
                    "label": "单次改进",
                    "data": [round(i, 4) for i in improvements],
                    "borderColor": self.COLORS[4],
                    "type": "bar",
                },
                {
                    "label": "累计改进",
                    "data": [round(c, 4) for c in cumulative],
                    "borderColor": self.COLORS[0],
                    "type": "line",
                },
            ],
            title="进化进度",
            chart_type="bar",
        )

    def generate_performance_summary(self, metrics: dict) -> dict:
        """生成性能摘要"""
        return {
            "total_return": f"{metrics.get('total_return', 0):.2%}",
            "annual_return": f"{metrics.get('annual_return', 0):.2%}",
            "sharpe_ratio": f"{metrics.get('sharpe_ratio', 0):.2f}",
            "max_drawdown": f"{metrics.get('max_drawdown', 0):.2%}",
            "win_rate": f"{metrics.get('win_rate', 0):.1%}",
            "total_trades": metrics.get('total_trades', 0),
            "profit_factor": f"{metrics.get('profit_factor', 0):.2f}",
            "avg_trade_pnl": f"{metrics.get('avg_trade_pnl', 0):.4%}",
        }

    def get_dashboard_data(self, db) -> dict:
        """获取完整仪表盘数据"""
        try:
            trades = db.get_recent_trades(100)
            strategies = db.get_top_strategies(10)
            performance = db.get_performance_history(100)

            equity_data = [100000]
            for t in reversed(trades):
                equity_data.append(equity_data[-1] + t.get("pnl", 0))

            return {
                "equity_curve": self.generate_equity_curve(trades).__dict__,
                "pnl_distribution": self.generate_pnl_distribution(trades).__dict__,
                "strategy_comparison": self.generate_strategy_comparison(strategies).__dict__,
                "drawdown_chart": self.generate_drawdown_chart(equity_data).__dict__,
                "evolution_progress": self.generate_evolution_progress(performance).__dict__,
                "performance_summary": self.generate_performance_summary(
                    performance[-1] if performance else {}
                ),
                "stats": db.get_stats(),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"仪表盘数据生成失败: {e}")
            return {"error": str(e)}


visualizer = Visualizer()
