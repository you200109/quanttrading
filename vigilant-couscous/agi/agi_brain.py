"""
AGI 核心大脑 - LLM 驱动的自主交易智能

替代传统规则引擎，实现：
- 自然语言理解市场状态
- 自主生成交易策略（非模板）
- 多步推理链（Chain-of-Thought）
- 动态风险评估
- 策略解释和透明度
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MEMORY = ROOT / "memory" / "agi"
MEMORY.mkdir(parents=True, exist_ok=True)


@dataclass
class MarketContext:
    symbol: str
    current_price: float
    trend: str
    volatility: float
    volume_profile: str
    support_levels: list[float]
    resistance_levels: list[float]
    recent_events: list[str]
    sentiment: dict[str, float]


@dataclass
class AGIDecision:
    action: str
    confidence: float
    reasoning: str
    risk_assessment: str
    expected_outcome: str
    fallback_plan: str
    learning_points: list[str]
    timestamp: datetime = field(default_factory=datetime.now)


class AGIBrain:
    SYSTEM_PROMPT = """你是一个 AGI 交易系统核心大脑。你的能力远超传统量化策略：

1. **市场理解**：你能从价格、成交量、波动率等数据中理解市场的真实状态
2. **策略生成**：你不使用预定义模板，而是根据当前市场状态自主创造策略
3. **多步推理**：你使用 Chain-of-Thought 推理，逐步分析并得出结论
4. **风险管理**：你动态评估风险，而非使用固定止损止盈
5. **自我反思**：你从每次决策中学习，持续改进

请用中文回复，格式为 JSON。"""

    def __init__(self, model: str = "auto"):
        self.model = model
        self.decision_history: list[AGIDecision] = []
        self.knowledge_base: dict[str, Any] = self._load_knowledge()
        self.llm_client = None
        self._init_llm()

    def _init_llm(self):
        try:
            import os
            if os.getenv("OPENAI_API_KEY"):
                from openai import OpenAI
                self.llm_client = OpenAI()
                self.model = "gpt-4"
                logger.info("AGI Brain: 使用 OpenAI GPT-4")
            elif os.getenv("ANTHROPIC_API_KEY"):
                from anthropic import Anthropic
                self.llm_client = Anthropic()
                self.model = "claude-3-opus-20240229"
                logger.info("AGI Brain: 使用 Anthropic Claude")
            else:
                logger.warning("AGI Brain: 无 LLM API Key，使用内置推理引擎")
        except ImportError:
            logger.warning("AGI Brain: LLM 库未安装，使用内置推理引擎")

    def analyze_market(self, data: dict, symbol: str) -> MarketContext:
        close = data.get('close', [])
        volume = data.get('volume', [])
        high = data.get('high', [])
        low = data.get('low', [])
        if len(close) < 20:
            return MarketContext(symbol=symbol, current_price=0, trend="unknown",
                                volatility=0, volume_profile="unknown",
                                support_levels=[], resistance_levels=[],
                                recent_events=[], sentiment={})
        import numpy as np
        current_price = float(close[-1])
        returns = np.diff(close) / close[:-1]
        volatility = float(np.std(returns[-20:]) * np.sqrt(252))
        sma_20 = np.mean(close[-20:])
        np.mean(close[-50:]) if len(close) >= 50 else sma_20
        if current_price > sma_20 * 1.03:
            trend = "强势上涨"
        elif current_price > sma_20:
            trend = "温和上涨"
        elif current_price < sma_20 * 0.97:
            trend = "强势下跌"
        elif current_price < sma_20:
            trend = "温和下跌"
        else:
            trend = "横盘震荡"
        vol_ma = np.mean(volume[-20:])
        vol_current = volume[-1]
        if vol_current > vol_ma * 2:
            volume_profile = "放量"
        elif vol_current > vol_ma * 1.3:
            volume_profile = "温和放量"
        elif vol_current < vol_ma * 0.5:
            volume_profile = "缩量"
        else:
            volume_profile = "正常"
        recent_low = np.min(low[-20:])
        recent_high = np.max(high[-20:])
        support_levels = [round(recent_low, 2), round(recent_low * 1.01, 2)]
        resistance_levels = [round(recent_high, 2), round(recent_high * 0.99, 2)]
        return MarketContext(
            symbol=symbol, current_price=round(current_price, 2),
            trend=trend, volatility=round(volatility, 4),
            volume_profile=volume_profile,
            support_levels=support_levels, resistance_levels=resistance_levels,
            recent_events=[], sentiment={"fear_greed": 50}
        )

    def think(self, context: MarketContext, portfolio: dict) -> AGIDecision:
        if self.llm_client:
            return self._llm_think(context, portfolio)
        return self._builtin_think(context, portfolio)

    def _llm_think(self, context: MarketContext, portfolio: dict) -> AGIDecision:
        prompt = f"""当前市场状态：
