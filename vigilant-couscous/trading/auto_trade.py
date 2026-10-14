"""
全自动交易系�?- 自主运行主循�?
分析→交易→记录→优�?完整闭环
"""
import json
import logging
import os
import sys
import time
import traceback
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings('ignore')

Path('reports').mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler('reports/auto_trade.log', encoding='utf-8')]
)
logger = logging.getLogger(__name__)

from agents.alert_manager import AlertManager
from agents.multi_timeframe import MultiTimeframeAnalyzer
from agents.parallel_scheduler import DataCache, ParallelScheduler
from agents.researcher import ResearcherAgent
from agents.risk_manager import RiskLimits, RiskManagerAgent
from agents.trader import TraderAgent
from agi.adversarial_training import AdversarialTraining
from agi.agi_brain import AGIBrain
from agi.auto_researcher import AutoResearcher
from agi.continuous_learner import ContinuousLearner
from agi.distributed_orchestrator import DistributedOrchestrator
from agi.eternal_evolver import EternalEvolver
from agi.goal_manager import GoalManager
from agi.market_scanner import MarketScanner
from agi.memory_system import MemorySystem
from agi.meta_learner import MetaLearner
from agi.multi_modal_perception import MultiModalPerception
from agi.self_reflection import SelfReflectionEngine
from agi.zero_shot_adapter import ZeroShotAdapter
from data.fetcher import DataFetcher
from data.live_trader import OKXLiveTrader


