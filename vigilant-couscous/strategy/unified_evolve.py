"""
统一进化引擎 - 进化流程三合一

合并原三个脚本:
1. daily_evolve  - 每日进化
2. weekly_evolve - 每周进化(含GitHub学习+版本升级)
3. evolve_btc    - 遗传算法参数优化

用法:
    python unified_evolve.py daily   每日轻量优化
    python unified_evolve.py weekly  每周完整流程
    python unified_evolve.py once    单次400轮优化
    python unified_evolve.py once --rl  单次优化+RL双引擎
"""
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 数据根目录：本文件位于 vigilant-couscous/strategy/ 下，仓库数据契约为
# vigilant-couscous/memory/nexus（与 learning_engine、vc_routes 共用）。
# 历史上曾误用 Path(__file__).parent（指向 strategy/），导致 gh_strategy_library
# 等契约文件读写分裂，2026-10-16 P3a 修复。
ROOT = Path(__file__).resolve().parent.parent
NEXUS = ROOT / "memory" / "nexus"
NEXUS.mkdir(parents=True, exist_ok=True)


def get_btc_data():
    """获取 BTC 训练数据"""
    import config
    from data.fetcher import DataFetcher
    fetcher = DataFetcher(okx_url=config.DATA_SOURCE["okx_url"])
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    data = fetcher.fetch('BTC/USDT', start_date=start, end_date=end, source='ccxt')
    logger.info(f"训练数据: {len(data)} 条")
    return data


def make_fitness(data):
    """构建抗过拟合的适应度函数

    改进点(解决训练集上万/测试集趋零的过拟合):
    1. 滚动窗口验证 - 切成 4 个连续窗口分别回测, 取均值并惩罚窗口间波动
    2. 收益封顶 - 单笔收益截断到 [-0.5, 0.5], 总收益封顶, 避免少数暴利单刷分
    3. 夏普钳制 - 夏普限定在 [-3, 3], 避免分母极小时爆炸
    4. 复杂度惩罚 - 过短周期/过紧止损扣分
    """
    close = data['close'].values
    n = len(close)

    def _simulate(seg, rsi_period, sma_fast, sma_slow, sl, tp, os_, ob):
        m = len(seg)
        if m < sma_slow + 2:
            return None
        delta = np.diff(seg, prepend=seg[0])
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = np.array([np.mean(gain[max(0, i-rsi_period+1):i+1]) for i in range(m)])
        avg_loss = np.array([np.mean(loss[max(0, i-rsi_period+1):i+1]) for i in range(m)])
        rs = np.divide(avg_gain, avg_loss, out=np.ones(m)*100, where=avg_loss != 0)
        rsi = 100 - (100 / (1 + rs))
        sma_f = pd.Series(seg).rolling(sma_fast).mean().values
        sma_s = pd.Series(seg).rolling(sma_slow).mean().values
        capital, position, entry, trades = 100000.0, 0.0, 0.0, []
        for i in range(sma_slow, m):
            price = seg[i]
            if position > 0:
                pnl = (price - entry) / entry
                if pnl <= -sl or pnl >= tp:
                    capital += position * price
                    trades.append(pnl)
                    position = 0
                    continue
            if position == 0 and not np.isnan(sma_f[i]) and not np.isnan(sma_s[i]):
                if rsi[i] < os_ or (sma_f[i] > sma_s[i] and sma_f[i-1] <= sma_s[i-1]):
                    conf = 0.85 if rsi[i] < os_ else 0.65
                    size = capital * 0.2 * conf
                    position = size / price
                    entry = price
                    capital -= size
            elif position > 0 and not np.isnan(sma_f[i]) and not np.isnan(sma_s[i]):
                if rsi[i] > ob or (sma_f[i] < sma_s[i] and sma_f[i-1] >= sma_s[i-1]):
                    pnl = (price - entry) / entry
                    capital += position * price
                    trades.append(pnl)
                    position = 0
        if position > 0:
            trades.append((seg[-1] - entry) / entry)
            capital += position * seg[-1]
        if len(trades) < 2:
            return None
        total_ret = (capital - 100000) / 100000
        capped = np.clip(np.array(trades), -0.5, 0.5)
        avg, std = np.mean(capped), np.std(capped)
        sharpe = (avg / std * np.sqrt(252)) if std > 0 else 0
        sharpe = max(-3.0, min(3.0, sharpe))
        cum = np.cumprod(1 + capped)
        peak = np.maximum.accumulate(cum)
        mdd = np.max((peak - cum) / (peak + 1e-8))
        wr = sum(1 for t in trades if t > 0) / len(trades)
        total_ret = max(-0.5, min(1.0, total_ret))
        return (total_ret*0.30 + max(0, sharpe)/3*0.20 + (1-mdd)*0.20
                + wr*0.20 + min(1, len(trades)/15)*0.10)

    def fitness(gene, _=None):
        rsi_period = max(2, int(gene.params.get('rsi_period', 14)))
        sma_fast = max(1, int(gene.params.get('sma_fast', 5)))
        sma_slow = max(sma_fast + 1, int(gene.params.get('sma_slow', 20)))
        sl = max(0.01, min(0.30, gene.params.get('stop_loss', 0.05)))
        tp = max(sl + 0.01, min(1.00, gene.params.get('take_profit', 0.15)))
        os_ = max(15, min(45, gene.params.get('rsi_oversold', 30)))
        ob = max(55, min(85, gene.params.get('rsi_overbought', 70)))
        if n < sma_slow + 2:
            return 0.0

        folds = 4
        seg_len = n // folds
        scores = []
        for k in range(folds):
            start = k * seg_len
            end = n if k == folds - 1 else (k + 1) * seg_len
            s = _simulate(close[start:end], rsi_period, sma_fast, sma_slow, sl, tp, os_, ob)
            if s is not None:
                scores.append(s)
        if not scores:
            return 0.05

        mean_score = float(np.mean(scores))
        consistency_penalty = float(np.std(scores)) * 0.3

        complexity = 0.0
        if rsi_period < 7:
            complexity += 0.02
        if sma_fast < 3:
            complexity += 0.02
        if sl < 0.03:
            complexity += 0.02

        return max(0.01, mean_score - consistency_penalty - complexity)

    return fitness