- 币种: {context.symbol}
- 价格: ${context.current_price:,.2f}
- 趋势: {context.trend}
- 波动率: {context.volatility:.2%}
- 成交量: {context.volume_profile}
- 支撑位: {context.support_levels}
- 阻力位: {context.resistance_levels}

投资组合：
- 总资产: ${portfolio.get('total_value', 100000):,.2f}
- 持仓数: {portfolio.get('position_count', 0)}
- 总收益: {portfolio.get('total_return', 0):.2%}

请进行多步推理分析并返回 JSON：
{{"action": "buy/sell/hold", "confidence": 0.0-1.0, "reasoning": "推理过程",
  "risk_assessment": "风险评估", "expected_outcome": "预期结果",
  "fallback_plan": "备选方案", "learning_points": ["学习点1", "学习点2"]}}"""
        try:
            if hasattr(self.llm_client, 'chat'):
                response = self.llm_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ], temperature=0.7, max_tokens=1000
                )
                result = json.loads(response.choices[0].message.content)
            else:
                response = self.llm_client.messages.create(
                    model=self.model, max_tokens=1000,
                    system=self.SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}]
                )
                result = json.loads(response.content[0].text)
            decision = AGIDecision(
                action=result.get("action", "hold"),
                confidence=result.get("confidence", 0.5),
                reasoning=result.get("reasoning", ""),
                risk_assessment=result.get("risk_assessment", ""),
                expected_outcome=result.get("expected_outcome", ""),
                fallback_plan=result.get("fallback_plan", ""),
                learning_points=result.get("learning_points", []),
            )
            self.decision_history.append(decision)
            self._save_decision(decision, context)
            return decision
        except Exception as e:
            logger.error(f"LLM 推理失败: {e}，使用内置引擎")
            return self._builtin_think(context, portfolio)

    def _builtin_think(self, context: MarketContext, portfolio: dict) -> AGIDecision:
        reasoning_parts = []
        score = 0
        if "上涨" in context.trend:
            reasoning_parts.append(f"趋势向好({context.trend})")
            score += 20
        elif "下跌" in context.trend:
            reasoning_parts.append(f"趋势偏弱({context.trend})")
            score -= 20
        else:
            reasoning_parts.append("趋势不明朗")
        if context.volatility > 0.5:
            reasoning_parts.append(f"高波动({context.volatility:.1%})，需谨慎")
            score -= 10
        elif context.volatility < 0.2:
            reasoning_parts.append(f"低波动({context.volatility:.1%})，适合建仓")
            score += 10
        if context.volume_profile == "放量":
            reasoning_parts.append("放量信号，市场活跃")
            score += 15 if "上涨" in context.trend else -15
        if context.current_price <= context.support_levels[0] * 1.02:
            reasoning_parts.append(f"接近支撑位 ${context.support_levels[0]:,.2f}")
            score += 15
        elif context.current_price >= context.resistance_levels[0] * 0.98:
            reasoning_parts.append(f"接近阻力位 ${context.resistance_levels[0]:,.2f}")
            score -= 15
        position_count = portfolio.get('position_count', 0)
        if position_count >= 3:
            reasoning_parts.append("仓位已满，建议观望")
            score -= 20
        if score >= 30:
            action, confidence = "buy", min(0.9, score / 60)
        elif score <= -30:
            action, confidence = "sell", min(0.9, abs(score) / 60)
        else:
            action, confidence = "hold", 0.5
        decision = AGIDecision(
            action=action, confidence=confidence,
            reasoning=" | ".join(reasoning_parts),
            risk_assessment=f"综合评分: {score}，波动率: {context.volatility:.1%}",
            expected_outcome=f"预期{'盈利' if action == 'buy' else '避险' if action == 'sell' else '等待机会'}",
            fallback_plan="若趋势反转则止损",
            learning_points=[f"{context.symbol} {context.trend}环境下{'做多' if score > 0 else '观望'}评分{score}"],
        )
        self.decision_history.append(decision)
        self._save_decision(decision, context)
        return decision

    def reflect(self, decision: AGIDecision, actual_outcome: dict) -> dict:
        was_correct = (decision.action == "buy" and actual_outcome.get("profit", 0) > 0) or \
                      (decision.action == "sell" and actual_outcome.get("profit", 0) > 0) or \
                      (decision.action == "hold")
        reflection = {
            "decision": decision.action, "confidence": decision.confidence,
            "actual_profit": actual_outcome.get("profit", 0),
            "was_correct": was_correct, "lessons": [],
            "timestamp": datetime.now().isoformat(),
        }
        if not was_correct and decision.confidence > 0.7:
            reflection["lessons"].append("高置信度决策出错，需检查推理逻辑")
        if actual_outcome.get("profit", 0) < -0.05:
            reflection["lessons"].append("大额亏损，需加强风控")
        if was_correct:
            reflection["lessons"].append(f"决策正确，{decision.reasoning[:50]}...")
        self.knowledge_base.setdefault("reflections", []).append(reflection)
        self._save_knowledge()
        return reflection

    def generate_strategy_code(self, context: MarketContext) -> str:
        if self.llm_client:
            return self._llm_generate_code(context)
        return self._builtin_generate_code(context)

    def _llm_generate_code(self, context: MarketContext) -> str:
        prompt = f"""为 {context.symbol} 当前市场状态生成一个 Python 交易策略类：
