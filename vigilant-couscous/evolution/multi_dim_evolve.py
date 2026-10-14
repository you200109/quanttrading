"""
多维度进化引擎 - 多币种、多策略类型、多参数空间并行进化

突破单一 BTC RSI+SMA 策略限制，实现：
- 多币种: BTC/ETH/SOL 同时进化
- 多策略: RSI/MACD/布林带/均线交叉/动量/成交量 6 种策略类型
- 多参数: 每种策略独立参数空间，自动发现最优组合
- 策略融合: 多策略信号加权投票
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
NEXUS = ROOT / "memory" / "nexus"
NEXUS.mkdir(parents=True, exist_ok=True)


@dataclass
class StrategyTemplate:
    """策略模板定义"""
    name: str
    category: str
    params: dict[str, tuple[float, float]]
    description: str


STRATEGY_TEMPLATES = {
    "rsi_reversal": StrategyTemplate(
        name="RSI 均值回归",
        category="momentum",
        params={
            "rsi_period": (5, 30), "rsi_oversold": (15, 40),
            "rsi_overbought": (60, 85), "stop_loss": (0.02, 0.15),
            "take_profit": (0.05, 0.40), "position_size": (0.1, 0.3),
        },
        description="RSI 超买超卖反转策略"
    ),
    "macd_cross": StrategyTemplate(
        name="MACD 金叉死叉",
        category="trend",
        params={
            "ema_fast": (8, 20), "ema_slow": (21, 50),
            "signal_period": (5, 15), "stop_loss": (0.02, 0.12),
            "take_profit": (0.08, 0.35), "position_size": (0.1, 0.3),
        },
        description="MACD 快慢线交叉趋势跟踪"
    ),
    "bollinger_breakout": StrategyTemplate(
        name="布林带突破",
        category="volatility",
        params={
            "bb_period": (10, 30), "bb_std": (1.5, 3.0),
            "stop_loss": (0.02, 0.10), "take_profit": (0.10, 0.50),
            "position_size": (0.1, 0.25),
        },
        description="布林带上下轨突破策略"
    ),
    "sma_cross": StrategyTemplate(
        name="均线交叉",
        category="trend",
        params={
            "sma_fast": (3, 20), "sma_slow": (15, 60),
            "stop_loss": (0.02, 0.12), "take_profit": (0.08, 0.35),
            "position_size": (0.1, 0.3),
        },
        description="双均线金叉死叉策略"
    ),
    "momentum_breakout": StrategyTemplate(
        name="动量突破",
        category="momentum",
        params={
            "lookback": (5, 30), "threshold": (0.01, 0.05),
            "stop_loss": (0.02, 0.10), "take_profit": (0.10, 0.40),
            "position_size": (0.1, 0.3),
        },
        description="价格动量突破策略"
    ),
    "volume_surge": StrategyTemplate(
        name="放量突破",
        category="volume",
        params={
            "vol_ma_period": (10, 30), "vol_multiple": (1.5, 4.0),
            "price_threshold": (0.01, 0.04), "stop_loss": (0.02, 0.10),
            "take_profit": (0.08, 0.35), "position_size": (0.1, 0.25),
        },
        description="成交量放大配合价格突破"
    ),
}

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


class MultiDimEvolution:
    """多维度进化引擎"""

    def __init__(self, symbols: list[str] = None, strategies: list[str] = None):
        self.symbols = symbols or SYMBOLS
        self.strategy_names = strategies or list(STRATEGY_TEMPLATES.keys())
        self.results: dict[str, dict] = {}

    def evolve_all(self, generations: int = 100, population: int = 30) -> dict:
        """并行进化所有币种×策略组合"""
        tasks = []
        for symbol in self.symbols:
            for strategy_name in self.strategy_names:
                tasks.append((symbol, strategy_name))

        logger.info(f"多维度进化启动: {len(tasks)} 个任务 ({len(self.symbols)}币种 × {len(self.strategy_names)}策略)")

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {}
            for symbol, strategy_name in tasks:
                future = executor.submit(self._evolve_single, symbol, strategy_name, generations, population)
                futures[future] = (symbol, strategy_name)

            for future in as_completed(futures):
                symbol, strategy_name = futures[future]
                try:
                    result = future.result()
                    key = f"{symbol}_{strategy_name}"
                    self.results[key] = result
                    if result.get("passed"):
                        logger.info(f"✅ {symbol} {strategy_name}: 适应度={result.get('fitness',0):.4f}")
                    else:
                        logger.info(f"❌ {symbol} {strategy_name}: 未通过")
                except Exception as e:
                    logger.error(f"{symbol} {strategy_name} 进化失败: {e}")

        self._save_results()
        return self._summarize()

    def _evolve_single(self, symbol: str, strategy_name: str,
                       generations: int, population: int) -> dict:
        """单币种单策略进化"""
        template = STRATEGY_TEMPLATES[strategy_name]
        data = self._fetch_data(symbol)
        if data.empty:
            return {"error": "数据获取失败"}

        from evolution.learning_loop import EvolutionConfig, EvolutionEngine

        config = EvolutionConfig(
            population_size=population,
            elite_count=max(2, population // 10),
            mutation_rate=0.15,
            crossover_rate=0.7,
            max_generations=generations,
            early_stop_generations=30,
        )
        engine = EvolutionEngine(config=config)
        engine.initialize_population(template.params)

        fitness_func = self._make_fitness(data, template)
        best = engine.run_evolution(
            fitness_func=fitness_func, data=data,
            param_template=template.params, callback=None
        )

        params = {k: (int(v) if isinstance(v, float) and v == int(v) and k.endswith('_period') else round(v, 4))
                   for k, v in best.params.items()}

        passed = False
        try:
            from evolution.backtest_validator import BacktestValidator
            validator = BacktestValidator(data)
            bt_result = validator.validate_strategy(params, f"{symbol}_{strategy_name}")
            passed = bt_result.passed
        except Exception:
            pass

        return {
            "symbol": symbol,
            "strategy": strategy_name,
            "category": template.category,
            "params": params,
            "fitness": best.fitness,
            "generation": best.generation,
            "passed": passed,
            "timestamp": datetime.now().isoformat(),
        }

    def _fetch_data(self, symbol: str) -> pd.DataFrame:
        """获取行情数据"""
        import config
        from data.fetcher import DataFetcher
        fetcher = DataFetcher(okx_url=config.DATA_SOURCE["okx_url"])
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        return fetcher.fetch(symbol, start_date=start, end_date=end, source='ccxt')

    def _make_fitness(self, data: pd.DataFrame, template: StrategyTemplate):
        """构建策略特定的适应度函数"""
        close = data['close'].values
        data.get('high', close).values
        data.get('low', close).values
        volume = data.get('volume', np.ones_like(close)).values
        n = len(close)

        def fitness(gene, _=None):
            params = gene.params
            if template.name == "RSI 均值回归":
                return self._sim_rsi(close, params, n)
            elif template.name == "MACD 金叉死叉":
                return self._sim_macd(close, params, n)
            elif template.name == "布林带突破":
                return self._sim_bollinger(close, params, n)
            elif template.name == "均线交叉":
                return self._sim_sma_cross(close, params, n)
            elif template.name == "动量突破":
                return self._sim_momentum(close, params, n)
            elif template.name == "放量突破":
                return self._sim_volume(close, volume, params, n)
            return 0.0

        return fitness

    def _sim_rsi(self, close, params, n):
        period = max(2, int(params.get('rsi_period', 14)))
        os_ = params.get('rsi_oversold', 30)
        ob = params.get('rsi_overbought', 70)
        sl = params.get('stop_loss', 0.05)
        tp = params.get('take_profit', 0.15)
        size = params.get('position_size', 0.2)
        return self._run_sim(close, n, period, lambda i, rsi, sma_f, sma_s, vol:
            'buy' if rsi[i] < os_ else ('sell' if rsi[i] > ob else 'hold'), sl, tp, size)

    def _sim_macd(self, close, params, n):
        fast = int(params.get('ema_fast', 12))
        slow = int(params.get('ema_slow', 26))
        sig = int(params.get('signal_period', 9))
        sl = params.get('stop_loss', 0.05)
        tp = params.get('take_profit', 0.15)
        size = params.get('position_size', 0.2)
        ema_f = pd.Series(close).ewm(span=fast).mean().values
        ema_s = pd.Series(close).ewm(span=slow).mean().values
        macd = ema_f - ema_s
        signal = pd.Series(macd).ewm(span=sig).mean().values
        return self._run_sim(close, n, max(fast, slow, sig), lambda i, rsi, sma_f, sma_s, vol:
            'buy' if macd[i] > signal[i] and macd[i-1] <= signal[i-1] else
            ('sell' if macd[i] < signal[i] and macd[i-1] >= signal[i-1] else 'hold'), sl, tp, size)

    def _sim_bollinger(self, close, params, n):
        period = int(params.get('bb_period', 20))
        std_mul = params.get('bb_std', 2.0)
        sl = params.get('stop_loss', 0.05)
        tp = params.get('take_profit', 0.15)
        size = params.get('position_size', 0.2)
        sma = pd.Series(close).rolling(period).mean().values
        std = pd.Series(close).rolling(period).std().values
        upper = sma + std_mul * std
        lower = sma - std_mul * std
        return self._run_sim(close, n, period, lambda i, rsi, sma_f, sma_s, vol:
            'buy' if close[i] < lower[i] else ('sell' if close[i] > upper[i] else 'hold'), sl, tp, size)

    def _sim_sma_cross(self, close, params, n):
        fast = max(1, int(params.get('sma_fast', 5)))
        slow = max(fast + 1, int(params.get('sma_slow', 20)))
        sl = params.get('stop_loss', 0.05)
        tp = params.get('take_profit', 0.15)
        size = params.get('position_size', 0.2)
        pd.Series(close).rolling(fast).mean().values
        pd.Series(close).rolling(slow).mean().values
        return self._run_sim(close, n, slow, lambda i, rsi, sma_f, sma_s, vol:
            'buy' if sma_f[i] > sma_s[i] and sma_f[i-1] <= sma_s[i-1] else
            ('sell' if sma_f[i] < sma_s[i] and sma_f[i-1] >= sma_s[i-1] else 'hold'), sl, tp, size)

    def _sim_momentum(self, close, params, n):
        lookback = int(params.get('lookback', 10))
        threshold = params.get('threshold', 0.02)
        sl = params.get('stop_loss', 0.05)
        tp = params.get('take_profit', 0.15)
        size = params.get('position_size', 0.2)
        momentum = pd.Series(close).pct_change(lookback).values
        return self._run_sim(close, n, lookback, lambda i, rsi, sma_f, sma_s, vol:
            'buy' if momentum[i] > threshold else ('sell' if momentum[i] < -threshold else 'hold'), sl, tp, size)

    def _sim_volume(self, close, volume, params, n):
        vol_period = int(params.get('vol_ma_period', 20))
        vol_mult = params.get('vol_multiple', 2.0)
        price_th = params.get('price_threshold', 0.02)
        sl = params.get('stop_loss', 0.05)
        tp = params.get('take_profit', 0.15)
        size = params.get('position_size', 0.2)
        vol_ma = pd.Series(volume).rolling(vol_period).mean().values
        price_chg = pd.Series(close).pct_change().values
        return self._run_sim(close, n, vol_period, lambda i, rsi, sma_f, sma_s, vol:
            'buy' if volume[i] > vol_ma[i] * vol_mult and price_chg[i] > price_th else
            ('sell' if volume[i] > vol_ma[i] * vol_mult and price_chg[i] < -price_th else 'hold'), sl, tp, size)

    def _run_sim(self, close, n, min_period, signal_func, sl, tp, size):
        """通用回测模拟"""
        if n < min_period + 2:
            return 0.0
        rsi = np.zeros(n)
        sma_f = np.zeros(n)
        sma_s = np.zeros(n)
        vol = np.zeros(n)
        capital, position, entry, trades = 100000.0, 0.0, 0.0, []
        for i in range(min_period, n):
            price = close[i]
            if position > 0:
                pnl = (price - entry) / entry
                if pnl <= -sl or pnl >= tp:
                    capital += position * price
                    trades.append(pnl)
                    position = 0
                    continue
            signal = signal_func(i, rsi, sma_f, sma_s, vol)
            if position == 0 and signal == 'buy':
                position = capital * size / price
                entry = price
                capital -= capital * size
            elif position > 0 and signal == 'sell':
                pnl = (price - entry) / entry
                capital += position * price
                trades.append(pnl)
                position = 0
        if position > 0:
            trades.append((close[-1] - entry) / entry)
            capital += position * close[-1]
        if len(trades) < 3:
            return 0.01
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
        return total_ret * 0.30 + max(0, sharpe) / 3 * 0.20 + (1 - mdd) * 0.20 + wr * 0.20 + min(1, len(trades) / 15) * 0.10

    def _save_results(self):
        """保存多维度进化结果"""
        output = {
            "timestamp": datetime.now().isoformat(),
            "total_tasks": len(self.results),
            "passed": sum(1 for r in self.results.values() if r.get("passed")),
            "results": self.results,
        }
        (NEXUS / "multi_dim_evolve.json").write_text(
            json.dumps(output, indent=2, ensure_ascii=False, default=str))

    def _summarize(self) -> dict:
        """汇总结果"""
        passed = {k: v for k, v in self.results.items() if v.get("passed")}
        by_symbol = {}
        for _k, v in passed.items():
            sym = v["symbol"]
            by_symbol.setdefault(sym, []).append(v)
        by_category = {}
        for _k, v in passed.items():
            cat = v.get("category", "unknown")
            by_category.setdefault(cat, []).append(v)
        return {
            "total": len(self.results),
            "passed": len(passed),
            "by_symbol": {s: len(v) for s, v in by_symbol.items()},
            "by_category": {c: len(v) for c, v in by_category.items()},
            "top_strategies": sorted(passed.values(), key=lambda x: x.get("fitness", 0), reverse=True)[:5],
        }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    engine = MultiDimEvolution()
    summary = engine.evolve_all(generations=80, population=25)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