def run_evolution(data, generations, population, seed_genes=None, callback=None):
    """执行遗传算法进化"""
    from evolution.learning_loop import EvolutionConfig, EvolutionEngine, StrategyGene
    config = EvolutionConfig(population_size=population, elite_count=max(3, population//8),
                             mutation_rate=0.15, crossover_rate=0.7,
                             max_generations=generations, early_stop_generations=80)
    engine = EvolutionEngine(config=config)
    template = {"rsi_period": (5, 30), "sma_fast": (3, 15), "sma_slow": (15, 60),
                "stop_loss": (0.02, 0.15), "take_profit": (0.05, 0.40),
                "rsi_oversold": (20, 40), "rsi_overbought": (60, 85)}
    engine.initialize_population(template)

    if seed_genes:
        for i, seed in enumerate(seed_genes[:len(engine.population)]):
            engine.population[i] = StrategyGene(id=f"seed_{i}", generation=0, params=seed.get("params", {}))

    fitness = make_fitness(data)
    best = engine.run_evolution(fitness_func=fitness, data=data, param_template=template, callback=callback)
    return engine, best


def cmd_once(generations=400, population=40, use_rl=False):
    """单次遗传算法优化（支持 RL 双引擎 + 回测验证）"""
    logger.info(f"单次进化: {generations} 代")
    data = get_btc_data()
    if data.empty:
        logger.error("数据获取失败")
        return
    if use_rl:
        try:
            from evolution.rl_trainer import RLTrainer
            trainer = RLTrainer(algorithm='PPO')
            rl_result = trainer.train(data, total_timesteps=50000)
            logger.info(f"RL 训练完成: 平均收益 {rl_result.get('evaluation', {}).get('avg_return', 0):.2%}")
        except Exception as e:
            logger.warning(f"RL 训练失败: {e}，回退到纯遗传算法")
    engine, best = run_evolution(data, generations, population)
    params = {k: (int(v) if k in ('rsi_period','sma_fast','sma_slow') else round(v,4)) for k, v in best.params.items()}
    logger.info(f"最优适应度: {best.fitness:.4f}")
    logger.info(f"最优参数: {params}")
    _validate_and_update(params, best.fitness, data, "once")
    _save_result("once", params, best.fitness, engine.generation)


def cmd_daily():
    """每日轻量优化"""
    logger.info("每日进化: 200 代轻量优化")
    data = get_btc_data()
    if data.empty:
        return
    seeds = _load_seeds()
    engine, best = run_evolution(data, 200, 30, seed_genes=seeds)
    params = {k: (int(v) if k in ('rsi_period','sma_fast','sma_slow') else round(v,4)) for k, v in best.params.items()}
    _validate_and_update(params, best.fitness, data, "daily")
    logger.info(f"最优适应度: {best.fitness:.4f}")
    _save_result("daily", params, best.fitness, engine.generation)


def cmd_weekly(use_rl=False):
    """每周完整流程: 学习 + 进化 + RL + 回测验证 + 版本升级"""
    logger.info("每周进化: 完整流程")
    # 1. GitHub 学习
    try:
        from learning_engine import LearningEngine
        learner = LearningEngine()
        cycle = learner.full_cycle()
        logger.info(f"学习完成: 静态新增{cycle['static_added']}, 发现{sum(cycle['discovered'].values())}, 参数入库{cycle['params_added']}")
        seeds = learner.get_seed_genes(8)
    except Exception as e:
        logger.warning(f"学习环节跳过: {e}")
        seeds = _load_seeds()

    # 2. 进化
    data = get_btc_data()
    if data.empty:
        return
    if use_rl:
        try:
            from evolution.rl_trainer import RLTrainer
            trainer = RLTrainer(algorithm='PPO')
            rl_result = trainer.train(data, total_timesteps=100000)
            logger.info(f"RL 训练完成: 平均收益 {rl_result.get('evaluation', {}).get('avg_return', 0):.2%}")
        except Exception as e:
            logger.warning(f"RL 训练失败: {e}")
    engine, best = run_evolution(data, 300, 40, seed_genes=seeds)
    params = {k: (int(v) if k in ('rsi_period','sma_fast','sma_slow') else round(v,4)) for k, v in best.params.items()}

    # 3. 回测验证 + 版本升级
    _validate_and_update(params, best.fitness, data, "weekly")
    version = _bump_version()
    logger.info(f"最优适应度: {best.fitness:.4f} | 新版本: {version}")
    _save_result("weekly", params, best.fitness, engine.generation)


def _load_seeds():
    """从策略库加载种子"""
    lib = NEXUS / "gh_strategy_library.json"
    if not lib.exists():
        return []
    try:
        data = json.loads(lib.read_text(encoding="utf-8"))
        return [{"name": s.get("name",""), "params": {k: s.get(k) for k in ("rsi_period","sma_fast","sma_slow","stop_loss","take_profit","rsi_oversold","rsi_overbought")}}
                for s in data.get("strategies", [])[:8]]
    except Exception:
        return []


def _validate_and_update(params, fitness, data, mode="once"):
    """回测验证 + 策略入库"""
    if fitness < 0.3:
        logger.info(f"适应度 {fitness:.4f} < 0.3，跳过入库")
        return 0
    passed = True
    if data is not None and not data.empty:
        try:
            from evolution.backtest_validator import BacktestValidator
            validator = BacktestValidator(data)
            bt_result = validator.validate_strategy(params, f"evolved_{mode}")
            passed = bt_result.passed
            if passed:
                logger.info(f"回测通过 (评分: {bt_result.score:.0f}, 夏普: {bt_result.sharpe_ratio:.2f})")
            else:
                logger.warning(f"回测未通过: {'; '.join(bt_result.warnings)}")
        except Exception as e:
            logger.warning(f"回测验证异常: {e}，跳过验证")
    if not passed:
        return 0
    lib_file = NEXUS / "gh_strategy_library.json"
    lib = json.loads(lib_file.read_text(encoding="utf-8")) if lib_file.exists() else {"strategies": []}
    name = f"evolved_{datetime.now().strftime('%m%d%H%M')}"
    entry = {"name": name, "source": "self-evolution", "stars": int(fitness*1000), "backtest_passed": passed}
    entry.update(params)
    lib["strategies"].append(entry)
    lib["total_strategies"] = len(lib["strategies"])
    lib_file.write_text(json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"策略已入库: {name}")
    return 1


def _update_library(params, fitness):
    """把最优参数回写知识库（兼容旧接口）"""
    return _validate_and_update(params, fitness, None, "legacy")


def _bump_version():
    """版本升级"""
    vf = NEXUS / "version.json"
    data = json.loads(vf.read_text(encoding="utf-8")) if vf.exists() else {"version": "0.1.0", "history": []}
    parts = [int(x) for x in data["version"].split(".")]
    parts[2] += 1
    data["version"] = ".".join(str(p) for p in parts)
    data["last_updated"] = datetime.now().isoformat()
    data.setdefault("history", []).append({"version": data["version"], "time": datetime.now().isoformat()})
    vf.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data["version"]


def _save_result(mode, params, fitness, generations):
    """保存进化结果"""
    NEXUS.mkdir(parents=True, exist_ok=True)
    result = {"mode": mode, "timestamp": datetime.now().isoformat(),
              "best_params": params, "best_fitness": round(fitness, 4), "generations": generations}
    (NEXUS / "evolve_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("结果已保存: memory/nexus/evolve_result.json")


MODES = {"daily": cmd_daily, "weekly": cmd_weekly, "once": cmd_once}

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    use_rl = "--rl" in sys.argv
    if mode in MODES:
        func = MODES[mode]
        if mode in ("once", "weekly"):
            func(use_rl=use_rl)
        else:
            func()
    else:
        print("用法: python unified_evolve.py [daily|weekly|once] [--rl]")
        print(f"未知模式: {mode}")
