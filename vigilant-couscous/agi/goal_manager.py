"""
AGI 自主目标管理系统 - 动态调整交易目标

实现目标驱动的智能决策：
- 目标层级：战略目标 → 战术目标 → 执行目标
- 动态调整：根据市场状态和绩效自动调整
- 风险自适应：根据回撤和波动率调整风险偏好
- 多目标优化：收益/风险/学习 三维平衡
- 目标冲突解决：自动处理矛盾目标
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MEMORY = ROOT / "memory" / "agi"
MEMORY.mkdir(parents=True, exist_ok=True)


class GoalPriority(Enum):
    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    OPTIONAL = 1


class MarketRegime(Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    VOLATILE = "volatile"
    CRISIS = "crisis"


@dataclass
class Goal:
    id: str
    description: str
    priority: GoalPriority
    target_value: float
    current_value: float
    deadline: datetime | None
    constraints: dict[str, Any]
    parent_goal: str | None
    status: str = "active"
    progress: float = 0.0
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)


@dataclass
class RiskProfile:
    max_position_size: float = 0.2
    max_drawdown: float = 0.15
    stop_loss: float = 0.05
    take_profit: float = 0.15
    max_leverage: float = 1.0
    max_correlated_positions: int = 2
    min_confidence: float = 0.6
    rebalance_interval_hours: int = 4


class GoalManager:
    """自主目标管理器

    三层目标架构：
    1. 战略目标 - 长期方向（月/年级）
    2. 战术目标 - 中期计划（周/月级）
    3. 执行目标 - 短期行动（时/日级）
    """

    STRATEGIC_TEMPLATES = {
        "capital_growth": {
            "description": "资产增值",
            "metrics": ["total_return", "annual_return"],
            "priority": GoalPriority.HIGH,
        },
        "risk_control": {
            "description": "风险控制",
            "metrics": ["max_drawdown", "sharpe_ratio"],
            "priority": GoalPriority.CRITICAL,
        },
        "learning_efficiency": {
            "description": "学习效率",
            "metrics": ["win_rate_improvement", "new_strategies"],
            "priority": GoalPriority.MEDIUM,
        },
        "market_adaptation": {
            "description": "市场适应",
            "metrics": ["regime_detection_accuracy", "strategy_diversity"],
            "priority": GoalPriority.MEDIUM,
        },
    }

    def __init__(self):
        self.goals: dict[str, Goal] = {}
        self.risk_profile = RiskProfile()
        self.current_regime = MarketRegime.SIDEWAYS
        self.performance_history: list[dict] = []
        self.goal_history: list[dict] = []
        self._init_default_goals()

    def _init_default_goals(self):
        """初始化默认目标"""
        self.add_goal("capital_growth", "月收益 5%", GoalPriority.HIGH, 0.05, 0,
                      deadline=datetime.now() + timedelta(days=30))
        self.add_goal("risk_control", "最大回撤 < 15%", GoalPriority.CRITICAL, 0.15, 0)
        self.add_goal("learning_efficiency", "每周新增 3 个有效策略", GoalPriority.MEDIUM, 3, 0,
                      deadline=datetime.now() + timedelta(days=7))
        self.add_goal("market_adaptation", "市场状态识别准确率 > 70%", GoalPriority.MEDIUM, 0.7, 0.5)

    def add_goal(self, goal_id: str, description: str, priority: GoalPriority,
                 target: float, current: float, deadline: datetime = None,
                 constraints: dict = None, parent: str = None) -> str:
        """添加新目标"""
        self.goals[goal_id] = Goal(
            id=goal_id, description=description, priority=priority,
            target_value=target, current_value=current, deadline=deadline,
            constraints=constraints or {}, parent_goal=parent,
        )
        return goal_id

    def update_progress(self, goal_id: str, current_value: float):
        """更新目标进度"""
        if goal_id not in self.goals:
            return
        goal = self.goals[goal_id]
        goal.current_value = current_value
        goal.progress = min(1.0, current_value / max(goal.target_value, 0.001))
        goal.updated = datetime.now()

        if goal.progress >= 1.0 and goal.status == "active":
            goal.status = "achieved"
            logger.info(f"目标达成: {goal.description}")

        if goal.deadline and datetime.now() > goal.deadline and goal.progress < 1.0:
            goal.status = "expired"
            logger.warning(f"目标过期: {goal.description}")

    def adapt_to_market(self, market_data: dict) -> dict[str, Any]:
        """根据市场状态自适应调整目标和风险"""
        regime = self._detect_regime(market_data)
        self.current_regime = regime

        adjustments = {"regime": regime.value, "goal_changes": [], "risk_changes": {}}

        if regime == MarketRegime.BULL:
            self.risk_profile.max_position_size = 0.3
            self.risk_profile.take_profit = 0.20
            self.risk_profile.stop_loss = 0.04
            adjustments["risk_changes"] = {"position_size": "0.2→0.3", "take_profit": "0.15→0.20"}
            self.update_progress("capital_growth", self.goals["capital_growth"].current_value * 1.1)

        elif regime == MarketRegime.BEAR:
            self.risk_profile.max_position_size = 0.1
            self.risk_profile.stop_loss = 0.03
            self.risk_profile.min_confidence = 0.75
            adjustments["risk_changes"] = {"position_size": "0.2→0.1", "min_confidence": "0.6→0.75"}

        elif regime == MarketRegime.VOLATILE:
            self.risk_profile.max_position_size = 0.15
            self.risk_profile.stop_loss = 0.06
            self.risk_profile.take_profit = 0.10
            adjustments["risk_changes"] = {"position_size": "0.2→0.15", "stop_loss": "0.05→0.06"}

        elif regime == MarketRegime.CRISIS:
            self.risk_profile.max_position_size = 0.05
            self.risk_profile.stop_loss = 0.02
            self.risk_profile.min_confidence = 0.85
            adjustments["risk_changes"] = {"position_size": "0.2→0.05", "min_confidence": "0.6→0.85"}

        adjustments["goal_changes"] = [
            {"id": g.id, "description": g.description, "progress": g.progress, "status": g.status}
            for g in self.goals.values()
        ]

        self.goal_history.append({
            "timestamp": datetime.now().isoformat(), "regime": regime.value,
            "adjustments": adjustments,
        })
        self._save()
        return adjustments

    def resolve_conflicts(self) -> list[str]:
        """解决目标冲突"""
        warnings = []
        growth_goal = self.goals.get("capital_growth")
        risk_goal = self.goals.get("risk_control")

        if growth_goal and risk_goal:
            if growth_goal.progress < 0.3 and risk_goal.progress > 0.8:
                warnings.append("过度保守：风险控制良好但收益不足，建议适度放宽风险限制")
            if growth_goal.progress > 0.8 and risk_goal.progress < 0.3:
                warnings.append("过度激进：收益良好但风险超标，建议收紧仓位")

        return warnings

    def generate_daily_goals(self) -> list[dict]:
        """生成每日执行目标"""
        daily = []
        for goal in self.goals.values():
            if goal.status != "active":
                continue
            remaining = goal.target_value - goal.current_value
            if goal.deadline:
                days_left = max(1, (goal.deadline - datetime.now()).days)
                daily_target = remaining / days_left
            else:
                daily_target = remaining / 30

            daily.append({
                "goal_id": goal.id, "description": goal.description,
                "daily_target": round(daily_target, 4), "progress": goal.progress,
                "priority": goal.priority.value,
            })

        daily.sort(key=lambda x: x["priority"], reverse=True)
        return daily

    def evaluate_performance(self, metrics: dict) -> dict:
        """评估目标完成情况"""
        self.performance_history.append({
            "timestamp": datetime.now().isoformat(), "metrics": metrics,
        })

        evaluation = {"overall_score": 0, "goal_scores": {}, "recommendations": []}

        for goal_id, goal in self.goals.items():
            if goal_id in metrics:
                self.update_progress(goal_id, metrics[goal_id])
            score = goal.progress * 100
            evaluation["goal_scores"][goal_id] = score

        scores = list(evaluation["goal_scores"].values())
        evaluation["overall_score"] = np.mean(scores) if scores else 0

        if evaluation["overall_score"] < 40:
            evaluation["recommendations"].append("整体目标完成度低，建议重新评估策略")
        if self.goals.get("risk_control", Goal(id="", description="", priority=GoalPriority.LOW,
                                                target_value=0, current_value=0, deadline=None,
                                                constraints={})).progress < 0.5:
            evaluation["recommendations"].append("风险控制目标未达标，优先降低仓位")

        self._save()
        return evaluation

    def _detect_regime(self, market_data: dict) -> MarketRegime:
        """检测市场状态"""
        close = market_data.get('close', [])
        if len(close) < 50:
            return MarketRegime.SIDEWAYS

        returns = np.diff(close[-50:]) / close[-51:-1]
        total_return = (close[-1] - close[-50]) / close[-50]
        volatility = np.std(returns) * np.sqrt(252)

        if volatility > 0.8:
            return MarketRegime.CRISIS
        if volatility > 0.5:
            return MarketRegime.VOLATILE
        if total_return > 0.15:
            return MarketRegime.BULL
        if total_return < -0.15:
            return MarketRegime.BEAR
        return MarketRegime.SIDEWAYS

    def get_risk_profile(self) -> dict:
        return {
            "max_position_size": self.risk_profile.max_position_size,
            "max_drawdown": self.risk_profile.max_drawdown,
            "stop_loss": self.risk_profile.stop_loss,
            "take_profit": self.risk_profile.take_profit,
            "min_confidence": self.risk_profile.min_confidence,
            "regime": self.current_regime.value,
        }

    def _save(self):
        data = {
            "goals": {g.id: {"description": g.description, "progress": g.progress,
                            "status": g.status, "priority": g.priority.value}
                      for g in self.goals.values()},
            "risk_profile": self.get_risk_profile(),
            "current_regime": self.current_regime.value,
            "last_updated": datetime.now().isoformat(),
        }
        (MEMORY / "goal_manager.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get_status(self) -> dict:
        return {
            "active_goals": sum(1 for g in self.goals.values() if g.status == "active"),
            "achieved_goals": sum(1 for g in self.goals.values() if g.status == "achieved"),
            "current_regime": self.current_regime.value,
            "risk_profile": self.get_risk_profile(),
            "daily_goals": self.generate_daily_goals()[:3],
            "conflicts": self.resolve_conflicts(),
        }
