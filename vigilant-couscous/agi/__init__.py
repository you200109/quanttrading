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

2026-10-16 P3b：原 __init__  eager 全量导入 14 个子模块——每个子模块导入时
都会执行 mkdir 等模块级副作用，且 7 个模块（distributed_orchestrator /
zero_shot_adapter / market_scanner / goal_manager / self_reflection /
multi_modal_perception / auto_refactor）无任何调用方，纯属拖累导入速度。
现改为 PEP 562 __getattr__ 懒加载：import agi 不再触达任何子模块，
属性访问 / from agi import X 时才按需导入对应子模块。
"""

import importlib

# name -> (submodule, attr)
_LAZY_EXPORTS = {
    # 认知层
    "AGIBrain": ("agi_brain", "AGIBrain"),
    "MarketContext": ("agi_brain", "MarketContext"),
    "AGIDecision": ("agi_brain", "AGIDecision"),
    "SelfReflectionEngine": ("self_reflection", "SelfReflectionEngine"),
    "TradeRecord": ("self_reflection", "TradeRecord"),
    "Reflection": ("self_reflection", "Reflection"),
    "MultiModalPerception": ("multi_modal_perception", "MultiModalPerception"),
    "UnifiedPerception": ("multi_modal_perception", "UnifiedPerception"),
    "MemorySystem": ("memory_system", "MemorySystem"),
    "EpisodicMemory": ("memory_system", "EpisodicMemory"),
    "SemanticMemory": ("memory_system", "SemanticMemory"),
    "WorkingMemory": ("memory_system", "WorkingMemory"),
    "GoalManager": ("goal_manager", "GoalManager"),
    "Goal": ("goal_manager", "Goal"),
    "RiskProfile": ("goal_manager", "RiskProfile"),
    "MarketRegime": ("goal_manager", "MarketRegime"),
    "GoalPriority": ("goal_manager", "GoalPriority"),
    # 进化层
    "ContinuousLearner": ("continuous_learner", "ContinuousLearner"),
    "Experience": ("continuous_learner", "Experience"),
    "LearningUpdate": ("continuous_learner", "LearningUpdate"),
    "AdversarialTraining": ("adversarial_training", "AdversarialTraining"),
    "StrategyAgent": ("adversarial_training", "StrategyAgent"),
    "BattleResult": ("adversarial_training", "BattleResult"),
    "MetaLearner": ("meta_learner", "MetaLearner"),
    "LearningConfig": ("meta_learner", "LearningConfig"),
    "MetaKnowledge": ("meta_learner", "MetaKnowledge"),
    "ZeroShotAdapter": ("zero_shot_adapter", "ZeroShotAdapter"),
    "MarketProfile": ("zero_shot_adapter", "MarketProfile"),
    "AdaptationResult": ("zero_shot_adapter", "AdaptationResult"),
    # 协同层
    "DistributedOrchestrator": ("distributed_orchestrator", "DistributedOrchestrator"),
    "AGIInstance": ("distributed_orchestrator", "AGIInstance"),
    "ConsensusResult": ("distributed_orchestrator", "ConsensusResult"),
    "Task": ("distributed_orchestrator", "Task"),
    "AutoResearcher": ("auto_researcher", "AutoResearcher"),
    "ResearchPaper": ("auto_researcher", "ResearchPaper"),
    "ResearchHypothesis": ("auto_researcher", "ResearchHypothesis"),
    # 执行层
    "AutoRefactor": ("auto_refactor", "AutoRefactor"),
    "CodeAnalysis": ("auto_refactor", "CodeAnalysis"),
    "RefactorResult": ("auto_refactor", "RefactorResult"),
    "MarketScanner": ("market_scanner", "MarketScanner"),
    "MarketOpportunity": ("market_scanner", "MarketOpportunity"),
    "OrderSuggestion": ("market_scanner", "OrderSuggestion"),
    "EternalEvolver": ("eternal_evolver", "EternalEvolver"),
    "EvolutionGoal": ("eternal_evolver", "EvolutionGoal"),
    "EvolutionRecord": ("eternal_evolver", "EvolutionRecord"),
    "Innovation": ("eternal_evolver", "Innovation"),
}

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


def __getattr__(name: str):
    """PEP 562 懒加载：首次访问导出名时导入对应子模块"""
    try:
        submodule_name, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    module = importlib.import_module(f".{submodule_name}", __name__)
    return getattr(module, attr)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
