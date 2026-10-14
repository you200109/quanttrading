"""
AGI 自我反思引擎 - 交易复盘与策略逻辑修正

实现真正的"从错误中学习"：
- 每笔交易后自动复盘分析
- 因果推理：为什么盈利/亏损
- 策略逻辑自动修正
- 知识图谱积累
- 反思驱动的策略进化
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MEMORY = ROOT / "memory" / "agi"
MEMORY.mkdir(parents=True, exist_ok=True)


@dataclass
class TradeRecord:
    symbol: str
    action: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    entry_time: datetime
    exit_time: datetime
    reasoning: str
    market_conditions: dict


@dataclass
class Reflection:
    trade: TradeRecord
    root_cause: str
    was_correct: bool
    lessons: list[str]
    strategy_fix: str | None
    confidence_adjustment: float
    timestamp: datetime = field(default_factory=datetime.now)


class SelfReflectionEngine:
    """自我反思引擎

    核心能力：
    1. 交易复盘 - 分析每笔交易的完整生命周期
    2. 因果推理 - 找出盈利/亏损的根本原因
    3. 模式识别 - 发现重复出现的错误模式
    4. 策略修正 - 自动调整策略参数和逻辑
    5. 知识积累 - 构建可查询的经验知识库
    """

    def __init__(self):
        self.reflections: list[Reflection] = []
        self.error_patterns: dict[str, int] = defaultdict(int)
        self.success_patterns: dict[str, int] = defaultdict(int)
        self.knowledge_graph: dict[str, Any] = self._load_knowledge()
        self.llm_client = None
        self._init_llm()

    def _init_llm(self):
        try:
            import os
            if os.getenv("OPENAI_API_KEY"):
                from openai import OpenAI
                self.llm_client = OpenAI()
            elif os.getenv("ANTHROPIC_API_KEY"):
                from anthropic import Anthropic
                self.llm_client = Anthropic()
        except ImportError:
            pass

    def reflect_on_trade(self, trade: TradeRecord, market_data: dict) -> Reflection:
        """对单笔交易进行深度反思"""
        was_correct = trade.pnl > 0

        if self.llm_client:
            root_cause, lessons, strategy_fix = self._llm_reflect(trade, market_data)
        else:
            root_cause, lessons, strategy_fix = self._builtin_reflect(trade, market_data)

        if was_correct:
            self.success_patterns[root_cause[:50]] += 1
        else:
            self.error_patterns[root_cause[:50]] += 1

        confidence_adj = 0.05 if was_correct else -0.1
        if abs(trade.pnl_pct) > 0.1:
            confidence_adj *= 2

        reflection = Reflection(
            trade=trade, root_cause=root_cause, was_correct=was_correct,
            lessons=lessons, strategy_fix=strategy_fix,
            confidence_adjustment=confidence_adj,
        )
        self.reflections.append(reflection)
        self._update_knowledge(reflection)
        self._save()

        emoji = "✅" if was_correct else "❌"
        logger.info(f"{emoji} 反思: {trade.symbol} {trade.action} PnL={trade.pnl_pct:.2%} | {root_cause[:60]}")
        return reflection

    def _llm_reflect(self, trade: TradeRecord, market_data: dict) -> tuple:
        prompt = f"""分析这笔交易：
- 币种: {trade.symbol}
- 操作: {trade.action}
- 入场价: ${trade.entry_price:,.2f}
- 出场价: ${trade.exit_price:,.2f}
- 盈亏: {trade.pnl_pct:.2%}
- 入场理由: {trade.reasoning}
- 市场条件: {json.dumps(trade.market_conditions, ensure_ascii=False)}

请分析：
1. 这笔交易盈利/亏损的根本原因是什么？
2. 从中学到了什么教训？
3. 策略应该如何调整？

