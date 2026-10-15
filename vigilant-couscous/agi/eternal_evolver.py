"""
AGI 永续进化引擎 - 永不停止的自我迭代

实现真正的"永远进化"：
- 自主目标发现：系统自己决定下一步进化什么
- 开放式探索：不受限于预定义策略空间
- 自我评估：自动判断进化是否有效
- 知识传承：每次进化的经验积累
- 永续循环：永不停止的进化循环
- 突变创新：随机引入全新概念
- 跨域迁移：将其他领域的成功模式迁移到交易

2026-10-16 P3b：进化改进度由 random.uniform 假度量改为真实系统状态增量
（策略库通过数/库规模/风控覆盖/内化数/语义记忆/归档目标/发现数，
数据源全部文件可查）；四个 _evolve_* 方法各自执行真实动作
（参数入库/风控审计修复/记忆巩固/目标治理）；_last_system_state 持久化，
支撑 _self_assess 的跨周期增长评估；突变适用度静态化。
"""

import hashlib
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MEMORY = ROOT / "memory" / "agi"
MEMORY.mkdir(parents=True, exist_ok=True)
ETERNAL_LOG = MEMORY / "eternal_evolution.jsonl"

# 2026-10-16 P3b：真实系统状态度量的数据源。
# 与 strategy/learning_engine（NEXUS）、evolution/learning_loop（memory/iterations）、
# agi/memory_system（memory/agi/memory_system.json）的仓库数据契约一致。
STRATEGY_LIB = ROOT / "memory" / "nexus" / "gh_strategy_library.json"
ITERATIONS_DIR = ROOT / "memory" / "iterations"
SEMANTIC_FILE = MEMORY / "memory_system.json"
GOAL_ARCHIVE = MEMORY / "goal_archive.json"
DEFAULT_STOP_LOSS = 0.05
DEFAULT_TAKE_PROFIT = 0.15


@dataclass
class EvolutionGoal:
    """进化目标"""
    id: str
    description: str
    domain: str
    novelty_score: float
    difficulty: float
    potential_impact: float
    status: str = "pending"
    attempts: int = 0
    best_result: float = 0
    created: datetime = field(default_factory=datetime.now)
    completed: datetime | None = None


@dataclass
class EvolutionRecord:
    """进化记录"""
    id: str
    goal_id: str
    action: str
    before_state: dict
    after_state: dict
    improvement: float
    novel_discovery: bool
    lessons: list[str]
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Innovation:
    """创新发现"""
    id: str
    concept: str
    source: str
    description: str
    applicability: float
    tested: bool = False
    success_rate: float = 0
    timestamp: datetime = field(default_factory=datetime.now)


