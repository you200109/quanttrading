"""
AGI 自进化交易系统 - 完整认知架构

14 个核心模块，覆盖认知层、进化层、协同层、执行层：

认知层：
- AGIBrain - LLM 驱动的自主交易智能
- SelfReflectionEngine - 交易复盘与策略逻辑修正
- MultiModalPerception - 新闻/社交媒体/链上数据融合
- MemorySystem - 情景记忆 + 语义记忆双层存储
- GoalManager - 自主目标管理和风险自适应

进化层：
- ContinuousLearner - 在线增量学习引擎
- AdversarialTraining - 多策略博弈进化
- MetaLearner - 学习如何学习的元学习
- ZeroShotAdapter - 新市场零样本泛化

协同层：
- DistributedOrchestrator - 多 AGI 实例分布式协同
- AutoResearcher - 自主学术研究和策略发现

执行层：
- AutoRefactor - 自主代码理解和重构
- MarketScanner - 全市场扫描和高频自适应
- SelfProgrammingEngine - GitHub 代码搜索和注入
"""

from .adversarial_training import AdversarialTraining, BattleResult, StrategyAgent
from .agi_brain import AGIBrain, AGIDecision, MarketContext
from .auto_refactor import AutoRefactor, CodeAnalysis, RefactorResult
from .auto_researcher import AutoResearcher, ResearchHypothesis, ResearchPaper
from .continuous_learner import ContinuousLearner, Experience, LearningUpdate
from .distributed_orchestrator import AGIInstance, ConsensusResult, DistributedOrchestrator, Task
from .eternal_evolver import EternalEvolver, EvolutionGoal, EvolutionRecord, Innovation
from .goal_manager import Goal, GoalManager, GoalPriority, MarketRegime, RiskProfile
from .market_scanner import MarketOpportunity, MarketScanner, OrderSuggestion
from .memory_system import EpisodicMemory, MemorySystem, SemanticMemory, WorkingMemory
from .meta_learner import LearningConfig, MetaKnowledge, MetaLearner
from .multi_modal_perception import MultiModalPerception, UnifiedPerception
from .self_reflection import Reflection, SelfReflectionEngine, TradeRecord
from .zero_shot_adapter import AdaptationResult, MarketProfile, ZeroShotAdapter

__all__ = [
    "AGIBrain", "MarketContext", "AGIDecision",
    "SelfReflectionEngine", "TradeRecord", "Reflection",
    "MultiModalPerception", "UnifiedPerception",
    "MemorySystem", "EpisodicMemory", "SemanticMemory", "WorkingMemory",
    "GoalManager", "Goal", "RiskProfile", "MarketRegime", "GoalPriority",
    "ContinuousLearner", "Experience", "LearningUpdate",
    "AdversarialTraining", "StrategyAgent", "BattleResult",
    "MetaLearner", "LearningConfig", "MetaKnowledge",
    "ZeroShotAdapter", "MarketProfile", "AdaptationResult",
    "DistributedOrchestrator", "AGIInstance", "ConsensusResult", "Task",
    "AutoResearcher", "ResearchPaper", "ResearchHypothesis",
    "AutoRefactor", "CodeAnalysis", "RefactorResult",
    "MarketScanner", "MarketOpportunity", "OrderSuggestion",
    "EternalEvolver", "EvolutionGoal", "EvolutionRecord", "Innovation",
]
