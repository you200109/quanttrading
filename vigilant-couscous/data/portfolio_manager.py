"""
多币种组合交易管理器

功能：
- 多币种同时监控（BTC、ETH、SOL 等）
- 动态资金分配（基于波动率加权）
- 组合层面风控
- 相关性分析
- 再平衡策略
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class AssetConfig:
    """资产配置"""
    symbol: str
    weight: float = 0.0
    max_weight: float = 0.4
    min_weight: float = 0.05
    volatility: float = 0.0
    trend: str = "neutral"
    signal_confidence: float = 0.0


@dataclass
class PortfolioState:
    """组合状态"""
    total_value: float = 0.0
    cash: float = 0.0
    positions: Dict[str, float] = field(default_factory=dict)
    weights: Dict[str, float] = field(default_factory=dict)
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    rebalance_count: int = 0


class PortfolioManager:
    """多币种组合管理器
    
    实现动态资金分配和组合优化：
    - 波动率倒数加权
    - 趋势跟踪调整
    - 相关性分散
    - 定期再平衡
    """
    
    # 默认监控的币种
    DEFAULT_SYMBOLS = [
        'BTC-USDT',
        'ETH-USDT',
        'SOL-USDT',
        'BNB-USDT',
        'XRP-USDT',
    ]
    
    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        initial_capital: float = 100000,
        max_positions: int = 5,
        rebalance_threshold: float = 0.1,
        risk_free_rate: float = 0.02
    ):
        self.symbols = symbols or self.DEFAULT_SYMBOLS
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.rebalance_threshold = rebalance_threshold
        self.risk_free_rate = risk_free_rate
        
        self.cash = initial_capital
        self.positions: Dict[str, float] = {s: 0.0 for s in self.symbols}
        self.entry_prices: Dict[str, float] = {}
        self.asset_configs: Dict[str, AssetConfig] = {}
        self.value_history: List[float] = [initial_capital]
        self.trade_history: List[dict] = []
        
        # 初始化资产配置
        equal_weight = 1.0 / len(self.symbols)
        for symbol in self.symbols:
            self.asset_configs[symbol] = AssetConfig(
                symbol=symbol,
                weight=equal_weight,
                max_weight=0.4,
                min_weight=0.05
            )
    
    def update_market_data(
        self,
        prices: Dict[str, float],
        historical_data: Optional[Dict[str, pd.DataFrame]] = None
    ):
        """更新市场数据并重新计算权重
        
        Args:
            prices: 当前价格 {symbol: price}
            historical_data: 历史数据用于计算波动率
        """
        # 计算波动率
        if historical_data:
            for symbol, df in historical_data.items():
                if symbol in self.asset_configs and len(df) > 20:
                    returns = df['close'].pct_change().dropna()
                    vol = returns.std() * np.sqrt(365)
                    self.asset_configs[symbol].volatility = vol
        
        # 更新持仓市值
        total_position_value = sum(
            self.positions.get(s, 0) * prices.get(s, 0)
            for s in self.symbols
        )
        total_value = self.cash + total_position_value
        
        # 更新权重
        for symbol in self.symbols:
            pos_value = self.positions.get(symbol, 0) * prices.get(symbol, 0)
            self.asset_configs[symbol].weight = pos_value / total_value if total_value > 0 else 0
        
        self.value_history.append(total_value)
    
    def calculate_target_weights(self) -> Dict[str, float]:
        """计算目标权重（波动率倒数加权）
        
        低波动资产获得更高权重，高波动资产降低权重。
        """
        vols = {}
        for symbol, config in self.asset_configs.items():
            vols[symbol] = config.volatility if config.volatility > 0 else 0.5
        
        # 波动率倒数
        inv_vols = {s: 1.0 / max(v, 0.01) for s, v in vols.items()}
        total_inv = sum(inv_vols.values())
        
        if total_inv == 0:
            # 等权重
            n = len(self.symbols)
            return {s: 1.0 / n for s in self.symbols}
        
        # 归一化并限制范围
        weights = {}
        for symbol in self.symbols:
            raw_weight = inv_vols[symbol] / total_inv
            config = self.asset_configs[symbol]
            weights[symbol] = max(config.min_weight, min(config.max_weight, raw_weight))
        
        # 重新归一化
        total = sum(weights.values())
        if total > 0:
            weights = {s: w / total for s, w in weights.items()}
        
        return weights
    
    def should_rebalance(self, target_weights: Dict[str, float]) -> bool:
        """判断是否需要再平衡"""
        total_deviation = 0.0
        for symbol in self.symbols:
            current = self.asset_configs[symbol].weight
            target = target_weights.get(symbol, 0)
            total_deviation += abs(current - target)
        
        return total_deviation > self.rebalance_threshold
    
    def generate_rebalance_orders(
        self,
        prices: Dict[str, float],
        target_weights: Dict[str, float]
    ) -> List[dict]:
        """生成再平衡订单
        
        Returns:
            订单列表 [{'symbol': ..., 'side': 'buy'/'sell', 'quantity': ...}]
        """
        total_value = self.get_total_value(prices)
        orders = []
        
        for symbol in self.symbols:
            target_value = total_value * target_weights.get(symbol, 0)
            current_value = self.positions.get(symbol, 0) * prices.get(symbol, 0)
            diff = target_value - current_value
            
            if abs(diff) < total_value * 0.01:  # 忽略小于 1% 的调整
                continue
            
            price = prices.get(symbol, 0)
            if price <= 0:
                continue
            
            if diff > 0:  # 需要买入
                quantity = diff / price
                if quantity * price <= self.cash:
                    orders.append({
                        'symbol': symbol,
                        'side': 'buy',
                        'quantity': quantity,
                        'value': diff,
                        'price': price
                    })
            else:  # 需要卖出
                quantity = min(abs(diff) / price, self.positions.get(symbol, 0))
                if quantity > 0:
                    orders.append({
                        'symbol': symbol,
                        'side': 'sell',
                        'quantity': quantity,
                        'value': abs(diff),
                        'price': price
                    })
        
        return orders
    
    def execute_order(self, order: dict):
        """执行订单"""
        symbol = order['symbol']
        side = order['side']
        quantity = order['quantity']
        price = order['price']
        
        if side == 'buy':
            cost = quantity * price
            if cost <= self.cash:
                self.positions[symbol] = self.positions.get(symbol, 0) + quantity
                self.cash -= cost
                self.entry_prices[symbol] = price
        else:
            revenue = quantity * price
            self.positions[symbol] = max(0, self.positions.get(symbol, 0) - quantity)
            self.cash += revenue
        
        self.trade_history.append({
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price': price,
            'value': quantity * price
        })
        
        logger.info(f"[组合] {side} {quantity:.4f} {symbol} @ ${price:,.2f}")
    
    def get_total_value(self, prices: Dict[str, float]) -> float:
        """计算总资产"""
        position_value = sum(
            self.positions.get(s, 0) * prices.get(s, 0)
            for s in self.symbols
        )
        return self.cash + position_value
    
    def get_portfolio_state(self, prices: Dict[str, float]) -> PortfolioState:
        """获取组合状态"""
        total_value = self.get_total_value(prices)
        
        weights = {}
        for symbol in self.symbols:
            pos_value = self.positions.get(symbol, 0) * prices.get(symbol, 0)
            weights[symbol] = pos_value / total_value if total_value > 0 else 0
        
        # 计算绩效
        if len(self.value_history) > 1:
            returns = np.diff(self.value_history) / np.array(self.value_history[:-1])
            sharpe = (np.mean(returns) - self.risk_free_rate / 365) / (np.std(returns) + 1e-8) * np.sqrt(365)
            
            peak = np.maximum.accumulate(self.value_history)
            drawdown = (peak - np.array(self.value_history)) / (peak + 1e-8)
            max_dd = np.max(drawdown)
        else:
            sharpe = 0
            max_dd = 0
        
        return PortfolioState(
            total_value=total_value,
            cash=self.cash,
            positions=self.positions.copy(),
            weights=weights,
            daily_pnl=total_value - self.value_history[-2] if len(self.value_history) > 1 else 0,
            total_pnl=total_value - self.initial_capital,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            rebalance_count=len([t for t in self.trade_history if t.get('type') == 'rebalance'])
        )
    
    def get_correlation_matrix(self, historical_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """计算资产相关性矩阵"""
        returns = {}
        for symbol, df in historical_data.items():
            if symbol in self.symbols and len(df) > 20:
                returns[symbol] = df['close'].pct_change().dropna()
        
        if len(returns) < 2:
            return pd.DataFrame()
        
        return pd.DataFrame(returns).corr()
    
    def get_summary(self, prices: Dict[str, float]) -> str:
        """生成组合摘要"""
        state = self.get_portfolio_state(prices)
        
        summary = f"""
{'='*50}
  多币种组合状态
{'='*50}
总资产: ${state.total_value:,.2f}
现金: ${state.cash:,.2f}
总收益: ${state.total_pnl:+,.2f} ({state.total_pnl/self.initial_capital*100:+.2f}%)
夏普比率: {state.sharpe_ratio:.2f}
最大回撤: {state.max_drawdown:.2%}

持仓:
"""
        for symbol in self.symbols:
            qty = self.positions.get(symbol, 0)
            if qty > 0:
                price = prices.get(symbol, 0)
                value = qty * price
                weight = state.weights.get(symbol, 0)
                summary += f"  {symbol}: {qty:.4f} @ ${price:,.2f} = ${value:,.2f} ({weight:.1%})\n"
        
        return summary
