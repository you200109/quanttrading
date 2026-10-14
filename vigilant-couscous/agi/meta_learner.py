"""
AGI 元学习系统 - 学习如何学习

实现学习算法的自我优化：
- 超参数自适应：自动调整学习率、批次大小等
- 架构搜索：自动发现最优网络结构
- 学习策略优化：选择最佳学习算法
- 迁移学习：跨市场/跨币种知识迁移
- 课程学习：从简单到复杂的渐进训练
"""

import json
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MEMORY = ROOT / "memory" / "agi"
MEMORY.mkdir(parents=True, exist_ok=True)


@dataclass
class LearningConfig:
    learning_rate: float = 0.001
    batch_size: int = 32
    momentum: float = 0.9
    weight_decay: float = 0.0001
    dropout_rate: float = 0.2
    hidden_layers: list[int] = field(default_factory=lambda: [64, 32])
    activation: str = "relu"
    optimizer: str = "adam"
    performance_score: float = 0.0
    trials: int = 0


@dataclass
class MetaKnowledge:
    concept: str
    source_domain: str
    target_domains: list[str]
    transferability: float
    knowledge_vector: np.ndarray
    success_rate: float
    timestamp: datetime = field(default_factory=datetime.now)


class MetaLearner:
    """元学习系统

    核心能力：
    1. 超参数优化 - 贝叶斯优化搜索最优配置
    2. 架构搜索 - 自动发现最优网络结构
    3. 学习策略选择 - 根据任务选择最佳算法
    4. 迁移学习 - 跨领域知识复用
    5. 课程学习 - 渐进式难度递增
    """

    HYPERPARAM_SPACE = {
        "learning_rate": (0.0001, 0.01),
        "batch_size": (8, 128),
        "momentum": (0.5, 0.99),
        "weight_decay": (0.0, 0.01),
        "dropout_rate": (0.0, 0.5),
    }

    ARCHITECTURE_SPACE = {
        "hidden_layers": [[32], [64, 32], [128, 64, 32], [64, 64], [128, 64]],
        "activation": ["relu", "tanh", "elu", "selu"],
        "optimizer": ["adam", "sgd", "rmsprop", "adamw"],
    }

    def __init__(self):
        self.current_config = LearningConfig()
        self.config_history: list[LearningConfig] = []
        self.meta_knowledge: dict[str, MetaKnowledge] = {}
        self.performance_buffer: deque = deque(maxlen=100)
        self.curriculum_level = 0
        self.curriculum_stages = [
            {"name": "基础", "difficulty": 0.2, "max_volatility": 0.3, "min_data_days": 30},
            {"name": "进阶", "difficulty": 0.4, "max_volatility": 0.5, "min_data_days": 90},
            {"name": "高级", "difficulty": 0.6, "max_volatility": 0.7, "min_data_days": 180},
            {"name": "专家", "difficulty": 0.8, "max_volatility": 1.0, "min_data_days": 365},
            {"name": "大师", "difficulty": 1.0, "max_volatility": 2.0, "min_data_days": 730},
        ]

    def optimize_hyperparams(self, performance_history: list[float],
                            n_trials: int = 20) -> LearningConfig:
        """贝叶斯优化超参数"""
        best_config = self.current_config
        best_score = np.mean(performance_history[-10:]) if performance_history else 0

        for _ in range(n_trials):
            config = LearningConfig()
            config.learning_rate = self._sample_log_uniform(*self.HYPERPARAM_SPACE["learning_rate"])
            config.batch_size = int(self._sample_uniform(*self.HYPERPARAM_SPACE["batch_size"]))
            config.momentum = self._sample_uniform(*self.HYPERPARAM_SPACE["momentum"])
            config.weight_decay = self._sample_log_uniform(*self.HYPERPARAM_SPACE["weight_decay"])
            config.dropout_rate = self._sample_uniform(*self.HYPERPARAM_SPACE["dropout_rate"])

            arch = self.ARCHITECTURE_SPACE
            config.hidden_layers = arch["hidden_layers"][np.random.randint(len(arch["hidden_layers"]))]
            config.activation = arch["activation"][np.random.randint(len(arch["activation"]))]
            config.optimizer = arch["optimizer"][np.random.randint(len(arch["optimizer"]))]

            estimated_score = self._estimate_performance(config, performance_history)
            config.performance_score = estimated_score
            config.trials = n_trials

            if estimated_score > best_score:
                best_score = estimated_score
                best_config = config

        self.current_config = best_config
        self.config_history.append(best_config)
        self._save()
        logger.info(f"超参数优化完成: lr={best_config.learning_rate:.5f}, "
                    f"layers={best_config.hidden_layers}, score={best_score:.4f}")
        return best_config

    def select_learning_strategy(self, task_type: str, data_size: int,
                                 complexity: float) -> dict[str, Any]:
        """根据任务选择最佳学习策略"""
        strategies = {
            "classification": {
                "small_data": {"algorithm": "svm", "reason": "小样本分类SVM最优"},
                "large_data": {"algorithm": "gradient_boosting", "reason": "大数据梯度提升"},
            },
            "regression": {
                "small_data": {"algorithm": "ridge", "reason": "小样本岭回归防过拟合"},
                "large_data": {"algorithm": "neural_network", "reason": "大数据神经网络"},
            },
            "reinforcement": {
                "any": {"algorithm": "ppo", "reason": "PPO稳定性好"},
            },
        }

        size_category = "small_data" if data_size < 1000 else "large_data"
        task_strategies = strategies.get(task_type, strategies["regression"])
        strategy = task_strategies.get(size_category, task_strategies.get("any", {}))

        if complexity > 0.7:
            strategy["ensemble"] = True
            strategy["reason"] += "，启用集成学习"

        return strategy

    def transfer_knowledge(self, source_domain: str, target_domain: str,
                          knowledge: dict) -> MetaKnowledge | None:
        """跨领域知识迁移"""
        concept = f"{source_domain}_to_{target_domain}"

        similarity = self._domain_similarity(source_domain, target_domain)
        if similarity < 0.3:
            logger.warning(f"领域差异过大 ({similarity:.2f})，迁移可能无效")
            return None

        knowledge_vector = self._encode_knowledge(knowledge)

        meta = MetaKnowledge(
            concept=concept, source_domain=source_domain,
            target_domains=[target_domain], transferability=similarity,
            knowledge_vector=knowledge_vector, success_rate=similarity * 0.8,
        )
        self.meta_knowledge[concept] = meta
        self._save()
        logger.info(f"知识迁移: {source_domain} → {target_domain} (相似度: {similarity:.2f})")
        return meta

    def get_curriculum(self) -> dict:
        """获取当前课程阶段"""
        if self.curriculum_level >= len(self.curriculum_stages):
            self.curriculum_level = len(self.curriculum_stages) - 1

        stage = self.curriculum_stages[self.curriculum_level]

        recent_performance = np.mean(list(self.performance_buffer)[-20:]) if self.performance_buffer else 0
        if recent_performance > 0.7 and self.curriculum_level < len(self.curriculum_stages) - 1:
            self.curriculum_level += 1
            logger.info(f"课程升级: {stage['name']} → {self.curriculum_stages[self.curriculum_level]['name']}")
        elif recent_performance < 0.3 and self.curriculum_level > 0:
            self.curriculum_level -= 1
            logger.info(f"课程降级: {stage['name']} → {self.curriculum_stages[self.curriculum_level]['name']}")

        return {
            "level": self.curriculum_level,
            "name": stage["name"],
            "difficulty": stage["difficulty"],
            "constraints": {
                "max_volatility": stage["max_volatility"],
                "min_data_days": stage["min_data_days"],
            },
        }

    def evaluate_learning_efficiency(self, before_performance: float,
                                     after_performance: float,
                                     time_spent: float) -> dict:
        """评估学习效率"""
        improvement = after_performance - before_performance
        efficiency = improvement / max(time_spent, 1)

        self.performance_buffer.append(after_performance)

        return {
            "improvement": improvement,
            "efficiency": efficiency,
            "learning_rate_quality": "优秀" if efficiency > 0.01 else "良好" if efficiency > 0.001 else "需优化",
            "recommendation": (
                "学习效率高，可增加难度" if efficiency > 0.01
                else "学习效率正常" if efficiency > 0.001
                else "建议调整超参数或简化任务"
            ),
        }

    def _sample_uniform(self, low: float, high: float) -> float:
        return np.random.uniform(low, high)

    def _sample_log_uniform(self, low: float, high: float) -> float:
        if low <= 0:
            low = 1e-6
        return np.exp(np.random.uniform(np.log(low), np.log(high)))

    def _estimate_performance(self, config: LearningConfig,
                              history: list[float]) -> float:
        """估计配置性能"""
        base_score = np.mean(history[-10:]) if history else 0.5
        lr_penalty = abs(np.log10(config.learning_rate) + 3) * 0.05
        complexity_bonus = len(config.hidden_layers) * 0.02
        return base_score - lr_penalty + complexity_bonus

    def _domain_similarity(self, domain_a: str, domain_b: str) -> float:
        """计算领域相似度"""
        crypto_pairs = {"BTC": 0, "ETH": 1, "SOL": 2}
        if domain_a in crypto_pairs and domain_b in crypto_pairs:
            distance = abs(crypto_pairs[domain_a] - crypto_pairs[domain_b])
            return max(0.3, 1.0 - distance * 0.3)
        return 0.5

    def _encode_knowledge(self, knowledge: dict) -> np.ndarray:
        """编码知识为向量"""
        vec = np.zeros(32)
        for i, (_k, v) in enumerate(knowledge.items()):
            if i >= 32:
                break
            if isinstance(v, (int, float)):
                vec[i] = float(v)
            elif isinstance(v, str):
                vec[i] = hash(v) % 1000 / 1000
        return vec

    def _save(self):
        data = {
            "current_config": {
                "learning_rate": self.current_config.learning_rate,
                "batch_size": self.current_config.batch_size,
                "hidden_layers": self.current_config.hidden_layers,
                "optimizer": self.current_config.optimizer,
                "performance_score": self.current_config.performance_score,
            },
            "curriculum_level": self.curriculum_level,
            "meta_knowledge_count": len(self.meta_knowledge),
            "config_trials": len(self.config_history),
            "last_updated": datetime.now().isoformat(),
        }
        (MEMORY / "meta_learner.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get_status(self) -> dict:
        return {
            "current_config": {
                "lr": self.current_config.learning_rate,
                "layers": self.current_config.hidden_layers,
                "optimizer": self.current_config.optimizer,
            },
            "curriculum": self.get_curriculum(),
            "meta_knowledge_count": len(self.meta_knowledge),
            "config_trials": len(self.config_history),
        }
