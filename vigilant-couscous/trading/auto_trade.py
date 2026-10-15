"""
自动交易系统 - 全自动分析→交易循环

整合所有模块实现无人值守的自动交易：
1. 多币种并行分析（技术指标+AI信号）
2. 自动下单执行（风控+仓位管理）
3. AGI 持续进化（学习+策略优化）
4. 实时风险监控与告警
5. 状态持久化与恢复
"""

import json
import logging
import os
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

warnings.filterwarnings('ignore')

# 日志配置
log_dir = Path('reports')
log_dir.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('reports/auto_trade.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class AutoTradingSystem:
    """全自动交易系统
    
    集成多币种分析、自动下单、AGI 进化、风险监控于一体。
    """

    def __init__(self, symbols=None, initial_capital=100000):
        self.symbols = symbols or ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.positions = {}
        self.trade_history = []
        self.iteration = 0
        self.trading_paused = False
        self.start_time = datetime.now()

        # OKX 配置
        self.okx_url = os.getenv('OKX_BASE_URL', 'https://www.okx.com')
        self.demo = os.getenv('OKX_DEMO', 'true').lower() == 'true'

        # 初始化交易接口
        from data.live_trader import OKXLiveTrader
        self.trader = OKXLiveTrader(
            api_key=os.getenv('OKX_API_KEY', ''),
            secret_key=os.getenv('OKX_SECRET_KEY', ''),
            passphrase=os.getenv('OKX_PASSPHRASE', ''),
            base_url=self.okx_url,
            demo=self.demo
        )

        # 初始化各模块
        from agents.risk_manager import RiskManager
        from agents.alert_manager import AlertManager
        from agents.parallel_scheduler import ParallelScheduler
        from agents.multi_timeframe import MultiTimeframeAnalyzer
        from agents.researcher import StrategyResearcher
        from agents.trader import SmartTrader
        from agi.agi_brain import AGIBrain
        from agi.auto_researcher import AutoResearcher
        from agi.continuous_learner import ContinuousLearner
        from agi.eternal_evolver import EternalEvolver
        from agi.zero_shot_adapter import ZeroShotAdapter
        from agi.distributed_orchestrator import DistributedOrchestrator
        from data.fetcher import DataFetcher

        self.risk_manager = RiskManager(
            max_position_pct=0.2,
            stop_loss_pct=0.05,
            take_profit_pct=0.15,
            max_drawdown_pct=0.2
        )
        self.alert_manager = AlertManager()
        self.scheduler = ParallelScheduler()
        self.mtf_analyzer = MultiTimeframeAnalyzer()
        self.researcher = StrategyResearcher()
        self.smart_trader = SmartTrader()
        self.fetcher = DataFetcher(okx_url=self.okx_url)

        # AGI 模块
        self.agi_brain = AGIBrain()
        self.continuous_learner = ContinuousLearner()
        self.zero_shot = ZeroShotAdapter()
        self.orchestrator = DistributedOrchestrator()
        self.auto_researcher = AutoResearcher()
        self.scanner = MarketScanner()
        self.eternal_evolver = EternalEvolver()
        self.use_agi = True
        self.agi_cycle_count = 0

    def run_once(self):
        """执行一次完整的分析→交易循环（并行优化版）"""
        if self.trading_paused:
            logger.info('交易已暂停，跳过本轮')
            return
        self.iteration += 1
        logger.info(f'===== 第 {self.iteration} 轮分析 =====')
        results = self.scheduler.analyze_symbols_parallel(
            self.symbols,
            analyzer_func=self._analyze_single,
            data_func=self._fetch_data,
            timeframe='1D'
        )
        for symbol, result in results.items():
            if isinstance(result, dict) and 'error' not in result:
                try:
                    self._execute_trade_from_analysis(symbol, result)
                except Exception as e:
                    logger.error(f'{symbol} 交易执行失败: {e}')
            else:
                logger.warning(f'{symbol} 分析失败: {result}')

        # AGI 进化周期
        if self.use_agi and self.iteration % 5 == 0:
            self._run_agi_cycle()

        # 风险检查
        self._check_risk_alerts()

        # 状态保存
        self._save_state()

        # 打印摘要
        self._print_summary()

    def run_loop(self, interval_seconds=3600):
        """持续运行自动交易循环"""
        logger.info(f'自动交易系统启动，间隔 {interval_seconds} 秒')
        logger.info(f'交易币种: {self.symbols}')
        logger.info(f'初始资金: ${self.initial_capital:,.2f}')
        logger.info(f'模式: {"演示" if self.demo else "实盘"}')

        try:
            while True:
                self.run_once()
                logger.info(f'等待 {interval_seconds} 秒...')
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            logger.info('收到中断信号，正在停止...')
            self._save_state()
            logger.info('状态已保存，系统已停止')

    def _fetch_data(self, symbol, timeframe='1D', days=365):
        """获取历史数据"""
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        data = self.fetcher.fetch(symbol, start_date=start_date, end_date=end_date, source='ccxt')
        return data

    def _analyze_single(self, symbol, data):
        """分析单个币种"""
        if data is None or data.empty:
            return {'error': '无数据'}

        close = data['close'].values

        # 多时间框架分析
        mtf_signal = self.mtf_analyzer.analyze(data)

        # 技术指标
        rsi = self._calc_rsi(close, 14)
        sma_fast = pd.Series(close).rolling(5).mean().values
        sma_slow = pd.Series(close).rolling(20).mean().values

        # 信号综合
        signals = []
        if rsi[-1] < 30:
            signals.append({'type': 'rsi_oversold', 'direction': 'buy', 'strength': 0.7})
        if rsi[-1] > 70:
            signals.append({'type': 'rsi_overbought', 'direction': 'sell', 'strength': 0.7})
        if sma_fast[-1] > sma_slow[-1] and sma_fast[-2] <= sma_slow[-2]:
            signals.append({'type': 'sma_cross_up', 'direction': 'buy', 'strength': 0.8})
        if sma_fast[-1] < sma_slow[-1] and sma_fast[-2] >= sma_slow[-2]:
            signals.append({'type': 'sma_cross_down', 'direction': 'sell', 'strength': 0.8})

        # AGI 增强
        if self.use_agi:
            agi_signal = self.agi_brain.predict(data)
            if agi_signal:
                signals.append(agi_signal)

        # 综合决策
        buy_strength = sum(s['strength'] for s in signals if s['direction'] == 'buy')
        sell_strength = sum(s['strength'] for s in signals if s['direction'] == 'sell')

        if buy_strength > sell_strength and buy_strength > 0.5:
            action = 'buy'
            confidence = min(buy_strength, 1.0)
        elif sell_strength > buy_strength and sell_strength > 0.5:
            action = 'sell'
            confidence = min(sell_strength, 1.0)
        else:
            action = 'hold'
            confidence = 0

        return {
            'symbol': symbol,
            'action': action,
            'confidence': confidence,
            'price': close[-1],
            'rsi': rsi[-1],
            'sma_fast': sma_fast[-1],
            'sma_slow': sma_slow[-1],
            'signals': signals,
            'mtf_signal': mtf_signal
        }

    def _execute_trade_from_analysis(self, symbol, analysis):
        """根据分析结果执行交易"""
        action = analysis['action']
        confidence = analysis['confidence']
        price = analysis['price']

        if action == 'hold':
            return

        # 风控检查
        risk_check = self.risk_manager.check(
            action=action,
            symbol=symbol,
            price=price,
            current_positions=self.positions,
            capital=self.capital,
            confidence=confidence
        )

        if not risk_check['approved']:
            logger.info(f'{symbol} 交易被风控拒绝: {risk_check["reason"]}')
            return

        # 计算仓位
        position_size = risk_check['position_size']
        quantity = position_size / price

        # 执行下单
        order = self.trader.place_order(
            symbol=symbol.replace('/', '-'),
            side=action,
            quantity=quantity,
            price=price,
            order_type='limit' if action == 'buy' else 'market'
        )

        if order:
            self.trade_history.append({
                'time': datetime.now().isoformat(),
                'symbol': symbol,
                'action': action,
                'price': price,
                'quantity': quantity,
                'confidence': confidence,
                'order_id': order.order_id
            })

            if action == 'buy':
                self.positions[symbol] = {
                    'quantity': quantity,
                    'entry_price': price,
                    'entry_time': datetime.now().isoformat()
                }
                self.capital -= position_size
                logger.info(f'买入 {symbol}: {quantity:.6f} @ ${price:,.2f} (置信度: {confidence:.0%})')
            elif action == 'sell' and symbol in self.positions:
                pos = self.positions[symbol]
                pnl = (price - pos['entry_price']) * pos['quantity']
                self.capital += quantity * price
                logger.info(f'卖出 {symbol}: {quantity:.6f} @ ${price:,.2f} (盈亏: ${pnl:+,.2f})')
                del self.positions[symbol]

    def _run_agi_cycle(self):
        """AGI 进化周期"""
        self.agi_cycle_count += 1
        logger.info(f'--- AGI 进化第 {self.agi_cycle_count} 轮 ---')

        try:
            # 持续学习
            self.continuous_learner.learn_from_trades(self.trade_history)

            # 策略研究
            self.auto_researcher.search_and_evolve()

            # 永恒进化
            self.eternal_evolver.evolve()

            logger.info('AGI 进化周期完成')
        except Exception as e:
            logger.error(f'AGI 进化失败: {e}')

    def _check_risk_alerts(self):
        """风险监控与告警"""
        total_position_value = sum(
            pos['quantity'] * self._get_current_price(symbol)
            for symbol, pos in self.positions.items()
        )
        position_ratio = total_position_value / self.capital if self.capital > 0 else 0

        if position_ratio > 0.8:
            self.alert_manager.send(
                level='WARNING',
                message=f'仓位占比过高: {position_ratio:.1%}'
            )

        # 检查回撤
        total_value = self.capital + total_position_value
        drawdown = (self.initial_capital - total_value) / self.initial_capital
        if drawdown > 0.2:
            self.alert_manager.send(
                level='CRITICAL',
                message=f'最大回撤超限: {drawdown:.1%}，暂停交易'
            )
            self.trading_paused = True

    def _get_current_price(self, symbol):
        """获取当前价格"""
        try:
            ticker = self.trader.get_ticker(symbol.replace('/', '-'))
            return ticker.get('last', 0)
        except Exception:
            return 0

    def _print_summary(self):
        """打印当前状态摘要"""
        total_position_value = sum(
            pos['quantity'] * self._get_current_price(symbol)
            for symbol, pos in self.positions.items()
        )
        total_value = self.capital + total_position_value
        pnl = total_value - self.initial_capital
        pnl_pct = pnl / self.initial_capital

        logger.info(f'--- 第 {self.iteration} 轮摘要 ---')
        logger.info(f'总资产: ${total_value:,.2f} (盈亏: ${pnl:+,.2f} / {pnl_pct:+.2%})')
        logger.info(f'持仓数: {len(self.positions)} | 交易次数: {len(self.trade_history)}')
        for symbol, pos in self.positions.items():
            current_price = self._get_current_price(symbol)
            pos_pnl = (current_price - pos['entry_price']) * pos['quantity']
            logger.info(f'  {symbol}: {pos["quantity"]:.6f} @ ${pos["entry_price"]:,.2f} (盈亏: ${pos_pnl:+,.2f})')

    def _save_state(self):
        """保存状态到文件"""
        state = {
            'iteration': self.iteration,
            'capital': self.capital,
            'positions': self.positions,
            'trade_history': self.trade_history[-100:],
            'timestamp': datetime.now().isoformat()
        }
        state_dir = Path('memory/nexus')
        state_dir.mkdir(parents=True, exist_ok=True)
        with open('memory/nexus/auto_trade_state.json', 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def load_state(self):
        """从文件恢复状态"""
        state_file = Path('memory/nexus/auto_trade_state.json')
        if state_file.exists():
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            self.iteration = state.get('iteration', 0)
            self.capital = state.get('capital', self.initial_capital)
            self.positions = state.get('positions', {})
            self.trade_history = state.get('trade_history', [])
            logger.info(f'状态已恢复: 第 {self.iteration} 轮, 资金 ${self.capital:,.2f}')


class MarketScanner:
    """市场扫描器"""

    def scan(self, symbols=None):
        """扫描市场机会"""
        symbols = symbols or ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
        opportunities = []
        for symbol in symbols:
            try:
                ticker = self._get_ticker(symbol)
                if ticker:
                    opportunities.append({
                        'symbol': symbol,
                        'price': ticker.get('last', 0),
                        'change24h': ticker.get('change24h', 0)
                    })
            except Exception:
                pass
        return opportunities

    def _get_ticker(self, symbol):
        """获取行情数据"""
        from data.live_trader import OKXLiveTrader
        trader = OKXLiveTrader(demo=True)
        return trader.get_ticker(symbol.replace('/', '-'))


if __name__ == '__main__':
    system = AutoTradingSystem()
    system.load_state()
    system.run_loop(interval_seconds=3600)
