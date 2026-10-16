"""
AGI 对抗训练系统 - 多策略博弈进化

实现策略间的竞争与协作：
- 对抗博弈：多策略零和竞争，优胜劣汰
- 协作进化：策略间知识共享和融合
- 自我对弈：同一策略的不同版本对抗
- 红蓝对抗：攻击策略 vs 防御策略
- 锦标赛选择：定期淘汰低效策略
"""

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MEMORY = ROOT / "memory" / "agi"
MEMORY.mkdir(parents=True, exist_ok=True)


@dataclass
class StrategyAgent:
    id: str
    name: str
    category: str
    params: dict[str, float]
    fitness: float = 0.0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    elo_rating: float = 1500.0
    generation: int = 0
    parent_ids: list[str] = field(default_factory=list)
    created: datetime = field(default_factory=datetime.now)


@dataclass
class BattleResult:
    agent_a: str
    agent_b: str
    winner: str
    score_a: float
    score_b: float
    market_condition: str
    timestamp: datetime = field(default_factory=datetime.now)


class AdversarialTraining:
    """对抗训练系统

    核心机制：
    1. 锦标赛 - 定期淘汰赛，保留 Top K
    2. 自我对弈 - 同一策略不同参数版本对抗
    3. 红蓝对抗 - 攻击方 vs 防御方
    4. ELO 评分 - 动态能力评估
    5. 基因融合 - 优秀策略间交叉产生后代
    """

    ELO_K_FACTOR = 32
    TOURNAMENT_SIZE = 4
    POPULATION_LIMIT = 50
    MUTATION_RATE = 0.1

    def __init__(self):
        self.agents: dict[str, StrategyAgent] = {}
        self.battle_history: list[BattleResult] = []
        self.generation = 0
        self._init_default_agents()

    def _init_default_agents(self):
        """初始化默认策略代理"""
        templates = [
            ("trend_follower", "trend", {"sma_fast": 5, "sma_slow": 20, "stop_loss": 0.05}),
            ("mean_reverter", "momentum", {"rsi_period": 14, "rsi_oversold": 30, "rsi_overbought": 70}),
            ("breakout_hunter", "volatility", {"bb_period": 20, "bb_std": 2.0, "stop_loss": 0.04}),
            ("volume_tracker", "volume", {"vol_ma": 20, "vol_multiple": 2.0, "stop_loss": 0.04}),
            ("scalper", "momentum", {"lookback": 5, "threshold": 0.01, "stop_loss": 0.02}),
            ("swing_trader", "trend", {"sma_fast": 10, "sma_slow": 50, "stop_loss": 0.06}),
            ("grid_trader", "volatility", {"grid_size": 0.02, "grid_levels": 5, "stop_loss": 0.08}),
            ("arbitrage_seeker", "statistical", {"corr_threshold": 0.8, "spread_entry": 2.0}),
        ]
        for name, category, params in templates:
            self.add_agent(name, category, params)

    def add_agent(self, name: str, category: str, params: dict[str, float],
                  parent_ids: list[str] = None) -> str:
        """添加新策略代理"""
        agent_id = f"{name}_{self.generation}_{len(self.agents)}"
        self.agents[agent_id] = StrategyAgent(
            id=agent_id, name=name, category=category, params=params,
            generation=self.generation, parent_ids=parent_ids or [],
        )
        return agent_id

    def battle(self, agent_a_id: str, agent_b_id: str,
               market_data: dict) -> BattleResult:
        """两个策略代理对战"""
        agent_a = self.agents[agent_a_id]
        agent_b = self.agents[agent_b_id]

        score_a = self._simulate_performance(agent_a, market_data)
        score_b = self._simulate_performance(agent_b, market_data)

        if score_a > score_b * 1.02:
            winner = agent_a_id
            agent_a.wins += 1
            agent_b.losses += 1
        elif score_b > score_a * 1.02:
            winner = agent_b_id
            agent_b.wins += 1
            agent_a.losses += 1
        else:
            winner = "draw"
            agent_a.draws += 1
            agent_b.draws += 1

        self._update_elo(agent_a, agent_b, winner)

        result = BattleResult(
            agent_a=agent_a_id, agent_b=agent_b_id, winner=winner,
            score_a=score_a, score_b=score_b,
            market_condition=market_data.get("regime", "unknown"),
        )
        self.battle_history.append(result)
        return result

    def run_tournament(self, market_data: dict) -> list[BattleResult]:
        """运行锦标赛"""
        results = []
        agent_ids = list(self.agents.keys())
        random.shuffle(agent_ids)

        for i in range(0, len(agent_ids) - 1, 2):
            result = self.battle(agent_ids[i], agent_ids[i + 1], market_data)
            results.append(result)

        self._eliminate_weakest()
        self._breed_champions()
        self.generation += 1
        self._save()
        return results

    def self_play(self, agent_id: str, market_data: dict, n_variations: int = 5) -> list[BattleResult]:
        """自我对弈 - 同一策略的不同变异版本对抗"""
        original = self.agents[agent_id]
        variations = []
        for i in range(n_variations):
            mutated_params = {}
            for k, v in original.params.items():
                noise = np.random.randn() * v * self.MUTATION_RATE
                mutated_params[k] = max(0.001, v + noise)
            var_id = self.add_agent(f"{original.name}_var{i}", original.category,
                                    mutated_params, parent_ids=[agent_id])
            variations.append(var_id)

        results = []
        for var_id in variations:
            result = self.battle(agent_id, var_id, market_data)
            results.append(result)

        return results

    def red_blue_exercise(self, market_data: dict) -> list[BattleResult]:
        """红蓝对抗 - 攻击策略 vs 防御策略"""
        red_team = [a for a in self.agents.values() if a.category in ("momentum", "volatility")]
        blue_team = [a for a in self.agents.values() if a.category in ("trend", "statistical")]

        if not red_team or not blue_team:
            return []

        results = []
        for red in red_team[:3]:
            for blue in blue_team[:3]:
                result = self.battle(red.id, blue.id, market_data)
                results.append(result)

        return results

    def _simulate_performance(self, agent: StrategyAgent, market_data: dict) -> float:
        """模拟策略表现（K2：指标一律出自 pandas-ta，禁手写公式）"""
        close = market_data.get('close', [])
        if len(close) < 50:
            return 0.0

        returns = np.diff(close[-50:]) / close[-51:-1]
        params = agent.params
        window = np.asarray(close[-50:], dtype=float)
        close_s = pd.Series(window)

        if agent.category == "trend":
            sma_f = int(params.get('sma_fast', 5))
            sma_s = int(params.get('sma_slow', 20))
            sma_f_vals = ta.sma(close_s, length=sma_f)
            sma_s_vals = ta.sma(close_s, length=sma_s)
            if sma_f_vals is None or sma_s_vals is None:
                return 0.0
            start = max(sma_f, sma_s) - 1
            signals = (sma_f_vals.iloc[start:].to_numpy() > sma_s_vals.iloc[start:].to_numpy()).astype(int)
            strategy_returns = signals[:-1] * returns[-len(signals)+1:]

        elif agent.category == "momentum":
            rsi_period = int(params.get('rsi_period', 14))
            os_ = params.get('rsi_oversold', 30)
            ob = params.get('rsi_overbought', 70)
            rsi_series = ta.rsi(close_s, length=rsi_period)
            if rsi_series is None:
                return 0.0
            rsi = rsi_series.to_numpy()[1:]  # 与原 len(deltas)=49 对齐（idx0 为 NaN，不产生信号）
            signals = np.zeros(len(rsi))
            signals[rsi < os_] = 1
            signals[rsi > ob] = -1
            strategy_returns = signals[:-1] * returns[-len(signals)+1:]

        else:
            bb_period = int(params.get('bb_period', 20))
            bb_std = params.get('bb_std', 2.0)
            bb_df = ta.bbands(close_s, length=bb_period, std=bb_std)
            if bb_df is None:
                return 0.0
            upper = bb_df.iloc[bb_period-1:, 2].to_numpy()
            lower = bb_df.iloc[bb_period-1:, 0].to_numpy()
            prices = window[bb_period-1:]
            signals = np.zeros(len(prices))
            signals[prices < lower] = 1
            signals[prices > upper] = -1
            strategy_returns = signals[:-1] * returns[-len(signals)+1:]

        total_return = np.prod(1 + strategy_returns) - 1 if len(strategy_returns) > 0 else 0
        sharpe = np.mean(strategy_returns) / (np.std(strategy_returns) + 1e-8) * np.sqrt(252) if len(strategy_returns) > 1 else 0
        return total_return * 0.5 + max(0, sharpe) * 0.1

    def _update_elo(self, agent_a: StrategyAgent, agent_b: StrategyAgent, winner: str):
        """更新 ELO 评分"""
        expected_a = 1 / (1 + 10 ** ((agent_b.elo_rating - agent_a.elo_rating) / 400))
        expected_b = 1 - expected_a

        if winner == agent_a.id:
            score_a, score_b = 1, 0
        elif winner == agent_b.id:
            score_a, score_b = 0, 1
        else:
            score_a, score_b = 0.5, 0.5

        agent_a.elo_rating += self.ELO_K_FACTOR * (score_a - expected_a)
        agent_b.elo_rating += self.ELO_K_FACTOR * (score_b - expected_b)

    def _eliminate_weakest(self):
        """淘汰最弱策略"""
        if len(self.agents) <= self.POPULATION_LIMIT:
            return

        sorted_agents = sorted(self.agents.values(), key=lambda a: a.elo_rating)
        to_remove = sorted_agents[:len(sorted_agents) - self.POPULATION_LIMIT]

        for agent in to_remove:
            del self.agents[agent.id]
            logger.info(f"淘汰: {agent.name} (ELO: {agent.elo_rating:.0f})")

    def _breed_champions(self):
        """冠军繁殖 - 优秀策略交叉产生后代"""
        top_agents = sorted(self.agents.values(), key=lambda a: a.elo_rating, reverse=True)[:5]
        if len(top_agents) < 2:
            return

        for i in range(min(3, len(top_agents) - 1)):
            parent_a = top_agents[i]
            parent_b = top_agents[i + 1]

            child_params = {}
            for key in set(list(parent_a.params.keys()) + list(parent_b.params.keys())):
                if key in parent_a.params and key in parent_b.params:
                    child_params[key] = (parent_a.params[key] + parent_b.params[key]) / 2
                    if random.random() < self.MUTATION_RATE:
                        child_params[key] *= (1 + np.random.randn() * 0.1)
                elif key in parent_a.params:
                    child_params[key] = parent_a.params[key]
                else:
                    child_params[key] = parent_b.params[key]

            child_name = f"{parent_a.name}_{parent_b.name}_gen{self.generation}"
            self.add_agent(child_name, parent_a.category, child_params,
                          parent_ids=[parent_a.id, parent_b.id])

    def get_leaderboard(self, top_n: int = 10) -> list[dict]:
        """获取排行榜"""
        sorted_agents = sorted(self.agents.values(), key=lambda a: a.elo_rating, reverse=True)
        return [
            {"rank": i + 1, "name": a.name, "elo": round(a.elo_rating, 0),
             "wins": a.wins, "losses": a.losses, "win_rate": a.wins / max(a.wins + a.losses, 1),
             "category": a.category, "generation": a.generation}
            for i, a in enumerate(sorted_agents[:top_n])
        ]

    def _save(self):
        data = {
            "generation": self.generation,
            "population": len(self.agents),
            "total_battles": len(self.battle_history),
            "leaderboard": self.get_leaderboard(5),
            "last_updated": datetime.now().isoformat(),
        }
        (MEMORY / "adversarial_training.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get_status(self) -> dict:
        return {
            "population": len(self.agents),
            "generation": self.generation,
            "total_battles": len(self.battle_history),
            "avg_elo": np.mean([a.elo_rating for a in self.agents.values()]) if self.agents else 0,
            "top_agent": self.get_leaderboard(1)[0] if self.agents else None,
        }
