"""
并行处理调度器

实现多Agent并行协同、数据缓存层、任务优先级调度。
支持线程池并行分析、LRU数据缓存、进化引擎向量化加速。
"""

import hashlib
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class LRUCache:
    """线程安全的 LRU 缓存"""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            value, timestamp = self._cache[key]
            if (datetime.now() - timestamp).total_seconds() > self.ttl_seconds:
                del self._cache[key]
                self._misses += 1
                return None
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (value, datetime.now())
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def clear(self):
        with self._lock:
            self._cache.clear()

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0

    @property
    def stats(self) -> dict:
        return {"size": len(self._cache), "max_size": self.max_size,
                "hits": self._hits, "misses": self._misses, "hit_rate": self.hit_rate}


class DataCache:
    """分层数据缓存系统"""

    def __init__(self, cache_dir: str = "memory/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.memory_cache = LRUCache(max_size=500, ttl_seconds=600)
        self.disk_cache_ttl = timedelta(hours=24)

    def _make_key(self, symbol: str, timeframe: str, start: str, end: str) -> str:
        raw = f"{symbol}:{timeframe}:{start}:{end}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get_data(self, symbol: str, timeframe: str = "1D",
                 start: str = "", end: str = "") -> pd.DataFrame | None:
        key = self._make_key(symbol, timeframe, start, end)
        cached = self.memory_cache.get(key)
        if cached is not None:
            logger.debug(f"内存缓存命中: {symbol} {timeframe}")
            return cached
        disk_file = self.cache_dir / f"{key}.parquet"
        if disk_file.exists():
            mtime = datetime.fromtimestamp(disk_file.stat().st_mtime)
            if datetime.now() - mtime < self.disk_cache_ttl:
                try:
                    df = pd.read_parquet(disk_file)
                    self.memory_cache.set(key, df)
                    logger.debug(f"磁盘缓存命中: {symbol} {timeframe}")
                    return df
                except Exception:
                    pass
        return None

    def set_data(self, symbol: str, data: pd.DataFrame, timeframe: str = "1D",
                 start: str = "", end: str = ""):
        key = self._make_key(symbol, timeframe, start, end)
        self.memory_cache.set(key, data.copy())
        try:
            disk_file = self.cache_dir / f"{key}.parquet"
            data.to_parquet(disk_file, index=False)
        except Exception as e:
            logger.warning(f"磁盘缓存写入失败: {e}")

    def clear_expired(self):
        for f in self.cache_dir.glob("*.parquet"):
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if datetime.now() - mtime > self.disk_cache_ttl:
                f.unlink()
                logger.debug(f"清理过期缓存: {f.name}")

    @property
    def stats(self) -> dict:
        return {"memory": self.memory_cache.stats,
                "disk_files": len(list(self.cache_dir.glob("*.parquet")))}


@dataclass
class Task:
    id: str
    func: Callable
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    priority: int = 0
    timeout: float = 120
    depends_on: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    task_id: str
    success: bool
    result: Any = None
    error: str = ""
    duration: float = 0
    timestamp: datetime = field(default_factory=datetime.now)


class ParallelScheduler:
    """并行任务调度器"""

    def __init__(self, max_workers: int = 8):
        self.max_workers = max_workers
        self.data_cache = DataCache()
        self.results: dict[str, TaskResult] = {}
        self._lock = Lock()

    def run_parallel(self, tasks: list[Task]) -> dict[str, TaskResult]:
        """并行执行任务列表"""
        results = {}
        ready_tasks = [t for t in tasks if not t.depends_on]
        pending_tasks = [t for t in tasks if t.depends_on]
        with ThreadPoolExecutor(max_workers=min(self.max_workers, max(len(ready_tasks), 1))) as executor:
            futures = {}
            for task in ready_tasks:
                future = executor.submit(self._execute_task, task)
                futures[future] = task
            for future in as_completed(futures):
                task = futures[future]
                try:
                    result = future.result(timeout=task.timeout)
                except Exception as e:
                    result = TaskResult(task_id=task.id, success=False, error=str(e))
                results[task.id] = result
                self.results[task.id] = result
                for pt in pending_tasks[:]:
                    if all(dep in results for dep in pt.depends_on):
                        pending_tasks.remove(pt)
                        dep_results = {dep: results[dep] for dep in pt.depends_on}
                        future = executor.submit(self._execute_task_with_deps, pt, dep_results)
                        futures[future] = pt
        for pt in pending_tasks:
            results[pt.id] = TaskResult(task_id=pt.id, success=False, error="依赖任务未完成")
        return results

    def analyze_symbols_parallel(self, symbols: list[str], analyzer_func: Callable,
                                 data_func: Callable, **kwargs) -> dict[str, Any]:
        """并行分析多个交易标的"""
        tasks = []
        for symbol in symbols:
            tasks.append(Task(
                id=f"analyze_{symbol.replace('/', '_')}",
                func=self._analyze_single_symbol,
                args=(symbol, analyzer_func, data_func),
                kwargs=kwargs,
                timeout=180,
            ))
        results = self.run_parallel(tasks)
        output = {}
        for task_id, result in results.items():
            symbol = task_id.replace("analyze_", "").replace("_", "/")
            output[symbol] = result.result if result.success else {"error": result.error}
        return output

    def _analyze_single_symbol(self, symbol: str, analyzer_func: Callable,
                               data_func: Callable, **kwargs) -> dict:
        cached = self.data_cache.get_data(symbol, kwargs.get("timeframe", "1D"))
        if cached is not None:
            data = cached
        else:
            data = data_func(symbol, **kwargs)
            if data is not None and not data.empty:
                self.data_cache.set_data(symbol, data, kwargs.get("timeframe", "1D"))
        if data is None or data.empty:
            return {"error": f"{symbol} 数据获取失败"}
        return analyzer_func(symbol, data)

    def _execute_task(self, task: Task) -> TaskResult:
        start = time.time()
        try:
            result = task.func(*task.args, **task.kwargs)
            duration = time.time() - start
            return TaskResult(task_id=task.id, success=True, result=result, duration=duration)
        except Exception as e:
            duration = time.time() - start
            logger.error(f"任务 {task.id} 失败: {e}")
            return TaskResult(task_id=task.id, success=False, error=str(e), duration=duration)

    def _execute_task_with_deps(self, task: Task, dep_results: dict[str, TaskResult]) -> TaskResult:
        merged_kwargs = {**task.kwargs, "_dep_results": dep_results}
        merged_task = Task(id=task.id, func=task.func, args=task.args,
                           kwargs=merged_kwargs, timeout=task.timeout)
        return self._execute_task(merged_task)

    def get_summary(self) -> dict:
        with self._lock:
            total = len(self.results)
            success = sum(1 for r in self.results.values() if r.success)
            avg_duration = np.mean([r.duration for r in self.results.values()]) if self.results else 0
        return {"total_tasks": total, "success": success, "failed": total - success,
                "avg_duration": avg_duration, "cache_stats": self.data_cache.stats}


