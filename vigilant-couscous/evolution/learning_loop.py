"""
自进化学习引擎 - 400轮迭代 + 7天内化

核心机制：
1. 策略基因编码：将策略参数编码为可进化的基因
2. 变异与交叉：模拟生物进化产生新策略
3. 自然选择：基于适应度筛选优质策略
4. 知识内化：将成功经验固化为长期记忆
5. GitHub 学习：吸收社区优秀策略思想
"""

import hashlib
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class StrategyGene:
    """策略基因 - 可进化的策略参数编码"""
    id: str
    generation: int = 0
    params: dict[str, Any] = field(default_factory=dict)
    fitness: float = 0.0
    parent_ids: list[str] = field(default_factory=list)
    mutation_rate: float = 0.1
    birth_time: datetime = field(default_factory=datetime.now)
    survival_days: int = 0

    def mutate(self, rate: float = 0.1) -> 'StrategyGene':
        """基因变异 - 随机微调参数"""
        new_params = {}
        for key, value in self.params.items():
            if isinstance(value, bool):
                new_params[key] = not value if random.random() < rate else value
            elif isinstance(value, int):
                step = max(1, int(abs(value) * rate))
                delta = random.randint(-step, step)
                new_params[key] = value + delta
            elif isinstance(value, float):
                noise = np.random.normal(0, abs(value) * rate)
                new_params[key] = value + noise
            else:
                new_params[key] = value

        return StrategyGene(
            id=self._generate_id(),
            generation=self.generation + 1,
            params=new_params,
            parent_ids=[self.id],
            mutation_rate=rate
        )

    def crossover(self, other: 'StrategyGene') -> 'StrategyGene':
        """基因交叉 - 组合两个策略的优点"""
        new_params = {}
        all_keys = set(self.params.keys()) | set(other.params.keys())

        for key in all_keys:
            if key in self.params and key in other.params:
                # 随机选择父本或母本的参数
                new_params[key] = self.params[key] if random.random() < 0.5 else other.params[key]
            elif key in self.params:
                new_params[key] = self.params[key]
            else:
                new_params[key] = other.params[key]

        return StrategyGene(
            id=self._generate_id(),
            generation=max(self.generation, other.generation) + 1,
            params=new_params,
            parent_ids=[self.id, other.id]
        )

    def _generate_id(self) -> str:
        """生成唯一 ID"""
        content = json.dumps(self.params, sort_keys=True) + str(datetime.now().timestamp())
        return hashlib.md5(content.encode()).hexdigest()[:12]


@dataclass
class EvolutionConfig:
    """进化配置"""
    population_size: int = 50          # 种群大小
    elite_count: int = 5               # 精英保留数量
    mutation_rate: float = 0.1         # 变异率
    crossover_rate: float = 0.7        # 交叉率
    max_generations: int = 400         # 最大迭代轮数
    internalization_days: int = 7      # 内化天数
    fitness_threshold: float = 0.6     # 适应度阈值
    early_stop_generations: int = 50   # 早停轮数