返回 JSON：
{{"root_cause": "根本原因", "lessons": ["教训1", "教训2"], "strategy_fix": "策略修正建议"}}"""
        try:
            if hasattr(self.llm_client, 'chat'):
                response = self.llm_client.chat.completions.create(
                    model="gpt-4", messages=[
                        {"role": "system", "content": "你是一个交易复盘专家，擅长分析交易成败的根本原因。"},
                        {"role": "user", "content": prompt}
                    ], temperature=0.5, max_tokens=500
                )
                result = json.loads(response.choices[0].message.content)
            else:
                response = self.llm_client.messages.create(
                    model="claude-3-opus-20240229", max_tokens=500,
                    system="你是一个交易复盘专家。",
                    messages=[{"role": "user", "content": prompt}]
                )
                result = json.loads(response.content[0].text)
            return result.get("root_cause", ""), result.get("lessons", []), result.get("strategy_fix", "")
        except Exception as e:
            logger.error(f"LLM 反思失败: {e}")
            return self._builtin_reflect(trade, market_data)

    def _builtin_reflect(self, trade: TradeRecord, market_data: dict) -> tuple:
        root_cause_parts = []
        lessons = []

        if trade.pnl > 0:
            root_cause_parts.append(f"{trade.action}操作盈利")
            if trade.pnl_pct > 0.05:
                root_cause_parts.append("大盈利")
                lessons.append("大盈利交易的特征值得记录和复用")
            else:
                lessons.append("小额盈利，策略基本正确")
        else:
            root_cause_parts.append(f"{trade.action}操作亏损")
            if abs(trade.pnl_pct) > 0.05:
                root_cause_parts.append("大亏损，需重点分析")
                lessons.append("大亏损交易需检查是否违反风控规则")
            if trade.market_conditions.get("volatility", 0) > 0.5:
                root_cause_parts.append("高波动环境")
                lessons.append("高波动环境下应降低仓位")
            if trade.market_conditions.get("trend", "") != trade.action:
                root_cause_parts.append("逆势交易")
                lessons.append("避免逆势交易，应顺势而为")

        strategy_fix = ""
        if "逆势" in " ".join(root_cause_parts):
            strategy_fix = "增加趋势过滤条件，仅在趋势明确时交易"
        elif "高波动" in " ".join(root_cause_parts):
            strategy_fix = "高波动时降低仓位至正常的50%"
        elif "大亏损" in " ".join(root_cause_parts):
            strategy_fix = "收紧止损至3%，增加最大回撤限制"

        return " | ".join(root_cause_parts), lessons, strategy_fix

    def analyze_patterns(self) -> dict:
        """分析错误和成功模式"""
        total = len(self.reflections)
        if total == 0:
            return {"status": "no_data"}

        wins = sum(1 for r in self.reflections if r.was_correct)
        losses = total - wins

        top_errors = sorted(self.error_patterns.items(), key=lambda x: x[1], reverse=True)[:5]
        top_successes = sorted(self.success_patterns.items(), key=lambda x: x[1], reverse=True)[:5]

        recent_lessons = []
        for r in self.reflections[-10:]:
            recent_lessons.extend(r.lessons)

        return {
            "total_trades": total,
            "win_rate": wins / total if total > 0 else 0,
            "wins": wins, "losses": losses,
            "top_error_patterns": [{"pattern": p, "count": c} for p, c in top_errors],
            "top_success_patterns": [{"pattern": p, "count": c} for p, c in top_successes],
            "recent_lessons": list(set(recent_lessons))[-10:],
            "avg_confidence_adjustment": sum(r.confidence_adjustment for r in self.reflections) / total,
        }

    def get_strategy_improvements(self) -> list[dict]:
        """获取策略改进建议"""
        improvements = []
        for r in self.reflections[-20:]:
            if r.strategy_fix and not r.was_correct:
                improvements.append({
                    "issue": r.root_cause,
                    "fix": r.strategy_fix,
                    "trade": f"{r.trade.symbol} {r.trade.action}",
                    "pnl": r.trade.pnl_pct,
                    "timestamp": r.timestamp.isoformat(),
                })
        return improvements

    def _update_knowledge(self, reflection: Reflection):
        kg = self.knowledge_graph
        kg.setdefault("total_reflections", 0)
        kg["total_reflections"] += 1

        symbol = reflection.trade.symbol
        kg.setdefault("by_symbol", {})
        kg["by_symbol"].setdefault(symbol, {"wins": 0, "losses": 0, "total_pnl": 0})
        if reflection.was_correct:
            kg["by_symbol"][symbol]["wins"] += 1
        else:
            kg["by_symbol"][symbol]["losses"] += 1
        kg["by_symbol"][symbol]["total_pnl"] += reflection.trade.pnl_pct

        for lesson in reflection.lessons:
            kg.setdefault("lessons", []).append({
                "lesson": lesson, "trade": reflection.trade.symbol,
                "timestamp": reflection.timestamp.isoformat(),
            })
        kg["lessons"] = kg["lessons"][-100:]

    def _save(self):
        data = {
            "total_reflections": len(self.reflections),
            "knowledge_graph": self.knowledge_graph,
            "error_patterns": dict(self.error_patterns),
            "success_patterns": dict(self.success_patterns),
            "recent_reflections": [
                {"symbol": r.trade.symbol, "pnl": r.trade.pnl_pct,
                 "root_cause": r.root_cause, "was_correct": r.was_correct}
                for r in self.reflections[-20:]
            ],
            "last_updated": datetime.now().isoformat(),
        }
        (MEMORY / "reflection_engine.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str))

    def _load_knowledge(self) -> dict:
        kf = MEMORY / "reflection_engine.json"
        if kf.exists():
            return json.loads(kf.read_text(encoding="utf-8")).get("knowledge_graph", {})
        return {}

    def get_status(self) -> dict:
        patterns = self.analyze_patterns()
        improvements = self.get_strategy_improvements()
        return {
            "total_reflections": len(self.reflections),
            "patterns": patterns,
            "pending_improvements": len(improvements),
            "top_improvements": improvements[:3],
        }
