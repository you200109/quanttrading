"""
基础策略类 - 所有交易策略的基类

基于 backtrader 框架，提供策略模板和通用功能：
- 参数管理
- 信号生成
- 订单管理
- 性能统计
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


@dataclass
class StrategyConfig:
    """策略配置"""
    name: str
    symbols: List[str] = field(default_factory=list)
    timeframe: str = "1d"
    initial_capital: float = 100000
    commission: float = 0.0003
    slippage: float = 0.001
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyResult:
    """策略回测结果"""
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    avg_trade_return: float = 0.0


class BaseStrategy(ABC):
    """策略基类
    
    所有交易策略必须继承此类并实现 generate_signals 方法。
    """
    
    def __init__(self, config: StrategyConfig):
        self.config = config
        self.name = config.name
        self.positions: Dict[str, float] = {}
        self.signals: List[dict] = []
        self.trades: List[dict] = []
        self.capital = config.initial_capital
        self.available_capital = config.initial_capital
        
    @abstractmethod
    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> List[dict]:
        """生成交易信号
        
        Args:
            data: 多标的历史数据，key 为 symbol，value 为 OHLCV DataFrame
            
        Returns:
            交易信号列表，每个信号包含 symbol、side、quantity、confidence 等
        """
        pass
    
    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算常用技术指标（基于 pandas-ta 成熟库）
        
        Args:
            data: OHLCV 数据，需包含 open/high/low/close/volume 列
            
        Returns:
            添加了指标列的 DataFrame
        """
        try:
            import pandas_ta as ta  # noqa: F401  # 导入即向 DataFrame 注册 .ta 访问器（副作用导入）
        except ImportError:
            raise ImportError(
                "pandas-ta 未安装，请执行: pip install pandas-ta"
            )
        df = data.copy()
        
        # 趋势类指标
        df.ta.sma(length=5, append=True, col_names=('sma_5',))
        df.ta.sma(length=10, append=True, col_names=('sma_10',))
        df.ta.sma(length=20, append=True, col_names=('sma_20',))
        df.ta.sma(length=50, append=True, col_names=('sma_50',))
        df.ta.sma(length=200, append=True, col_names=('sma_200',))
        df.ta.ema(length=12, append=True, col_names=('ema_12',))
        df.ta.ema(length=26, append=True, col_names=('ema_26',))
        df.ta.ema(length=50, append=True, col_names=('ema_50',))
        df.ta.wma(length=20, append=True, col_names=('wma_20',))
        df.ta.hma(length=20, append=True, col_names=('hma_20',))
        df.ta.alma(length=20, append=True, col_names=('alma_20',))
        df.ta.dema(length=20, append=True, col_names=('dema_20',))
        df.ta.tema(length=20, append=True, col_names=('tema_20',))
        df.ta.kama(length=20, append=True, col_names=('kama_20',))
        df.ta.vidya(length=20, append=True, col_names=('vidya_20',))
        df.ta.zlma(length=20, append=True, col_names=('zlma_20',))
        df.ta.supertrend(length=10, multiplier=3, append=True)
        df.ta.psar(append=True)
        
        # 动量类指标
        df.ta.rsi(length=14, append=True, col_names=('rsi_14',))
        df.ta.rsi(length=7, append=True, col_names=('rsi_7',))
        df.ta.rsi(length=21, append=True, col_names=('rsi_21',))
        df.ta.stoch(k=14, d=3, append=True)
        df.ta.stochrsi(length=14, append=True)
        df.ta.willr(length=14, append=True, col_names=('willr_14',))
        df.ta.cci(length=20, append=True, col_names=('cci_20',))
        df.ta.mom(length=10, append=True, col_names=('mom_10',))
        df.ta.roc(length=10, append=True, col_names=('roc_10',))
        df.ta.cmo(length=14, append=True, col_names=('cmo_14',))
        df.ta.uo(append=True)
        df.ta.ao(append=True)
        df.ta.apo(fast=12, slow=26, append=True)
        df.ta.ppo(fast=12, slow=26, append=True)
        df.ta.bop(append=True)
        df.ta.brar(length=26, append=True)
        df.ta.coppock(length=14, append=True, col_names=('coppock_14',))
        df.ta.er(length=10, append=True, col_names=('er_10',))
        df.ta.fisher(length=9, append=True)
        df.ta.kst(append=True)
        df.ta.pgo(length=14, append=True, col_names=('pgo_14',))
        df.ta.pvo(fast=12, slow=26, append=True)
        df.ta.qqe(length=14, append=True)
        df.ta.rvgi(length=14, append=True)
        df.ta.slope(length=20, append=True, col_names=('slope_20',))
        df.ta.smi(length=14, append=True)
        df.ta.squeeze(append=True)
        df.ta.squeeze_pro(append=True)
        df.ta.trix(length=15, append=True, col_names=('trix_15',))
        df.ta.tsi(fast=13, slow=25, append=True)
        
        # 波动类指标
        df.ta.bbands(length=20, std=2, append=True)
        df.ta.kc(length=20, scalar=2, append=True)
        df.ta.dc(length=20, append=True)
        df.ta.atr(length=14, append=True, col_names=('atr_14',))
        df.ta.atr(length=7, append=True, col_names=('atr_7',))
        df.ta.natr(length=14, append=True, col_names=('natr_14',))
        df.ta.true_range(append=True)
        df.ta.ui(length=14, append=True, col_names=('ui_14',))
        df.ta.massi(length=25, append=True)
        df.ta.aberration(length=20, append=True)
        df.ta.accbands(length=20, append=True)
        df.ta.hwc(length=20, append=True)
        
        # 成交量类指标
        df.ta.ad(append=True)
        df.ta.adosc(fast=3, slow=10, append=True)
        df.ta.aobv(length=14, append=True)
        df.ta.cmf(length=20, append=True, col_names=('cmf_20',))
        df.ta.efi(length=13, append=True)
        df.ta.eom(length=14, append=True)
        df.ta.kvo(fast=34, slow=55, append=True)
        df.ta.mfi(length=14, append=True, col_names=('mfi_14',))
        df.ta.nvi(append=True)
        df.ta.obv(append=True)
        df.ta.pvi(append=True)
        df.ta.pvol(length=14, append=True)
        df.ta.pvt(append=True)
        df.ta.vp(append=True)
        df.ta.vwap(append=True)
        df.ta.vwma(length=20, append=True, col_names=('vwma_20',))
        df.ta.wad(append=True)
        
        # 统计类指标
        df.ta.entropy(length=20, append=True, col_names=('entropy_20',))
        df.ta.kurtosis(length=30, append=True, col_names=('kurtosis_30',))
        df.ta.mad(length=20, append=True, col_names=('mad_20',))
        df.ta.median(length=20, append=True, col_names=('median_20',))
        df.ta.quantile(length=20, append=True)
        df.ta.skew(length=30, append=True, col_names=('skew_30',))
        df.ta.stdev(length=20, append=True, col_names=('stdev_20',))
        df.ta.tos_stdevall(length=20, append=True)
        df.ta.variance(length=20, append=True, col_names=('variance_20',))
        df.ta.zscore(length=20, append=True, col_names=('zscore_20',))
        
        # 复合/信号指标
        df.ta.decreasing(length=5, append=True, col_names=('decreasing_5',))
        df.ta.increasing(length=5, append=True, col_names=('increasing_5',))
        df.ta.linreg(length=20, append=True, col_names=('linreg_20',))
        df.ta.log_return(length=5, append=True, col_names=('logret_5',))
        df.ta.percent_return(length=5, append=True, col_names=('pctret_5',))
        df.ta.trend_return(length=20, append=True)
        
        return df
    
    def calculate_performance(self, trades: List[dict]) -> StrategyResult:
        """计算策略表现指标
        
        Args:
            trades: 交易记录列表
            
        Returns:
            StrategyResult 对象
        """
        if not trades:
            return StrategyResult()
        
        returns = [t.get('return_pct', 0) for t in trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        
        total_return = sum(returns)
        win_rate = len(wins) / len(returns) if returns else 0
        
        # 夏普比率（简化计算）
        if len(returns) > 1:
            avg_return = np.mean(returns)
            std_return = np.std(returns)
            sharpe = (avg_return / std_return * np.sqrt(252)) if std_return > 0 else 0
        else:
            sharpe = 0
        
        # 盈亏比
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 0
        profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses)) if avg_loss > 0 and len(losses) > 0 else 0
        
        # 最大回撤（简化）
        cumulative = np.cumsum(returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = running_max - cumulative
        max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0
        
        return StrategyResult(
            total_return=round(total_return, 4),
            annual_return=round(total_return * 252 / len(returns), 4) if len(returns) > 0 else 0,
            sharpe_ratio=round(sharpe, 2),
            max_drawdown=round(max_drawdown, 4),
            win_rate=round(win_rate, 4),
            total_trades=len(trades),
            profit_factor=round(profit_factor, 2),
            avg_trade_return=round(np.mean(returns), 4) if returns else 0
        )
    
    def optimize_params(
        self,
        data: Dict[str, pd.DataFrame],
        param_grid: Dict[str, List[Any]],
        metric: str = "sharpe_ratio"
    ) -> Dict[str, Any]:
        """网格搜索参数优化
        
        Args:
            data: 历史数据
            param_grid: 参数网格
            metric: 优化目标指标
            
        Returns:
            最优参数组合
        """
        best_params = {}
        best_score = -float('inf')
        
        # 生成所有参数组合
        from itertools import product
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        
        for combo in product(*values):
            params = dict(zip(keys, combo))
            # 更新参数
            for k, v in params.items():
                setattr(self, k, v)
            
            # 生成信号并评估
            signals = self.generate_signals(data)
            # 模拟交易
            trades = self._simulate_trades(signals, data)
            result = self.calculate_performance(trades)
            
            score = getattr(result, metric, 0)
            if score > best_score:
                best_score = score
                best_params = params.copy()
        
        # 恢复最优参数
        for k, v in best_params.items():
            setattr(self, k, v)
        
        logger.info(f"参数优化完成，最优参数: {best_params}, 最优{metric}: {best_score}")
        return best_params
    
    def _simulate_trades(self, signals: List[dict], data: Dict[str, pd.DataFrame]) -> List[dict]:
        """模拟交易执行"""
        trades = []
        for signal in signals:
            symbol = signal.get('symbol', '')
            side = signal.get('side', '')
            if symbol not in data:
                continue
            
            df = data[symbol]
            entry_price = df['close'].iloc[-1]
            exit_price = entry_price * (1.01 if side == 'buy' else 0.99)
            
            trade_return = (exit_price - entry_price) / entry_price
            if side == 'sell':
                trade_return = -trade_return
            
            trades.append({
                'symbol': symbol,
                'side': side,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'return_pct': trade_return,
                'timestamp': datetime.now()
            })
        
        return trades