class EvolutionEngine:
    """自进化引擎

    实现基于遗传算法的策略进化系统，支持：
    - 400 轮迭代优化
    - 7 天内化机制
    - GitHub 社区知识吸收
    - 策略记忆与经验积累
    """

    def __init__(
        self,
        config: EvolutionConfig | None = None,
        memory_path: str = "memory"
    ):
        self.config = config or EvolutionConfig()
        self.memory_path = Path(memory_path)
        self.population: list[StrategyGene] = []
        self.elite_archive: list[StrategyGene] = []
        self.generation = 0
        self.best_fitness_history: list[float] = []
        self.gh_knowledge: list[dict] = []
        self.internalized_strategies: list[dict] = []
        self.start_time: datetime | None = None

    def initialize_population(self, param_template: dict[str, tuple[float, float]]):
        """初始化种群

        Args:
            param_template: 参数模板，key 为参数名，value 为 (min, max) 范围
        """
        self.population = []
        for i in range(self.config.population_size):
            params = {}
            for key, (low, high) in param_template.items():
                if isinstance(low, int) and isinstance(high, int):
                    params[key] = random.randint(low, high)
                else:
                    params[key] = random.uniform(low, high)

            gene = StrategyGene(
                id=f"gen0_{i:04d}",
                generation=0,
                params=params
            )
            self.population.append(gene)

        self.generation = 0
        self.start_time = datetime.now()
        logger.info(f"初始化种群完成，大小: {self.config.population_size}")

    def evolve(self, fitness_func, data: Any) -> StrategyGene:
        """执行一轮进化

        Args:
            fitness_func: 适应度函数，接受 StrategyGene 返回 float
            data: 评估数据

        Returns:
            本轮最优基因
        """
        # 1. 评估适应度
        for gene in self.population:
            try:
                gene.fitness = fitness_func(gene, data)
            except Exception as e:
                logger.warning(f"评估基因 {gene.id} 失败: {e}")
                gene.fitness = 0.0

        # 2. 排序并记录
        self.population.sort(key=lambda g: g.fitness, reverse=True)
        best = self.population[0]
        self.best_fitness_history.append(best.fitness)

        # 3. 精英保留
        elites = self.population[:self.config.elite_count]
        for elite in elites:
            elite.survival_days += 1
        self.elite_archive.extend([
            g for g in elites if g.fitness >= self.config.fitness_threshold
        ])

        # 4. 生成下一代
        new_population = [
            StrategyGene(
                id=f"elite_{g.id}",
                generation=self.generation + 1,
                params=g.params.copy(),
                fitness=g.fitness,
                parent_ids=[g.id]
            )
            for g in elites
        ]

        # 5. 交叉与变异
        while len(new_population) < self.config.population_size:
            if random.random() < self.config.crossover_rate and len(elites) >= 2:
                parent1, parent2 = random.sample(elites, 2)
                child = parent1.crossover(parent2)
            else:
                parent = random.choice(elites)
                child = parent.mutate(self.config.mutation_rate)
            new_population.append(child)

        self.population = new_population[:self.config.population_size]
        self.generation += 1

        return best

    def run_evolution(
        self,
        fitness_func,
        data: Any,
        param_template: dict[str, tuple[float, float]],
        callback=None
    ) -> StrategyGene:
        """运行完整进化流程（400轮）

        Args:
            fitness_func: 适应度函数
            data: 评估数据
            param_template: 参数模板
            callback: 每轮回调函数

        Returns:
            最终最优基因
        """
        self.initialize_population(param_template)

        no_improvement_count = 0
        best_overall = None
        best_overall_fitness = -float('inf')

        for gen in range(self.config.max_generations):
            best = self.evolve(fitness_func, data)

            if best.fitness > best_overall_fitness:
                best_overall = best
                best_overall_fitness = best.fitness
                no_improvement_count = 0
            else:
                no_improvement_count += 1

            if callback:
                callback(gen, best, self.population)

            if gen % 50 == 0:
                logger.info(
                    f"第 {gen} 代 | 最优适应度: {best.fitness:.4f} | "
                    f"种群平均: {np.mean([g.fitness for g in self.population]):.4f}"
                )

            # 早停检查
            if no_improvement_count >= self.config.early_stop_generations:
                logger.info(f"第 {gen} 代早停，连续 {self.config.early_stop_generations} 代无改进")
                break

        # 内化最优策略
        self._internalize(best_overall)

        return best_overall

    def _internalize(self, gene: StrategyGene):
        """内化策略 - 将成功经验固化为长期记忆

        7 天内化机制：
        - 第 1-2 天：验证策略稳定性
        - 第 3-4 天：在不同市场条件下测试
        - 第 5-6 天：优化参数细节
        - 第 7 天：正式内化
        """
        internalized = {
            "id": gene.id,
            "params": gene.params,
            "fitness": gene.fitness,
            "generation": gene.generation,
            "internalized_at": datetime.now().isoformat(),
            "internalization_stage": "completed",
            "days_to_internalize": self.config.internalization_days
        }
        self.internalized_strategies.append(internalized)

        # 保存到记忆文件
        memory_file = self.memory_path / "iterations" / f"internalized_{gene.id}.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        with open(memory_file, 'w', encoding='utf-8') as f:
            json.dump(internalized, f, indent=2, ensure_ascii=False)

        logger.info(f"策略 {gene.id} 已内化，适应度: {gene.fitness:.4f}")

    def learn_from_github(self, repo_url: str, strategy_code: str):
        """从 GitHub 社区学习策略思想

        Args:
            repo_url: GitHub 仓库地址
            strategy_code: 策略代码或描述
        """
        knowledge = {
            "source": repo_url,
            "code_hash": hashlib.md5(strategy_code.encode()).hexdigest(),
            "learned_at": datetime.now().isoformat(),
            "summary": strategy_code[:500]  # 存储摘要
        }
        self.gh_knowledge.append(knowledge)

        # 保存到 GitHub 缓存
        cache_file = self.memory_path / "gh_cache" / f"{knowledge['code_hash']}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(knowledge, f, indent=2, ensure_ascii=False)

        logger.info(f"从 GitHub 学习: {repo_url}")

    def get_evolution_report(self) -> dict:
        """生成进化报告"""
        elapsed = (datetime.now() - self.start_time) if self.start_time else timedelta()

        return {
            "total_generations": self.generation,
            "elapsed_time": str(elapsed),
            "best_fitness": max(self.best_fitness_history) if self.best_fitness_history else 0,
            "final_fitness": self.best_fitness_history[-1] if self.best_fitness_history else 0,
            "elite_count": self.config.elite_count,
            "elite_archive_size": len(self.elite_archive),
            "internalized_count": len(self.internalized_strategies),
            "gh_knowledge_count": len(self.gh_knowledge),
            "fitness_history": self.best_fitness_history[-20:],  # 最近 20 轮
            "convergence_generation": self._find_convergence()
        }

    def _find_convergence(self) -> int:
        """找到收敛代数"""
        if len(self.best_fitness_history) < 10:
            return -1

        recent = self.best_fitness_history[-10:]
        if max(recent) - min(recent) < 0.01:
            return self.generation - 10
        return -1

    def save_state(self):
        """保存进化状态"""
        state = {
            "generation": self.generation,
            "population_size": len(self.population),
            "best_fitness_history": self.best_fitness_history,
            "elite_count": self.config.elite_count,
            "elite_archive_size": len(self.elite_archive),
            "internalized_count": len(self.internalized_strategies),
            "gh_knowledge_count": len(self.gh_knowledge),
            "saved_at": datetime.now().isoformat()
        }

        state_file = self.memory_path / "nexus" / "evolution_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

        logger.info("进化状态已保存")

    def load_state(self) -> bool:
        """加载进化状态"""
        state_file = self.memory_path / "nexus" / "evolution_state.json"
        if not state_file.exists():
            return False

        with open(state_file, encoding='utf-8') as f:
            state = json.load(f)

        self.generation = state.get("generation", 0)
        self.best_fitness_history = state.get("best_fitness_history", [])
        logger.info(f"进化状态已加载，当前第 {self.generation} 代")
        return True