class AutoTradingSystem:
    """全自动交易系�?""

    def __init__(self):
        self.fetcher = DataFetcher(okx_url='https://www.www.okx.com')
        self.research_agent = ResearcherAgent(verbose=False)
        self.trader = TraderAgent(initial_capital=100000)
        self.risk_mgr = RiskManagerAgent(limits=RiskLimits(min_confidence=0.01))
        self.live_trader = OKXLiveTrader(
            api_key=os.getenv('OKX_API_KEY', ''),
            secret_key=os.getenv('OKX_SECRET_KEY', ''),
            passphrase=os.getenv('OKX_PASSPHRASE', ''),
            base_url='https://www.www.okx.com',
            demo=os.getenv('OKX_DEMO', 'true').lower() == 'true'
        )
        self.symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
        self.trade_log = []
        self.iteration = 0
        self.start_time = datetime.now()
        self.alert_mgr = AlertManager()
        self.scheduler = ParallelScheduler(max_workers=4)
        self.data_cache = DataCache()
        self.peak_equity = 100000
        self.trading_paused = False
        self.agi_brain = AGIBrain()
        self.reflection_engine = SelfReflectionEngine()
        self.perception = MultiModalPerception()
        self.learner = ContinuousLearner()
        self.memory_system = MemorySystem()
        self.goal_manager = GoalManager()
        self.adversarial = AdversarialTraining()
        self.meta_learner = MetaLearner()
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
        logger.info(f'===== �?{self.iteration} 轮分�?=====')
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
                    traceback.print_exc()
            else:
                logger.warning(f'{symbol} 分析失败: {result.get("error", "未知错误")}')
        self._check_risk_alerts()
        self._run_agi_cycle()
        self._print_summary()
        self._save_state()

    def _fetch_data(self, symbol, **kwargs):
        """获取行情数据（带缓存�?""
        cached = self.data_cache.get_data(symbol, kwargs.get('timeframe', '1D'))
        if cached is not None:
            return cached
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        data = self.fetcher.fetch(symbol, start_date=start_date, end_date=end_date, source='ccxt')
        if not data.empty:
            self.data_cache.set_data(symbol, data, kwargs.get('timeframe', '1D'))
        return data

    def _analyze_single(self, symbol, data):
        """单币种综合分析（AGI大脑 + 多时间框架验证）"""
        if data is None or data.empty:
            return {'error': f'{symbol} 数据获取失败'}
        price = float(data['close'].iloc[-1])
        analysis = self.research_agent.analyze(symbol, data)
        mtf = MultiTimeframeAnalyzer(data, symbol)
        mtf_result = mtf.analyze()
        mtf_rec = mtf.get_trade_recommendation(mtf_result)
        agi_decision = None
        agi_perception = None
        if self.use_agi:
            try:
                context = self.agi_brain.analyze_market({
                    'close': data['close'].values,
                    'high': data['high'].values,
                    'low': data['low'].values,
                    'volume': data['volume'].values,
                }, symbol)
                portfolio = self.trader.get_portfolio_summary()
                agi_decision = self.agi_brain.think(context, portfolio)
                agi_perception = self.perception.perceive(symbol, {
                    'close': data['close'].values,
                    'volume': data['volume'].values,
                })
                logger.info(f'{symbol} AGI决策: {agi_decision.action} (置信�?{agi_decision.confidence:.0%}) | 感知: {agi_perception.overall_sentiment:.2f}')
            except Exception as e:
                logger.warning(f'AGI 分析跳过: {e}')
        return {
            'symbol': symbol, 'price': price,
            'analysis': analysis,
            'mtf': {
                'resonance_score': mtf_result.resonance_score,
                'consensus_trend': mtf_result.consensus_trend,
                'confidence': mtf_result.confidence,
                'recommendation': mtf_rec,
                'warnings': mtf_result.divergence_warnings,
            },
            'agi': {
                'decision': agi_decision.action if agi_decision else 'hold',
                'confidence': agi_decision.confidence if agi_decision else 0.5,
                'reasoning': agi_decision.reasoning[:100] if agi_decision else '',
                'perception': agi_perception.overall_sentiment if agi_perception else 0.5,
                'risk_level': agi_perception.risk_level if agi_perception else 'unknown',
            } if agi_decision else None,
        }

    def _execute_trade_from_analysis(self, symbol, result):
        """基于综合分析结果执行交易"""
        analysis = result['analysis']
        mtf = result['mtf']
        price = result['price']
        mtf_rec = mtf['recommendation']
        if mtf['warnings']:
            logger.info(f'{symbol} 多时间框架背离预�? {"; ".join(mtf["warnings"][:2])}')
            if mtf['resonance_score'] < 50:
                logger.info(f'{symbol} 共振评分过低({mtf["resonance_score"]:.0f})，跳过交�?)
                return
        if mtf_rec['action'] == 'hold' and analysis['recommendation'] != 'strong_buy':
            logger.info(f'{symbol} 多时间框架建议观望，跳过交易')
            return
        boosted_confidence = analysis['confidence'] * (0.7 + 0.3 * mtf['confidence'])
        analysis['confidence'] = min(1.0, boosted_confidence)
        logger.info(f'{symbol} ${price:,.2f} | 趋势:{analysis["trend"]} | 共振:{mtf["consensus_trend"]}({mtf["resonance_score"]:.0f}�? | 置信�?{analysis["confidence"]:.0%}')
        portfolio = self.trader.get_portfolio_summary()
        approved, reason = self.risk_mgr.approve_trade(analysis, portfolio)
        if not approved:
            logger.info(f'{symbol} 风控拒绝: {reason}')
            return
        order = self.trader.execute_signal(analysis, price)
        if order:
            self.trader.update_position(order, price)
            self.risk_mgr.set_stop_levels(symbol, price)
            live_order = self.live_trader.place_order(
                symbol.replace('/', '-'), order.side, order.quantity, order_type='market'
            )
            log_entry = {
                'time': datetime.now().isoformat(), 'symbol': symbol,
                'side': order.side, 'quantity': round(order.quantity, 6), 'price': price,
                'recommendation': analysis['recommendation'],
                'confidence': analysis['confidence'],
                'mtf_resonance': mtf['resonance_score'],
                'live_order_id': live_order.order_id if live_order else None
            }
            self.trade_log.append(log_entry)
            logger.info(f'{symbol} 交易执行: {order.side} {order.quantity:.4f}�?@ ${price:,.2f}')
            trade_result = {'symbol': symbol, 'pnl': 0, 'capital': portfolio.get('total_value', 100000)}
            for alert in self.alert_mgr.check_trade(trade_result):
                self.alert_mgr.send_alert(alert)
            if self.use_agi and result.get('agi'):
                try:
                    agi_decision = result.get('agi', {})
                    if agi_decision.get('decision') == order.side:
                        self.agi_brain.reflect(
                            self.agi_brain.decision_history[-1] if self.agi_brain.decision_history else None,
                            {'profit': 0, 'symbol': symbol}
                        )
                    trade_data = self._fetch_data(symbol)
                    state = self.learner.get_state_vector({
                        'close': trade_data['close'].values if not trade_data.empty else [],
                        'volume': trade_data['volume'].values if not trade_data.empty else [],
                    })
                    action_map = {'buy': 1, 'sell': 2, 'hold': 3}
                    self.learner.learn_from_trade(state, action_map.get(order.side, 3), 0, state, False)
                except Exception as e:
                    logger.debug(f'AGI 学习跳过: {e}')

    def _run_agi_cycle(self):
        """AGI 认知架构完整循环"""
        self.agi_cycle_count += 1
        try:
            self.trader.get_portfolio_summary()
            market_data = {'close': [], 'volume': []}
            self.goal_manager.adapt_to_market(market_data)
            self.memory_system.consolidate()
            if self.agi_cycle_count % 4 == 0:
                self.adversarial.run_tournament({'close': [], 'regime': self.goal_manager.current_regime.value})
            if self.agi_cycle_count % 12 == 0:
                self.meta_learner.optimize_hyperparams(
                    [self.agi_cycle_count * 0.001] * 20
                )
            if self.agi_cycle_count % 24 == 0:
                self.auto_researcher.research_cycle()
            if self.agi_cycle_count % 2 == 0:
                self.scanner.scan_all_markets()
            self.eternal_evolver.eternal_cycle()
        except Exception as e:
            logger.debug(f'AGI 循环跳过: {e}')

    def _check_risk_alerts(self):
        """检查风控告�?""
        try:
            portfolio = self.trader.get_portfolio_summary()
            current_equity = portfolio.get('total_value', 100000)
            if current_equity > self.peak_equity:
                self.peak_equity = current_equity
            for alert in self.alert_mgr.check_drawdown(current_equity, self.peak_equity):
                self.alert_mgr.send_alert(alert)
            for alert in self.alert_mgr.check_system_health({'api_errors': 0, 'data_timestamp': datetime.now()}):
                self.alert_mgr.send_alert(alert)
        except Exception as e:
            logger.error(f'风控检查异�? {e}')

    def _print_summary(self):
        """打印组合摘要"""
        summary = self.trader.get_portfolio_summary()
        elapsed = datetime.now() - self.start_time

        print(f'\n{"="*60}')
        print(f'  运行摘要 | 第{self.iteration}�?| 运行{elapsed}')
        print(f'{"="*60}')
        print(f'  总资�? ${summary["total_value"]:,.2f}')
        print(f'  总收�? {summary["total_return"]:.2%}')
        print(f'  持仓�? {summary["position_count"]}')
        print(f'  交易�? {len(self.trade_log)}')

        if summary.get('positions'):
            for s, p in summary['positions'].items():
                print(f'  {s}: {p["quantity"]:.4f}�? 均价${p["avg_price"]:,.2f}, 盈亏${p["pnl"]:,.2f}')
        print(f'{"="*60}\n')

    def _save_state(self):
        """保存系统状�?""
        state = {
            'iteration': self.iteration,
            'start_time': self.start_time.isoformat(),
            'last_update': datetime.now().isoformat(),
            'trade_count': len(self.trade_log),
            'portfolio': self.trader.get_portfolio_summary(),
            'recent_trades': self.trade_log[-10:]
        }
        with open('memory/nexus/auto_trade_state.json', 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False, default=str)

    def run_loop(self, interval_minutes=5, max_iterations=None):
        """持续运行主循�?""
        logger.info(f'全自动交易系统启�?| 间隔:{interval_minutes}分钟 | 币种:{self.symbols}')

        while max_iterations is None or self.iteration < max_iterations:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f'主循环异�? {e}')
                traceback.print_exc()

            if max_iterations and self.iteration >= max_iterations:
                break

            logger.info(f'等待 {interval_minutes} 分钟后下一�?..')
            time.sleep(interval_minutes * 60)

if __name__ == '__main__':
    system = AutoTradingSystem()

    if '--loop' in sys.argv:
        system.run_loop(interval_minutes=5)
    elif '--once' in sys.argv:
        system.run_once()
    else:
        print('用法: python auto_trade.py --once (单次) �?--loop (持续)')
        print('运行单次分析...')
        system.run_once()
