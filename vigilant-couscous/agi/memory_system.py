"""
AGI 长期记忆系统 - 情景记忆 + 语义记忆

实现人类级别的记忆架构：
- 情景记忆：存储具体的交易事件和上下文
- 语义记忆：存储抽象的市场知识和规律
- 工作记忆：当前决策的临时信息
- 记忆巩固：睡眠式记忆整理和强化
- 遗忘曲线：艾宾浩斯遗忘曲线模拟
"""

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MEMORY = ROOT / "memory" / "agi"
MEMORY.mkdir(parents=True, exist_ok=True)


@dataclass
class EpisodicMemory:
    """情景记忆 - 具体的交易事件"""
    id: str
    event_type: str
    symbol: str
    action: str
    outcome: float
    context: dict[str, Any]
    emotions: dict[str, float]
    importance: float
    timestamp: datetime
    access_count: int = 0
    last_accessed: datetime | None = None
    decay_factor: float = 1.0


@dataclass
class SemanticMemory:
    """语义记忆 - 抽象的市场知识"""
    id: str
    concept: str
    category: str
    knowledge: dict[str, Any]
    confidence: float
    sources: list[str]
    created: datetime
    updated: datetime
    reinforcement_count: int = 0


@dataclass
class WorkingMemory:
    """工作记忆 - 当前决策上下文"""
    current_symbol: str
    recent_prices: list[float]
    active_positions: dict[str, Any]
    pending_decisions: list[dict]
    attention_focus: str
    cognitive_load: float
    last_updated: datetime