- 趋势: {context.trend}
- 波动率: {context.volatility:.2%}
- 成交量: {context.volume_profile}

要求：
1. 类名使用 PascalCase
2. 包含 generate_signal(data) 方法返回 {{"action": "buy/sell/hold", "confidence": 0-1}}
3. 策略逻辑要针对当前市场状态优化
4. 添加详细注释解释每个决策

只返回 Python 代码，不要其他内容。"""
        try:
            if hasattr(self.llm_client, 'chat'):
                response = self.llm_client.chat.completions.create(
                    model=self.model, messages=[
                        {"role": "system", "content": "你是一个量化交易策略专家，擅长生成 Python 代码。"},
                        {"role": "user", "content": prompt}
                    ], temperature=0.8, max_tokens=2000
                )
                return response.choices[0].message.content
            else:
                response = self.llm_client.messages.create(
                    model=self.model, max_tokens=2000,
                    system="你是一个量化交易策略专家。",
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text
        except Exception as e:
            logger.error(f"代码生成失败: {e}")
            return self._builtin_generate_code(context)

    def _builtin_generate_code(self, context: MarketContext) -> str:
        return f'''"""
AGI 自动生成策略 - {context.symbol}
市场状态: {context.trend}, 波动率: {context.volatility:.2%}
生成时间: {datetime.now().isoformat()}
"""
import numpy as np

class AGIStrategy_{datetime.now().strftime("%m%d%H%M")}:
    def __init__(self):
        self.context = {{"trend": "{context.trend}", "volatility": {context.volatility}}}

    def generate_signal(self, data):
        close = data['close'].values
        if len(close) < 20:
            return {{"action": "hold", "confidence": 0}}
        price = close[-1]
        sma_20 = np.mean(close[-20:])
        volatility = np.std(np.diff(close[-20:]) / close[-21:-1])
        if price > sma_20 * 1.02 and volatility < 0.03:
            return {{"action": "buy", "confidence": 0.7, "reason": "趋势向上+低波动"}}
        elif price < sma_20 * 0.98:
            return {{"action": "sell", "confidence": 0.6, "reason": "跌破均线"}}
        return {{"action": "hold", "confidence": 0.5, "reason": "等待信号"}}
'''

    def _save_decision(self, decision: AGIDecision, context: MarketContext):
        record = {
            "action": decision.action, "confidence": decision.confidence,
            "reasoning": decision.reasoning, "symbol": context.symbol,
            "price": context.current_price, "trend": context.trend,
            "timestamp": decision.timestamp.isoformat(),
        }
        decisions_file = MEMORY / "agi_decisions.jsonl"
        with open(decisions_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _save_knowledge(self):
        (MEMORY / "agi_knowledge.json").write_text(
            json.dumps(self.knowledge_base, indent=2, ensure_ascii=False, default=str))

    def _load_knowledge(self) -> dict:
        kf = MEMORY / "agi_knowledge.json"
        if kf.exists():
            return json.loads(kf.read_text(encoding="utf-8"))
        return {"reflections": [], "strategies_generated": 0, "total_decisions": 0}

    def get_status(self) -> dict:
        return {
            "total_decisions": len(self.decision_history),
            "knowledge_entries": len(self.knowledge_base.get("reflections", [])),
            "model": self.model,
            "llm_available": self.llm_client is not None,
            "recent_decisions": [
                {"action": d.action, "confidence": d.confidence, "reasoning": d.reasoning[:80]}
                for d in self.decision_history[-5:]
            ],
        }
