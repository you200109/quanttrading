"""
AGI 分布式协同编排器 - 多实例协同决策

实现多 AGI 实例的协同工作：
- 任务分配：根据专长自动分配任务
- 共识机制：多实例投票决策
- 知识同步：实例间实时知识共享
- 负载均衡：动态调整计算资源
- 容错恢复：实例故障自动接管
"""

import hashlib
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
class AGIInstance:
    id: str
    name: str
    specialization: str
    capability_score: float
    current_load: float
    last_heartbeat: datetime
    knowledge_version: int
    status: str = "active"


@dataclass
class ConsensusResult:
    topic: str
    votes: dict[str, str]
    winner: str
    confidence: float
    agreement_ratio: float
    dissenting_opinions: list[str]
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Task:
    id: str
    type: str
    priority: int
    required_capability: str
    payload: dict[str, Any]
    assigned_to: str | None = None
    status: str = "pending"
    result: Any | None = None
    created: datetime = field(default_factory=datetime.now)
    completed: datetime | None = None


class DistributedOrchestrator:
    """分布式协同编排器

    核心能力：
    1. 任务分配 - 根据实例专长和负载智能分配
    2. 共识决策 - 多实例投票，少数服从多数
    3. 知识同步 - 实例间实时共享学习成果
    4. 负载均衡 - 动态调整任务分配
    5. 故障恢复 - 检测并接管故障实例任务
    """

    HEARTBEAT_TIMEOUT_SECONDS = 30
    MAX_LOAD_PER_INSTANCE = 5

    def __init__(self):
        self.instances: dict[str, AGIInstance] = {}
        self.tasks: dict[str, Task] = []
        self.consensus_history: list[ConsensusResult] = []
        self.shared_knowledge: dict[str, Any] = {}
        self.knowledge_version = 0
        self._init_default_instances()

    def _init_default_instances(self):
        """初始化默认 AGI 实例"""
        specs = [
            ("market_analyst", "市场分析", 0.9),
            ("risk_controller", "风险控制", 0.85),
            ("strategy_engine", "策略引擎", 0.88),
            ("data_collector", "数据采集", 0.75),
            ("execution_agent", "交易执行", 0.8),
        ]
        for name, spec, score in specs:
            self.register_instance(name, spec, score)

    def register_instance(self, name: str, specialization: str,
                         capability_score: float) -> str:
        """注册新实例"""
        instance_id = hashlib.md5(f"{name}:{datetime.now().isoformat()}".encode()).hexdigest()[:8]
        self.instances[instance_id] = AGIInstance(
            id=instance_id, name=name, specialization=specialization,
            capability_score=capability_score, current_load=0,
            last_heartbeat=datetime.now(), knowledge_version=self.knowledge_version,
        )
        logger.info(f"实例注册: {name} ({specialization})")
        return instance_id

    def submit_task(self, task_type: str, priority: int,
                   required_capability: str, payload: dict) -> str:
        """提交任务"""
        task_id = hashlib.md5(f"{task_type}:{datetime.now().isoformat()}".encode()).hexdigest()[:8]
        task = Task(
            id=task_id, type=task_type, priority=priority,
            required_capability=required_capability, payload=payload,
        )
        self.tasks.append(task)
        self._assign_task(task)
        return task_id

    def _assign_task(self, task: Task):
        """分配任务到最佳实例"""
        candidates = [
            i for i in self.instances.values()
            if i.specialization == task.required_capability
            and i.status == "active"
            and i.current_load < self.MAX_LOAD_PER_INSTANCE
        ]

        if not candidates:
            candidates = [
                i for i in self.instances.values()
                if i.status == "active"
                and i.current_load < self.MAX_LOAD_PER_INSTANCE
            ]

        if not candidates:
            task.status = "queued"
            return

        best = max(candidates, key=lambda i: i.capability_score / (i.current_load + 1))
        task.assigned_to = best.id
        task.status = "assigned"
        best.current_load += 1

    def reach_consensus(self, topic: str, proposals: dict[str, str]) -> ConsensusResult:
        """多实例共识决策"""
        active_instances = [i for i in self.instances.values() if i.status == "active"]
        if not active_instances:
            return ConsensusResult(
                topic=topic, votes={}, winner="hold",
                confidence=0, agreement_ratio=0, dissenting_opinions=["无活跃实例"],
            )

        votes = {}
        for instance in active_instances:
            vote = self._simulate_instance_vote(instance, topic, proposals)
            votes[instance.id] = vote

        vote_counts = defaultdict(int)
        for vote in votes.values():
            vote_counts[vote] += 1

        winner = max(vote_counts, key=vote_counts.get)
        agreement_ratio = vote_counts[winner] / len(votes)
        confidence = agreement_ratio * 0.7 + 0.3 * (1 if agreement_ratio > 0.6 else 0.5)

        dissenting = [
            f"{i.name}: {votes.get(i.id, 'unknown')}" for i in active_instances
            if votes.get(i.id) != winner
        ]

        result = ConsensusResult(
            topic=topic, votes=votes, winner=winner,
            confidence=confidence, agreement_ratio=agreement_ratio,
            dissenting_opinions=dissenting,
        )
        self.consensus_history.append(result)
        logger.info(f"共识达成: {topic} → {winner} (同意率: {agreement_ratio:.0%})")
        return result

    def sync_knowledge(self):
        """同步知识到所有实例"""
        self.knowledge_version += 1
        for instance in self.instances.values():
            if instance.status == "active":
                instance.knowledge_version = self.knowledge_version
        logger.info(f"知识同步完成: 版本 {self.knowledge_version}")

    def share_learning(self, source_instance: str, knowledge: dict):
        """共享学习成果"""
        knowledge_key = f"{source_instance}:{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.shared_knowledge[knowledge_key] = {
            "source": source_instance,
            "knowledge": knowledge,
            "timestamp": datetime.now().isoformat(),
            "version": self.knowledge_version,
        }
        self.sync_knowledge()

    def check_health(self) -> dict:
        """健康检查"""
        now = datetime.now()
        issues = []

        for instance in self.instances.values():
            if (now - instance.last_heartbeat).total_seconds() > self.HEARTBEAT_TIMEOUT_SECONDS:
                instance.status = "offline"
                issues.append(f"{instance.name} 离线")
                self._reassign_tasks(instance.id)

        overloaded = [i for i in self.instances.values()
                     if i.current_load >= self.MAX_LOAD_PER_INSTANCE]
        if overloaded:
            issues.append(f"{len(overloaded)} 个实例过载")

        return {
            "total_instances": len(self.instances),
            "active": sum(1 for i in self.instances.values() if i.status == "active"),
            "offline": sum(1 for i in self.instances.values() if i.status == "offline"),
            "issues": issues,
            "pending_tasks": sum(1 for t in self.tasks if t.status in ("pending", "queued")),
        }

    def _reassign_tasks(self, failed_instance_id: str):
        """重新分配故障实例的任务"""
        for task in self.tasks:
            if task.assigned_to == failed_instance_id and task.status == "assigned":
                task.assigned_to = None
                task.status = "pending"
                self._assign_task(task)

    def _simulate_instance_vote(self, instance: AGIInstance, topic: str,
                               proposals: dict[str, str]) -> str:
        """模拟实例投票"""
        if instance.specialization == "风险控制" and "risk" in topic.lower():
            return proposals.get("conservative", "hold")
        if instance.specialization == "市场分析" and "trend" in topic.lower():
            return proposals.get("aggressive", "hold")
        return max(proposals.values(), key=lambda v: hash(v + instance.id) % 100) if proposals else "hold"

    def get_cluster_status(self) -> dict:
        """获取集群状态"""
        return {
            "instances": [
                {"name": i.name, "specialization": i.specialization,
                 "load": i.current_load, "status": i.status}
                for i in self.instances.values()
            ],
            "total_tasks": len(self.tasks),
            "completed_tasks": sum(1 for t in self.tasks if t.status == "completed"),
            "knowledge_version": self.knowledge_version,
            "shared_knowledge_count": len(self.shared_knowledge),
            "consensus_count": len(self.consensus_history),
        }

    def _save(self):
        data = {
            "instances": len(self.instances),
            "knowledge_version": self.knowledge_version,
            "total_tasks": len(self.tasks),
            "last_updated": datetime.now().isoformat(),
        }
        (MEMORY / "distributed_orchestrator.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False))