class VectorizedEvolution:
    """向量化进化引擎加速器"""

    @staticmethod
    def batch_fitness(population: np.ndarray, price_data: np.ndarray,
                      rsi_periods: np.ndarray, sma_fast: np.ndarray,
                      sma_slow: np.ndarray) -> np.ndarray:
        """批量计算种群适应度（向量化）"""
        n_individuals = len(population)
        n_days = len(price_data)
        if n_days < max(sma_slow.max(), rsi_periods.max()) + 1:
            return np.zeros(n_individuals)
        returns = np.diff(price_data) / (price_data[:-1] + 1e-8)
        fitness = np.zeros(n_individuals)
        for i in range(n_individuals):
            rsi_p = int(rsi_periods[i])
            sma_f = int(sma_fast[i])
            sma_s = int(sma_slow[i])
            start_idx = max(sma_s, rsi_p) + 1
            if start_idx >= n_days:
                continue
            sma_f_vals = np.convolve(price_data, np.ones(sma_f)/sma_f, mode='valid')
            sma_s_vals = np.convolve(price_data, np.ones(sma_s)/sma_s, mode='valid')
            min_len = min(len(sma_f_vals), len(sma_s_vals))
            signals = (sma_f_vals[-min_len:] > sma_s_vals[-min_len:]).astype(int)
            signal_returns = signals[:-1] * returns[-len(signals)+1:]
            total_return = np.prod(1 + signal_returns) - 1 if len(signal_returns) > 0 else 0
            sharpe = np.mean(signal_returns) / (np.std(signal_returns) + 1e-8) * np.sqrt(252) if len(signal_returns) > 1 else 0
            cumulative = np.cumprod(1 + signal_returns) if len(signal_returns) > 0 else np.array([1])
            peak = np.maximum.accumulate(cumulative)
            drawdown = np.max((peak - cumulative) / (peak + 1e-8))
            fitness[i] = total_return * 0.3 + sharpe * 0.02 - drawdown * 0.3
        return fitness

    @staticmethod
    def batch_crossover(parents: np.ndarray, n_offspring: int,
                        crossover_rate: float = 0.8) -> np.ndarray:
        """批量交叉操作（向量化）"""
        n_parents, n_genes = parents.shape
        offspring = np.zeros((n_offspring, n_genes))
        for i in range(n_offspring):
            p1, p2 = np.random.choice(n_parents, 2, replace=False)
            mask = np.random.random(n_genes) < crossover_rate
            offspring[i] = np.where(mask, parents[p1], parents[p2])
        return offspring

    @staticmethod
    def batch_mutation(population: np.ndarray, mutation_rate: float = 0.1,
                       bounds: np.ndarray | None = None) -> np.ndarray:
        """批量变异操作（向量化）"""
        mutated = population.copy()
        n, m = population.shape
        mask = np.random.random((n, m)) < mutation_rate
        noise = np.random.randn(n, m) * 0.1 * population.std(axis=0)
        mutated = mutated + mask * noise
        if bounds is not None:
            mutated = np.clip(mutated, bounds[0], bounds[1])
        return mutated

    @staticmethod
    def batch_selection(population: np.ndarray, fitness: np.ndarray,
                        n_select: int, tournament_size: int = 3) -> np.ndarray:
        """批量锦标赛选择（向量化）"""
        n = len(population)
        selected = np.zeros((n_select, population.shape[1]))
        for i in range(n_select):
            candidates = np.random.choice(n, tournament_size, replace=False)
            winner = candidates[np.argmax(fitness[candidates])]
            selected[i] = population[winner]
        return selected