class MemorySystem:
    """AGI 记忆系统

    三层记忆架构：
    1. 工作记忆 - 当前决策的临时信息（容量有限）
    2. 情景记忆 - 具体交易事件（时间序列）
    3. 语义记忆 - 抽象市场知识（概念网络）
    """

    WORKING_MEMORY_CAPACITY = 7
    EPISODIC_RETENTION_DAYS = 365
    CONSOLIDATION_INTERVAL_HOURS = 4

    def __init__(self):
        self.episodic: list[EpisodicMemory] = []
        self.semantic: dict[str, SemanticMemory] = {}
        self.working: WorkingMemory | None = None
        self.concept_graph: dict[str, list[tuple[str, float]]] = defaultdict(list)
        self.last_consolidation: datetime | None = None
        self._load()

    def remember_event(self, event_type: str, symbol: str, action: str,
                       outcome: float, context: dict, emotions: dict = None) -> str:
        """记录情景记忆"""
        event_id = hashlib.md5(
            f"{event_type}:{symbol}:{action}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]

        importance = self._calculate_importance(outcome, context)

        memory = EpisodicMemory(
            id=event_id, event_type=event_type, symbol=symbol,
            action=action, outcome=outcome, context=context,
            emotions=emotions or {"surprise": abs(outcome)},
            importance=importance, timestamp=datetime.now(),
        )
        self.episodic.append(memory)

        if len(self.episodic) > 10000:
            self.episodic = sorted(self.episodic, key=lambda m: m.importance, reverse=True)[:8000]

        self._update_concept_graph(memory)
        self._save()
        return event_id

    def recall_similar(self, symbol: str, action: str = None,
                       limit: int = 10) -> list[EpisodicMemory]:
        """回忆相似的情景记忆"""
        candidates = [m for m in self.episodic if m.symbol == symbol]
        if action:
            candidates = [m for m in candidates if m.action == action]

        for m in candidates:
            m.access_count += 1
            m.last_accessed = datetime.now()
            days_since = (datetime.now() - m.timestamp).days
            m.decay_factor = max(0.1, 1.0 - days_since / self.EPISODIC_RETENTION_DAYS)

        scored = [(m, m.importance * m.decay_factor) for m in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [m for m, _ in scored[:limit]]

    def learn_concept(self, concept: str, category: str, knowledge: dict,
                      confidence: float = 0.5, sources: list[str] = None):
        """学习语义概念"""
        concept_id = hashlib.md5(concept.encode()).hexdigest()[:12]

        if concept_id in self.semantic:
            existing = self.semantic[concept_id]
            existing.knowledge.update(knowledge)
            existing.confidence = (existing.confidence * existing.reinforcement_count + confidence) / (existing.reinforcement_count + 1)
            existing.reinforcement_count += 1
            existing.updated = datetime.now()
            existing.sources.extend(sources or [])
        else:
            self.semantic[concept_id] = SemanticMemory(
                id=concept_id, concept=concept, category=category,
                knowledge=knowledge, confidence=confidence,
                sources=sources or [], created=datetime.now(),
                updated=datetime.now(), reinforcement_count=1,
            )

        self._save()

    def query_knowledge(self, query: str, category: str = None) -> list[SemanticMemory]:
        """查询语义知识"""
        results = []
        query_lower = query.lower()
        for mem in self.semantic.values():
            if category and mem.category != category:
                continue
            relevance = 0
            if query_lower in mem.concept.lower():
                relevance += 0.5
            for key, value in mem.knowledge.items():
                if query_lower in str(key).lower() or query_lower in str(value).lower():
                    relevance += 0.3
            if relevance > 0:
                results.append((mem, relevance * mem.confidence))
        results.sort(key=lambda x: x[1], reverse=True)
        return [m for m, _ in results[:10]]

    def update_working_memory(self, symbol: str, prices: list[float],
                              positions: dict, decisions: list[dict],
                              attention: str = "market_analysis"):
        """更新工作记忆"""
        cognitive_load = min(1.0, (len(positions) * 0.2 + len(decisions) * 0.15))
        self.working = WorkingMemory(
            current_symbol=symbol, recent_prices=prices[-20:],
            active_positions=positions, pending_decisions=decisions[-self.WORKING_MEMORY_CAPACITY:],
            attention_focus=attention, cognitive_load=cognitive_load,
            last_updated=datetime.now(),
        )

    def consolidate(self):
        """记忆巩固 - 整理和强化重要记忆"""
        now = datetime.now()
        if self.last_consolidation and (now - self.last_consolidation).seconds < self.CONSOLIDATION_INTERVAL_HOURS * 3600:
            return

        logger.info("记忆巩固中...")

        important_events = [m for m in self.episodic if m.importance > 0.5]
        for event in important_events[-50:]:
            concept_key = f"{event.symbol}_{event.action}_{'win' if event.outcome > 0 else 'loss'}"
            self.learn_concept(
                concept=concept_key,
                category="trading_pattern",
                knowledge={
                    "symbol": event.symbol, "action": event.action,
                    "avg_outcome": event.outcome, "context": event.context,
                },
                confidence=min(0.9, event.importance),
            )

        self._prune_weak_memories()
        self.last_consolidation = now
        self._save()
        logger.info(f"记忆巩固完成: {len(self.episodic)} 情景, {len(self.semantic)} 语义")

    def _calculate_importance(self, outcome: float, context: dict) -> float:
        """计算记忆重要性"""
        importance = abs(outcome) * 5
        if abs(outcome) > 0.05:
            importance += 0.3
        if context.get("volatility", 0) > 0.5:
            importance += 0.2
        if context.get("was_agi_decision", False):
            importance += 0.2
        return min(1.0, importance)

    def _update_concept_graph(self, memory: EpisodicMemory):
        """更新概念关联图"""
        concepts = [memory.symbol, memory.action, memory.event_type]
        for i, c1 in enumerate(concepts):
            for c2 in concepts[i+1:]:
                existing = [w for c, w in self.concept_graph[c1] if c == c2]
                if existing:
                    self.concept_graph[c1] = [(c, w + 0.1) if c == c2 else (c, w) for c, w in self.concept_graph[c1]]
                else:
                    self.concept_graph[c1].append((c2, 0.1))
                self.concept_graph[c1] = [(c, min(w, 1.0)) for c, w in self.concept_graph[c1]]

    def _prune_weak_memories(self):
        """修剪弱记忆"""
        threshold = 0.1
        self.episodic = [m for m in self.episodic if m.importance * m.decay_factor > threshold]
        self.semantic = {
            k: v for k, v in self.semantic.items()
            if v.confidence > 0.2 or v.reinforcement_count > 2
        }

    def get_memory_stats(self) -> dict:
        """获取记忆统计"""
        return {
            "episodic_count": len(self.episodic),
            "semantic_count": len(self.semantic),
            "concept_graph_edges": sum(len(v) for v in self.concept_graph.values()),
            "working_memory_load": self.working.cognitive_load if self.working else 0,
            "last_consolidation": self.last_consolidation.isoformat() if self.last_consolidation else None,
            "avg_importance": np.mean([m.importance for m in self.episodic]) if self.episodic else 0,
        }

    def _save(self):
        data = {
            "episodic_count": len(self.episodic),
            "semantic_count": len(self.semantic),
            "concept_graph": {k: [(c, w) for c, w in v] for k, v in self.concept_graph.items()},
            "last_updated": datetime.now().isoformat(),
        }
        (MEMORY / "memory_system.json").write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))

    def _load(self):
        mf = MEMORY / "memory_system.json"
        if mf.exists():
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
                for k, v in data.get("concept_graph", {}).items():
                    self.concept_graph[k] = [(c, w) for c, w in v]
            except Exception:
                pass
