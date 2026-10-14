"""
策略回测验证管道

在策略入库前自动验证历史表现，过滤低质量策略。
支持滚动窗口验证、蒙特卡洛模拟、压力测试。
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    strategy_name: str
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    profit_factor: float
    calmar_ratio: float
    sortino_ratio: float
    avg_holding_days: float
    passed: bool
    score: float
    warnings: list[str] = field(default_factory=list)
    monthly_returns: dict[str, float] = field(default_factory=dict)


class BacktestValidator:
    MIN_TRADES = 20
    MIN_SHARPE = 0.3
    MAX_DRAWDOWN = 0.30
    MIN_WIN_RATE = 0.35
    MIN_PROFIT_FACTOR = 1.1
    MIN_ANNUAL_RETURN = 0.05

    def __init__(self, data: pd.DataFrame, initial_capital: float = 100000):
        self.data = data
        self.initial_capital = initial_capital
        self.commission = 0.001
        self.slippage = 0.0005

    def validate_strategy(self, strategy_params: dict, strategy_name: str = "unknown") -> BacktestResult:
        result = self._run_backtest(strategy_params)
        result.strategy_name = strategy_name
        result.passed = self._check_pass_criteria(result)
        result.score = self._calculate_score(result)
        return result

    def validate_batch(self, strategies: list[dict]) -> list[BacktestResult]:
        results = []
        for i, params in enumerate(strategies):
            name = params.get("name", f"strategy_{i}")
            result = self.validate_strategy(params, name)
            results.append(result)
            logger.info(f"[{i+1}/{len(strategies)}] {name}: {'通过' if result.passed else '未通过'} (评分: {result.score:.1f})")
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def rolling_window_validation(self, strategy_params: dict, windows: int = 4) -> dict:
        total_len = len(self.data)
        window_size = total_len // (windows + 1)
        results = []
        for i in range(windows):
            start = i * window_size
            end = start + window_size * 2
            window_data = self.data.iloc[start:end]
            validator = BacktestValidator(window_data, self.initial_capital)
            result = validator.validate_strategy(strategy_params, f"window_{i}")
            results.append(result)
        avg_return = np.mean([r.total_return for r in results])
        std_return = np.std([r.total_return for r in results])
        pass_count = sum(1 for r in results if r.passed)
        return {"avg_return": avg_return, "std_return": std_return,
                "min_return": min(r.total_return for r in results),
                "max_return": max(r.total_return for r in results),
                "pass_rate": pass_count / len(results),
                "stable": std_return < 0.15 and pass_count >= windows // 2,
                "window_results": [{"name": r.strategy_name, "return": r.total_return,
                                     "sharpe": r.sharpe_ratio, "passed": r.passed} for r in results]}

    def monte_carlo_simulation(self, strategy_params: dict, n_simulations: int = 200) -> dict:
        returns = []
        drawdowns = []
        for _ in range(n_simulations):
            shuffled = self.data.sample(frac=0.8, replace=True).sort_index()
            validator = BacktestValidator(shuffled, self.initial_capital)
            result = validator.validate_strategy(strategy_params)
            returns.append(result.total_return)
            drawdowns.append(result.max_drawdown)
        returns = np.array(returns)
        drawdowns = np.array(drawdowns)
        return {"mean_return": np.mean(returns), "median_return": np.median(returns),
                "std_return": np.std(returns), "p5_return": np.percentile(returns, 5),
                "p95_return": np.percentile(returns, 95),
                "prob_positive": np.mean(returns > 0),
                "mean_drawdown": np.mean(drawdowns),
                "max_drawdown_p95": np.percentile(drawdowns, 95),
                "n_simulations": n_simulations}

    def stress_test(self, strategy_params: dict) -> dict:
        scenarios = {
            "normal": self.data,
            "volatile": self._amplify_volatility(self.data, 2.0),
            "crash": self._simulate_crash(self.data),
            "low_volume": self._reduce_volume(self.data, 0.3),
        }
        results = {}
        for name, data in scenarios.items():
            validator = BacktestValidator(data, self.initial_capital)
            result = validator.validate_strategy(strategy_params, name)
            results[name] = {"return": result.total_return, "drawdown": result.max_drawdown,
                             "sharpe": result.sharpe_ratio, "passed": result.passed}
        all_pass = all(r["passed"] for r in results.values())
        worst_return = min(r["return"] for r in results.values())
        return {"scenarios": results, "all_pass": all_pass,
                "worst_return": worst_return,
                "robust": all_pass and worst_return > -0.20}

    def _run_backtest(self, params: dict) -> BacktestResult:
        close = self.data['close'].values
        self.data.get('high', close).values
        self.data.get('low', close).values
        rsi_period = params.get('rsi_period', 14)
        sma_fast = params.get('sma_fast', 5)
        sma_slow = params.get('sma_slow', 20)
        stop_loss = params.get('stop_loss', 0.05)
        take_profit = params.get('take_profit', 0.15)
        rsi_oversold = params.get('rsi_oversold', 30)
        rsi_overbought = params.get('rsi_overbought', 70)
        capital = self.initial_capital
        position = 0
        entry_price = 0
        trades = []
        equity_curve = [capital]
        for i in range(max(sma_slow, rsi_period) + 1, len(close)):
            rsi = self._calc_rsi(close[:i+1], rsi_period)
            sma_f = np.mean(close[i-sma_fast:i])
            sma_s = np.mean(close[i-sma_slow:i])
            price = close[i]
            if position > 0:
                pnl_pct = (price - entry_price) / entry_price
                if pnl_pct <= -stop_loss or pnl_pct >= take_profit:
                    capital += position * price * (1 - self.commission)
                    trades.append({"entry": entry_price, "exit": price, "pnl_pct": pnl_pct,
                                   "holding_days": i - trades[-1].get("exit_idx", i) if trades else i})
                    position = 0
            if position == 0:
                if rsi < rsi_oversold and sma_f > sma_s:
                    position = capital * 0.2 / price
                    capital -= position * price * (1 + self.commission)
                    entry_price = price
                elif rsi > rsi_overbought and sma_f < sma_s:
                    pass
            equity_curve.append(capital + position * price)
        if position > 0:
            capital += position * close[-1] * (1 - self.commission)
            trades.append({"entry": entry_price, "exit": close[-1],
                           "pnl_pct": (close[-1] - entry_price) / entry_price})
        return self._compute_metrics(trades, equity_curve, close)

    def _calc_rsi(self, prices: np.ndarray, period: int) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices[-period-1:])
        gains = np.sum(deltas[deltas > 0]) / period
        losses = -np.sum(deltas[deltas < 0]) / period
        return 100.0 - (100.0 / (1.0 + gains / (losses + 1e-8)))

    def _compute_metrics(self, trades: list[dict], equity: list[float], close: np.ndarray) -> BacktestResult:
        n = len(trades)
        if n == 0:
            return BacktestResult(strategy_name="", total_return=0, annual_return=0, sharpe_ratio=0,
                                  max_drawdown=0, win_rate=0, total_trades=0, profit_factor=0,
                                  calmar_ratio=0, sortino_ratio=0, avg_holding_days=0, passed=False, score=0)
        final_equity = equity[-1]
        total_return = (final_equity - self.initial_capital) / self.initial_capital
        days = len(close)
        annual_return = (1 + total_return) ** (365 / max(days, 1)) - 1
        equity_arr = np.array(equity)
        returns_arr = np.diff(equity_arr) / (equity_arr[:-1] + 1e-8)
        sharpe = np.mean(returns_arr) / (np.std(returns_arr) + 1e-8) * np.sqrt(252) if len(returns_arr) > 1 else 0
        peak = np.maximum.accumulate(equity_arr)
        drawdowns = (peak - equity_arr) / (peak + 1e-8)
        max_dd = np.max(drawdowns)
        wins = [t for t in trades if t['pnl_pct'] > 0]
        win_rate = len(wins) / n
        gross_profit = sum(t['pnl_pct'] for t in wins) * self.initial_capital / n
        gross_loss = abs(sum(t['pnl_pct'] for t in trades if t['pnl_pct'] <= 0)) * self.initial_capital / n
        profit_factor = gross_profit / (gross_loss + 1e-8)
        calmar = annual_return / (max_dd + 1e-8)
        neg_returns = returns_arr[returns_arr < 0]
        sortino = np.mean(returns_arr) / (np.std(neg_returns) + 1e-8) * np.sqrt(252) if len(neg_returns) > 0 else 0
        avg_holding = np.mean([t.get('holding_days', 1) for t in trades])
        return BacktestResult(strategy_name="", total_return=total_return, annual_return=annual_return,
                              sharpe_ratio=sharpe, max_drawdown=max_dd, win_rate=win_rate,
                              total_trades=n, profit_factor=profit_factor, calmar_ratio=calmar,
                              sortino_ratio=sortino, avg_holding_days=avg_holding, passed=False, score=0)

    def _check_pass_criteria(self, result: BacktestResult) -> bool:
        checks = [
            result.total_trades >= self.MIN_TRADES,
            result.sharpe_ratio >= self.MIN_SHARPE,
            result.max_drawdown <= self.MAX_DRAWDOWN,
            result.win_rate >= self.MIN_WIN_RATE,
            result.profit_factor >= self.MIN_PROFIT_FACTOR,
            result.annual_return >= self.MIN_ANNUAL_RETURN,
        ]
        failed = []
        names = ["交易次数", "夏普比率", "最大回撤", "胜率", "盈亏比", "年化收益"]
        thresholds = [self.MIN_TRADES, self.MIN_SHARPE, self.MAX_DRAWDOWN,
                      self.MIN_WIN_RATE, self.MIN_PROFIT_FACTOR, self.MIN_ANNUAL_RETURN]
        actuals = [result.total_trades, result.sharpe_ratio, result.max_drawdown,
                   result.win_rate, result.profit_factor, result.annual_return]
        for i, (check, name, thresh, actual) in enumerate(zip(checks, names, thresholds, actuals, strict=False)):
            if not check:
                if i == 2:
                    failed.append(f"{name}: {actual:.2%} > {thresh:.0%}")
                elif i in [0]:
                    failed.append(f"{name}: {actual} < {thresh}")
                else:
                    failed.append(f"{name}: {actual:.2f} < {thresh}")
        result.warnings = failed
        return all(checks)

    def _calculate_score(self, result: BacktestResult) -> float:
        score = 0
        score += min(result.sharpe_ratio * 20, 25)
        score += min(result.profit_factor * 10, 20)
        score += min(result.win_rate * 25, 20)
        score += min((1 - result.max_drawdown) * 20, 15)
        score += min(result.annual_return * 50, 15)
        score += min(result.total_trades / 5, 5)
        return min(100, score)

    def _amplify_volatility(self, data: pd.DataFrame, factor: float) -> pd.DataFrame:
        df = data.copy()
        returns = df['close'].pct_change().fillna(0)
        df['close'] = df['close'].iloc[0] * (1 + returns * factor).cumprod()
        return df

    def _simulate_crash(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        crash_start = len(df) // 2
        crash_len = min(20, len(df) - crash_start)
        for i in range(crash_start, crash_start + crash_len):
            df.iloc[i, df.columns.get_loc('close')] *= (1 - 0.03 * (i - crash_start + 1) / crash_len)
        return df

    def _reduce_volume(self, data: pd.DataFrame, factor: float) -> pd.DataFrame:
        df = data.copy()
        if 'volume' in df.columns:
            df['volume'] = df['volume'] * factor
        return df

    def generate_report(self, results: list[BacktestResult], output_path: str = "reports/backtest_report.json"):
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_strategies": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "pass_rate": sum(1 for r in results if r.passed) / max(len(results), 1),
            "top_strategies": [],
            "summary_stats": {},
        }
        passed_results = [r for r in results if r.passed]
        if passed_results:
            report["summary_stats"] = {
                "avg_sharpe": np.mean([r.sharpe_ratio for r in passed_results]),
                "avg_return": np.mean([r.total_return for r in passed_results]),
                "avg_win_rate": np.mean([r.win_rate for r in passed_results]),
                "avg_max_drawdown": np.mean([r.max_drawdown for r in passed_results]),
            }
        for r in results[:5]:
            report["top_strategies"].append({
                "name": r.strategy_name, "score": r.score, "passed": r.passed,
                "total_return": r.total_return, "sharpe_ratio": r.sharpe_ratio,
                "max_drawdown": r.max_drawdown, "win_rate": r.win_rate,
                "total_trades": r.total_trades, "warnings": r.warnings,
            })
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"回测报告已保存: {output_path}")
        return report
