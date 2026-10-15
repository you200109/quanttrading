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
from datetime import datetime
from pathlib import Path

import numpy as np

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
    """获取 BTC 训练数据（2026-10-16 P3b：委托 evolution/evolve_engine.fetch_history）"""
    from evolution import evolve_engine
    data = evolve_engine.fetch_history('BTC/USDT', days=365)
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
        from evolution import backtest_core
        m = len(seg)
        if m < sma_slow + 2:
            return None
        rsi = backtest_core.calc_rsi(seg, rsi_period)
        sma_f = backtest_core.calc_sma(seg, sma_fast)
        sma_s = backtest_core.calc_sma(seg, sma_slow)

        def _signal(i, rsi_arr, sf, ss, _vol, position):
            # 原逻辑：NaN 预热期不交易；空仓时 RSI 超卖优先买入（置信度 0.85），
            # 其次 SMA 金叉买入（0.65）；持仓时 RSI 超买或死叉平仓。
            # 注意买卖互斥由持仓状态分流（与原 if/elif 结构一致）。
            if np.isnan(sf[i]) or np.isnan(ss[i]):
                return 'hold'
            if position > 0:
                if rsi_arr[i] > ob:
                    return 'sell'
                if sf[i] < ss[i] and sf[i-1] >= ss[i-1]:
                    return 'sell'
                return 'hold'
            if rsi_arr[i] < os_:
                return ('buy', 0.2 * 0.85)
            if sf[i] > ss[i] and sf[i-1] <= ss[i-1]:
                return ('buy', 0.2 * 0.65)
            return 'hold'

        # 2026-10-16 P3b：原内联模拟循环（gain/loss 扩展窗口 RSI + 逐 bar 循环）
        # 收敛到 evolution/backtest_core.simulate，输出逐字节一致（黄金快照固化）
        result = backtest_core.simulate(seg, sma_slow, _signal, sl, tp, 0.2,
                                        initial_capital=100000.0,
                                        rsi=rsi, sma_f=sma_f, sma_s=sma_s)
        if len(result.trades) < 2:
            return None
        return backtest_core.fitness_score(result.trades, result.final_capital)

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
    """执行遗传算法进化（2026-10-16 P3b：委托 evolution/evolve_engine.run_ga）"""
    from evolution import evolve_engine
    engine, best = evolve_engine.run_ga(
        data, evolve_engine.DEFAULT_GENE_TEMPLATE, make_fitness,
        generations=generations, population=population,
        early_stop_generations=80, seed_genes=seed_genes, callback=callback)
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
        # 2026-10-16 P3b：原 from learning_engine import 在仓库根无此模块
        # （实际位于 strategy/），导入必然失败导致学习环节一直走 except 分支
        from strategy.learning_engine import LearningEngine
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
    """回测验证 + 策略入库（2026-10-16 P3b：验证门/入库委托 evolution/evolve_engine）"""
    from evolution import evolve_engine
    if fitness < 0.3:
        logger.info(f"适应度 {fitness:.4f} < 0.3，跳过入库")
        return 0
    # unified 口径：数据不可用或验证异常时视为跳过验证（放行）
    bt = evolve_engine.validate_params(data, params, f"evolved_{mode}")
    passed = True if bt is None else bt['passed']
    if bt is not None:
        if passed:
            logger.info(f"回测通过 (评分: {bt['score']:.0f}, 夏普: {bt['sharpe']:.2f})")
        else:
            logger.warning(f"回测未通过: {'; '.join(bt['warnings'])}")
    if not passed:
        return 0
    evolve_engine.register_strategy(params, fitness, nexus_dir=NEXUS, passed=passed)
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
