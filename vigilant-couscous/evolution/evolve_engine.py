"""
进化引擎公共编排层 - P3b 合并产物

背景：strategy/unified_evolve.py（单币种 RSI+SMA，daily/weekly/once 三模式）
与 evolution/multi_dim_evolve.py（多币种 × 6 策略模板并行）各自重复实现了
同一套编排逻辑——取数、GA 装配、运行、回测验证门、策略入库。
本模块把重复部分收敛为一处，两个调用方保留各自的公开入口与策略配置：

- fetch_history      取数（原 get_btc_data / _fetch_data 逐字重复）
- run_ga             EvolutionEngine 装配 + 种子基因透传 + 运行
- validate_params    回测验证门（异常/无数据时返回 None，放行策略由调用方决定）
- register_strategy  策略入库 gh_strategy_library.json（原 _validate_and_update 写入部）

设计约束：不改变两个调用方的对外行为——
- unified 的验证异常时放行（passed 保持 True），multi 的验证异常时不放行
- 两者的 EvolutionConfig 参数值不同（elite/early_stop），由调用方传入
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_GENE_TEMPLATE = {
    "rsi_period": (5, 30), "sma_fast": (3, 15), "sma_slow": (15, 60),
    "stop_loss": (0.02, 0.15), "take_profit": (0.05, 0.40),
    "rsi_oversold": (20, 40), "rsi_overbought": (60, 85),
}


def fetch_history(symbol: str = 'BTC/USDT', days: int = 365):
    """获取历史行情数据（ccxt 源）

    原 unified_evolve.get_btc_data 与 multi_dim_evolve._fetch_data 逐字重复，
    2026-10-16 P3b 收敛到此。
    """
    import config
    from data.fetcher import DataFetcher
    fetcher = DataFetcher(okx_url=config.DATA_SOURCE["okx_url"])
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    return fetcher.fetch(symbol, start_date=start, end_date=end, source='ccxt')


def run_ga(data, param_template, fitness_factory, *, generations, population,
           elite_count=None, early_stop_generations=80, seed_genes=None, callback=None):
    """装配 EvolutionEngine 并运行完整遗传算法进化

    Args:
        data: 评估数据（原样传给 fitness_func）
        param_template: 参数模板 {name: (low, high)}
        fitness_factory: 适应度工厂，签名 data -> fitness_func(gene, data) -> float。
            2026-10-16 P3b：统一为工厂语义（两个调用方均传工厂）；
            原 callable() 启发式无法区分工厂与已绑定 fitness（两者皆 callable），已删除。
        generations / population: 进化轮数 / 种群大小
        elite_count: 精英保留数，缺省 max(3, population//8)（unified 口径；
            multi 传 max(2, population//10)）
        early_stop_generations: 早停轮数（unified 80 / multi 30）
        seed_genes: 种子基因列表（仅 unified 使用），格式 [{"params": {...}}]，
            经 run_evolution 透传进 initialize_population
        callback: 每代回调

    Returns:
        (engine, best_gene)
    """
    from evolution.learning_loop import EvolutionConfig, EvolutionEngine
    elite = elite_count if elite_count is not None else max(3, population // 8)
    config = EvolutionConfig(
        population_size=population,
        elite_count=elite,
        mutation_rate=0.15,
        crossover_rate=0.7,
        max_generations=generations,
        early_stop_generations=early_stop_generations,
    )
    engine = EvolutionEngine(config=config)

    fitness_func = fitness_factory(data)
    best = engine.run_evolution(
        fitness_func=fitness_func, data=data,
        param_template=param_template, callback=callback,
        seed_genes=seed_genes)
    return engine, best


def validate_params(data, params: dict, name: str):
    """回测验证门

    Returns:
        结果 dict（passed/score/sharpe/return/max_drawdown/warnings/total_trades）；
        数据不可用或验证异常时返回 None——放行策略由调用方决定
        （unified 视为跳过验证放行，multi 视为不通过）。
    """
    if data is None or getattr(data, 'empty', True):
        return None
    try:
        from evolution.backtest_validator import BacktestValidator
        validator = BacktestValidator(data)
        result = validator.validate_strategy(params, name)
        return {
            'passed': result.passed, 'score': result.score,
            'sharpe': result.sharpe_ratio, 'return': result.total_return,
            'max_drawdown': result.max_drawdown, 'warnings': result.warnings,
            'total_trades': result.total_trades,
        }
    except Exception as e:
        logger.warning(f"回测验证异常: {e}")
        return None


def register_strategy(params: dict, fitness: float, *, nexus_dir, source: str = 'self-evolution',
                      passed: bool = True) -> str:
    """把进化出的策略写入 gh_strategy_library.json，返回策略名

    原 unified_evolve._validate_and_update 的写入部分，2026-10-16 P3b 收敛。
    """
    lib_file = Path(nexus_dir) / 'gh_strategy_library.json'
    lib = json.loads(lib_file.read_text(encoding="utf-8")) if lib_file.exists() else {"strategies": []}
    name = f"evolved_{datetime.now().strftime('%m%d%H%M')}"
    entry = {"name": name, "source": source, "stars": int(fitness * 1000), "backtest_passed": passed}
    entry.update(params)
    lib["strategies"].append(entry)
    lib["total_strategies"] = len(lib["strategies"])
    lib_file.parent.mkdir(parents=True, exist_ok=True)
    lib_file.write_text(json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"策略已入库: {name}")
    return name