class EternalEvolver:
    """永续进化引擎

    核心机制：
    1. 自主目标生成 - 系统自己决定进化方向
    2. 开放式探索 - 随机突变 + 跨域迁移
    3. 自我评估 - 自动判断进化有效性
    4. 知识积累 - 每次进化经验入库
    5. 永续循环 - 永不停止
    """

    EVOLUTION_DOMAINS = [
        "strategy_creation",
        "risk_management",
        "market_analysis",
        "execution_optimization",
        "data_pipeline",
        "cognitive_architecture",
        "learning_algorithm",
        "portfolio_theory",
        "sentiment_analysis",
        "anomaly_detection",
    ]

    CROSS_DOMAIN_CONCEPTS = [
        {"concept": "natural_selection", "source": "biology", "applicability": 0.9},
        {"concept": "reinforcement_learning", "source": "ai", "applicability": 0.95},
        {"concept": "game_theory", "source": "economics", "applicability": 0.85},
        {"concept": "entropy", "source": "physics", "applicability": 0.7},
        {"concept": "swarm_intelligence", "source": "biology", "applicability": 0.8},
        {"concept": "bayesian_inference", "source": "statistics", "applicability": 0.9},
        {"concept": "chaos_theory", "source": "mathematics", "applicability": 0.75},
        {"concept": "evolutionary_psychology", "source": "psychology", "applicability": 0.65},
        {"concept": "network_theory", "source": "computer_science", "applicability": 0.8},
        {"concept": "quantum_mechanics", "source": "physics", "applicability": 0.3},
    ]

    # 2026-10-16 P3b：突变创新的适用度由突变类型静态决定（原 random.uniform 假度量）
    MUTATION_APPLICABILITY = {
        "参数空间扩展": 0.70,
        "新指标引入": 0.75,
        "策略融合": 0.65,
        "时间框架变换": 0.60,
        "数据源扩展": 0.55,
        "模型架构变异": 0.50,
    }

    # 进化改进度 = 真实系统状态增量的加权和（原四处 random.uniform 假度量）。
    # 每个维度按 _NORMALIZE 归一化到 [0,1]，无真实增量时改进度为 0（诚实的"无改进"）。
    DOMAIN_WEIGHTS = {
        "strategy_creation": {"library_size": 0.35, "risk_covered": 0.15,
                              "passed_strategies": 0.25, "internalized": 0.10,
                              "semantic_memory": 0.05, "discoveries": 0.10},
        "risk_management": {"risk_covered": 0.45, "passed_strategies": 0.20,
                            "library_size": 0.10, "semantic_memory": 0.15,
                            "internalized": 0.05, "discoveries": 0.05},
        "cognitive_architecture": {"semantic_memory": 0.40, "internalized": 0.30,
                                   "passed_strategies": 0.10, "library_size": 0.05,
                                   "risk_covered": 0.05, "discoveries": 0.10},
    }
    DEFAULT_WEIGHTS = {"library_size": 0.25, "risk_covered": 0.15,
                       "passed_strategies": 0.15, "internalized": 0.10,
                       "semantic_memory": 0.10, "archived_goals": 0.15,
                       "discoveries": 0.10}
    _NORMALIZE = {"library_size": 3, "risk_covered": 3, "passed_strategies": 2,
                  "internalized": 2, "semantic_memory": 3, "archived_goals": 3,
                  "discoveries": 3}

    def __init__(self):
        self.goals: list[EvolutionGoal] = []
        self.records: list[EvolutionRecord] = []
        self.innovations: list[Innovation] = []
        self.cycle_count = 0
        self.total_improvement = 0.0
        self.discoveries_count = 0
        self._last_system_state: dict | None = None  # 上一周期末的真实系统状态（跨周期增长度量）
        self._load()

    def eternal_cycle(self) -> dict:
        """永续进化循环 - 永不停止"""
        self.cycle_count += 1
        logger.info(f"===== 永续进化 第 {self.cycle_count} 轮 =====")

        results = {
            "cycle": self.cycle_count,
            "timestamp": datetime.now().isoformat(),
            "actions": [],
        }

        # 1. 自主生成新目标
        if self.cycle_count % 3 == 0 or not self.goals:
            new_goals = self._generate_goals()
            results["actions"].append(f"生成 {len(new_goals)} 个新进化目标")

        # 2. 选择一个目标进行进化
        goal = self._select_goal()
        if goal:
            result = self._evolve_towards_goal(goal)
            results["actions"].append(f"进化目标: {goal.description[:50]} → 改进: {result.get('improvement', 0):.4f}")

        # 3. 随机突变探索
        if self.cycle_count % 5 == 0:
            innovation = self._random_mutation()
            if innovation:
                results["actions"].append(f"突变创新: {innovation.concept}")

        # 4. 跨域知识迁移
        if self.cycle_count % 7 == 0:
            migrated = self._cross_domain_transfer()
            if migrated:
                results["actions"].append(f"跨域迁移: {migrated['concept']} → 交易领域")

        # 5. 自我评估
        assessment = self._self_assess()
        results["assessment"] = assessment

        # 6. 知识巩固
        self._consolidate_knowledge()

        self._save()
        self._log_cycle(results)
        return results

    def _generate_goals(self) -> list[EvolutionGoal]:
        """自主生成进化目标"""
        goals = []

        # 基于历史表现生成目标
        if self.records:
            recent_improvements = [r.improvement for r in self.records[-20:]]
            avg_improvement = np.mean(recent_improvements) if recent_improvements else 0

            if avg_improvement < 0.01:
                goals.append(self._create_goal(
                    "突破当前进化瓶颈", "cognitive_architecture", 0.9, 0.8, 0.9
                ))

        # 随机探索新领域
        unexplored = [d for d in self.EVOLUTION_DOMAINS
                     if not any(g.domain == d and g.status == "completed" for g in self.goals)]
        for domain in unexplored[:2]:
            goals.append(self._create_goal(
                f"探索新领域: {domain}", domain, 0.8, 0.6, 0.7
            ))

        # 基于创新概念生成目标
        for innovation in self.innovations[-3:]:
            if not innovation.tested:
                goals.append(self._create_goal(
                    f"验证创新: {innovation.concept}", "strategy_creation", 0.7, 0.5, 0.6
                ))

        # 确保至少有一个目标
        if not goals:
            goals.append(self._create_goal(
                f"持续优化交易系统 v{self.cycle_count}", "strategy_creation", 0.5, 0.4, 0.5
            ))

        self.goals.extend(goals)
        return goals

    def _create_goal(self, description: str, domain: str,
                    novelty: float, difficulty: float, impact: float) -> EvolutionGoal:
        goal_id = hashlib.md5(f"{description}:{datetime.now().isoformat()}".encode()).hexdigest()[:8]
        return EvolutionGoal(
            id=goal_id, description=description, domain=domain,
            novelty_score=novelty, difficulty=difficulty, potential_impact=impact,
        )

    def _select_goal(self) -> EvolutionGoal | None:
        """智能选择进化目标"""
        pending = [g for g in self.goals if g.status == "pending"]
        if not pending:
            return None

        # 多因素评分选择
        scored = []
        for goal in pending:
            score = (
                goal.potential_impact * 0.35 +
                goal.novelty_score * 0.25 +
                (1 - goal.difficulty) * 0.20 +
                (1 / (goal.attempts + 1)) * 0.20
            )
            scored.append((goal, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]

    def _evolve_towards_goal(self, goal: EvolutionGoal) -> dict:
        """朝着目标进化

        2026-10-16 P3b：improvement 由真实系统状态增量计算（_measure_improvement），
        四个 _evolve_* 方法各自执行真实动作（参数入库/风控审计修复/记忆巩固/目标治理），
        不再返回 random.uniform 假度量。
        """
        goal.attempts += 1
        goal.status = "in_progress"

        before_state = self._capture_state()
        before_system = self._system_state()

        # 根据领域选择进化策略（真实动作）
        action = {
            "strategy_creation": self._evolve_strategy,
            "risk_management": self._evolve_risk,
            "cognitive_architecture": self._evolve_cognition,
        }.get(goal.domain, self._evolve_generic)
        action(goal)

        after_system = self._system_state()
        improvement = self._measure_improvement(before_system, after_system, goal.domain)

        after_state = self._capture_state()

        record = EvolutionRecord(
            id=hashlib.md5(f"{goal.id}:{self.cycle_count}".encode()).hexdigest()[:8],
            goal_id=goal.id, action=f"evolve_{goal.domain}",
            before_state=before_state, after_state=after_state,
            improvement=improvement,
            novel_discovery=improvement > 0.05,
            lessons=[f"{goal.domain} 进化改进 {improvement:.4f}"],
        )
        self.records.append(record)
        self.total_improvement += improvement

        if improvement > goal.best_result:
            goal.best_result = improvement

        if improvement > 0.03 or goal.attempts >= 5:
            goal.status = "completed"
            goal.completed = datetime.now()
        else:
            goal.status = "pending"

        return {"improvement": improvement, "goal": goal.description}

    def _evolve_strategy(self, goal: EvolutionGoal):
        """策略创建进化：把已发现参数真实并入策略库

        真实动作 = LearningEngine.integrate_params()（本地文件写入，无网络）。
        改进度由 _measure_improvement 按策略库真实增量计算。
        """
        try:
            from strategy.learning_engine import LearningEngine
            added = LearningEngine().integrate_params()
            logger.info(f"策略进化[{goal.description[:30]}]: 参数入库新增 {added} 组")
        except Exception as e:
            logger.warning(f"策略进化动作失败: {e}")

    def _evolve_risk(self, goal: EvolutionGoal):
        """风控进化：审计策略库，为缺失止损/止盈的条目补默认风控参数

        真实动作 = 本地审计 + 修复写回（无网络）。
        """
        if not STRATEGY_LIB.exists():
            return
        try:
            lib = json.loads(STRATEGY_LIB.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"风控审计读取策略库失败: {e}")
            return
        changed = 0
        for s in lib.get("strategies", []):
            if s.get("stop_loss") is None:
                s["stop_loss"] = DEFAULT_STOP_LOSS
                changed += 1
            if s.get("take_profit") is None:
                s["take_profit"] = DEFAULT_TAKE_PROFIT
                changed += 1
        if changed:
            lib["last_risk_audit"] = datetime.now().isoformat()
            STRATEGY_LIB.write_text(json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"风控进化: 修复 {changed} 个缺失风控参数的策略条目")

    def _evolve_cognition(self, goal: EvolutionGoal):
        """认知架构进化：记忆巩固（情景记忆 → 语义记忆）

        真实动作 = MemorySystem.consolidate()（本地文件写入，无网络）。
        """
        try:
            from agi.memory_system import MemorySystem
            MemorySystem().consolidate()
        except Exception as e:
            logger.warning(f"认知进化动作失败: {e}")

    def _evolve_generic(self, goal: EvolutionGoal):
        """通用进化：目标去重 + 归档已完成目标

        真实动作 = 本地目标治理（去重/归档写回，无网络）。
        """
        seen = set()
        deduped = []
        for g in self.goals:
            if g.status == "pending" and g.description in seen:
                continue
            seen.add(g.description)
            deduped.append(g)
        removed = len(self.goals) - len(deduped)
        self.goals = deduped

        completed = [g for g in self.goals if g.status == "completed"]
        if completed:
            try:
                archive = (json.loads(GOAL_ARCHIVE.read_text(encoding="utf-8"))
                           if GOAL_ARCHIVE.exists() else {"goals": []})
                archived_ids = {g.get("id") for g in archive.get("goals", [])}
                new_entries = [
                    {"id": g.id, "description": g.description, "domain": g.domain,
                     "best_result": g.best_result,
                     "completed": g.completed.isoformat() if g.completed else None}
                    for g in completed if g.id not in archived_ids
                ]
                if new_entries:
                    archive["goals"].extend(new_entries)
                    GOAL_ARCHIVE.write_text(
                        json.dumps(archive, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                logger.warning(f"目标归档失败: {e}")
        if removed:
            logger.info(f"通用进化: 清理 {removed} 个重复目标")

    # ---------- 真实系统状态度量（2026-10-16 P3b，替代 random.uniform 假度量） ----------

    def _read_strategy_library(self) -> dict:
        if not STRATEGY_LIB.exists():
            return {"strategies": []}
        try:
            return json.loads(STRATEGY_LIB.read_text(encoding="utf-8"))
        except Exception:
            return {"strategies": []}

    def _count_internalized(self) -> int:
        if not ITERATIONS_DIR.exists():
            return 0
        return len(list(ITERATIONS_DIR.glob("internalized_*.json")))

    def _count_semantic(self) -> int:
        if not SEMANTIC_FILE.exists():
            return 0
        try:
            return int(json.loads(SEMANTIC_FILE.read_text(encoding="utf-8")).get("semantic_count", 0))
        except Exception:
            return 0

    def _count_archived_goals(self) -> int:
        if not GOAL_ARCHIVE.exists():
            return 0
        try:
            return len(json.loads(GOAL_ARCHIVE.read_text(encoding="utf-8")).get("goals", []))
        except Exception:
            return 0

    def _system_state(self) -> dict:
        """真实系统状态快照——全部指标文件可查，非随机数"""
        lib = self._read_strategy_library()
        strategies = lib.get("strategies", [])
        return {
            "library_size": len(strategies),
            "risk_covered": sum(1 for s in strategies
                                if s.get("stop_loss") is not None and s.get("take_profit") is not None),
            "passed_strategies": sum(1 for s in strategies if s.get("backtest_passed") is True),
            "internalized": self._count_internalized(),
            "semantic_memory": self._count_semantic(),
            "archived_goals": self._count_archived_goals(),
            "discoveries": self.discoveries_count,
        }

    def _measure_improvement(self, before: dict, after: dict, domain: str) -> float:
        """由真实系统状态增量计算改进度

        每个维度增量按 _NORMALIZE 归一化到 [0,1] 后按领域权重加权；
        无真实增量（或回退）时该维度不计入——改进度为 0 是诚实的"无改进"。
        """
        weights = self.DOMAIN_WEIGHTS.get(domain, self.DEFAULT_WEIGHTS)
        total = 0.0
        for key, weight in weights.items():
            delta = after.get(key, 0) - before.get(key, 0)
            if delta <= 0:
                continue
            total += weight * min(1.0, delta / self._NORMALIZE.get(key, 3))
        return round(total, 6)

    def _random_mutation(self) -> Innovation | None:
        """随机突变 - 引入全新概念"""
        mutation_types = [
            "参数空间扩展",
            "新指标引入",
            "策略融合",
            "时间框架变换",
            "数据源扩展",
            "模型架构变异",
        ]

        mutation = random.choice(mutation_types)
        innovation = Innovation(
            id=hashlib.md5(f"mutation:{mutation}:{self.cycle_count}".encode()).hexdigest()[:8],
            concept=f"突变: {mutation}",
            source="random_mutation",
            description=f"随机引入 {mutation} 概念",
            applicability=self.MUTATION_APPLICABILITY.get(mutation, 0.5),
        )
        self.innovations.append(innovation)
        self.discoveries_count += 1
        logger.info(f"🧬 突变创新: {mutation}")
        return innovation

    def _cross_domain_transfer(self) -> dict | None:
        """跨域知识迁移"""
        if not self.CROSS_DOMAIN_CONCEPTS:
            return None

        concept = random.choice(self.CROSS_DOMAIN_CONCEPTS)
        innovation = Innovation(
            id=hashlib.md5(f"transfer:{concept['concept']}:{self.cycle_count}".encode()).hexdigest()[:8],
            concept=f"跨域: {concept['concept']}",
            source=concept['source'],
            description=f"将 {concept['source']} 领域的 {concept['concept']} 迁移到交易",
            applicability=concept['applicability'],
        )
        self.innovations.append(innovation)
        self.discoveries_count += 1
        logger.info(f"🔀 跨域迁移: {concept['concept']} ({concept['source']} → 交易)")
        return {"concept": concept['concept'], "source": concept['source']}

    def _self_assess(self) -> dict:
        """自我评估"""
        recent_records = self.records[-20:]
        if not recent_records:
            return {"status": "initializing", "score": 0}

        avg_improvement = np.mean([r.improvement for r in recent_records])
        novel_discoveries = sum(1 for r in recent_records if r.novel_discovery)
        trend = "improving" if avg_improvement > 0.01 else ("declining" if avg_improvement < 0 else "stable")

        # 2026-10-16 P3b：附加上一周期以来的真实系统状态增长（跨周期口径）
        system_growth = {}
        if self._last_system_state:
            current = self._system_state()
            system_growth = {k: current[k] - self._last_system_state.get(k, 0)
                             for k in current}

        return {
            "status": trend,
            "avg_improvement": round(avg_improvement, 4),
            "novel_discoveries": novel_discoveries,
            "total_improvement": round(self.total_improvement, 4),
            "system_growth": system_growth,
            "recommendation": (
                "进化势头良好，继续探索" if trend == "improving"
                else "建议增加突变率，引入更多创新" if trend == "declining"
                else "保持当前节奏，尝试跨域迁移"
            ),
        }

    def _capture_state(self) -> dict:
        """捕获当前状态"""
        return {
            "cycle": self.cycle_count,
            "total_goals": len(self.goals),
            "completed_goals": sum(1 for g in self.goals if g.status == "completed"),
            "innovations": len(self.innovations),
            "total_improvement": self.total_improvement,
        }

    def _consolidate_knowledge(self):
        """知识巩固"""
        if self.cycle_count % 10 == 0:
            completed = [g for g in self.goals if g.status == "completed"]
            logger.info(f"知识巩固: {len(completed)} 个已完成目标, {self.discoveries_count} 个创新发现")

    def get_evolution_summary(self) -> dict:
        """获取进化摘要"""
        return {
            "total_cycles": self.cycle_count,
            "total_goals": len(self.goals),
            "completed_goals": sum(1 for g in self.goals if g.status == "completed"),
            "in_progress": sum(1 for g in self.goals if g.status == "in_progress"),
            "total_improvement": round(self.total_improvement, 4),
            "discoveries": self.discoveries_count,
            "innovations": len(self.innovations),
            "recent_goals": [
                {"description": g.description[:60], "status": g.status, "improvement": g.best_result}
                for g in self.goals[-5:]
            ],
            "assessment": self._self_assess(),
        }

    def _save(self):
        data = {
            "cycle_count": self.cycle_count,
            "total_goals": len(self.goals),
            "total_improvement": self.total_improvement,
            "discoveries": self.discoveries_count,
            "last_updated": datetime.now().isoformat(),
            # 周期末真实系统状态，作为下一周期 _self_assess 跨周期增长的基线
            "last_system_state": self._system_state(),
        }
        (MEMORY / "eternal_evolver.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _load(self):
        ef = MEMORY / "eternal_evolver.json"
        if ef.exists():
            try:
                data = json.loads(ef.read_text(encoding="utf-8"))
                self.cycle_count = data.get("cycle_count", 0)
                self.total_improvement = data.get("total_improvement", 0)
                self.discoveries_count = data.get("discoveries", 0)
                self._last_system_state = data.get("last_system_state")
            except Exception:
                pass

    def _log_cycle(self, results: dict):
        """记录进化周期"""
        with open(ETERNAL_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(results, ensure_ascii=False) + "\n")

    def get_status(self) -> dict:
        return self.get_evolution_summary()
