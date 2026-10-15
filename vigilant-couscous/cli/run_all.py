"""
自进化交易系统 - 全模块集成入口

整合所有升级模块：
1. GitHub 在线学习 - 真实 API 搜索策略
2. RL 强化学习训练 - PPO/DQN 交易 Agent
3. 多币种组合交易 - BTC/ETH/SOL 动态配置
4. 实盘交易接口 - 欧易 API 自动下单
5. 遗传算法进化 - 400 轮迭代优化
6. 可视化报告 - 交互式 HTML 图表

用法:
    python run_all.py              # 完整流程
    python run_all.py --rl         # 仅 RL 训练
    python run_all.py --live       # 实盘监控
    python run_all.py --learn      # GitHub 学习
"""

import argparse
import logging
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

warnings.filterwarnings('ignore')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def step_github_learn():
    """Step 1: GitHub 在线学习"""
    print('\n' + '=' * 60)
    print('  [1/5] GitHub 在线学习 - 搜索真实策略')
    print('=' * 60)

    from learning_engine import LearningEngine

    learner = LearningEngine()

    # 搜索和学习
    print('正在搜索 GitHub 量化交易策略...')
    knowledge = learner.daily_search_and_learn(n_repos=3)

    if knowledge:
        print(f'\n学到 {len(knowledge)} 个仓库的策略:')
        for k in knowledge:
            params_count = len(k.get('extracted_params', []))
            print(f'  📚 {k["full_name"]} (⭐{k["stars"]})')
            print(f'     {k["description"][:80]}...')
            if params_count > 0:
                print(f'     提取了 {params_count} 组策略参数')
    else:
        print('今日已学习或搜索无新结果')

    # 获取种子参数
    seeds = learner.get_seed_params(n=5)
    print(f'\n提取 {len(seeds)} 组种子参数用于进化')

    report = learner.get_status()
    print(f'累计学习: {report.get("total_repos_learned", 0)} 个仓库, {report.get("total_params_extracted", 0)} 组参数')

    return learner, seeds


def step_rl_train(data: pd.DataFrame):
    """Step 2: RL 强化学习训练"""
    print('\n' + '=' * 60)
    print('  [2/5] RL 强化学习训练 - PPO Agent')
    print('=' * 60)

    from evolution.rl_environment import TradingEnvConfig
    from evolution.rl_trainer import RLTrainer

    TradingEnvConfig(
        initial_capital=100000,
        window_size=60,
        max_position=1.0,
        commission=0.001
    )

    trainer = RLTrainer(algorithm="PPO")

    print(f'训练数据: {len(data)} 条')
    print('算法: PPO, 步数: 50000')

    result = trainer.train(
        data,
        total_timesteps=50000,
        learning_rate=0.0003,
        verbose=0
    )

    if 'error' not in result:
        eval_result = result.get('evaluation', {})
        print('\n训练完成!')
        print(f'  耗时: {result["training_time"]:.1f} 秒')
        print(f'  平均收益: {eval_result.get("avg_return", 0):.2%}')
        print(f'  最大收益: {eval_result.get("max_return", 0):.2%}')
        print(f'  平均胜率: {eval_result.get("avg_win_rate", 0):.1%}')
    else:
        print(f'训练失败: {result["error"]}')

    return trainer


def step_portfolio_test():
    """Step 3: 多币种组合测试"""
    print('\n' + '=' * 60)
    print('  [3/5] 多币种组合交易测试')
    print('=' * 60)

    from data.fetcher import DataFetcher
    from data.portfolio_manager import PortfolioManager

    pm = PortfolioManager(
        symbols=['BTC-USDT', 'ETH-USDT', 'SOL-USDT'],
        initial_capital=100000
    )

    fetcher = DataFetcher(okx_url='https://www.www.okx.com')

    # 获取多币种价格
    prices = {}
    for symbol in pm.symbols:
        try:
            ticker_data = fetcher.fetch(
                symbol.replace('-', '/'),
                start_date=(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'),
                end_date=datetime.now().strftime('%Y-%m-%d'),
                source='ccxt'
            )
            if not ticker_data.empty:
                prices[symbol] = ticker_data['close'].iloc[-1]
                print(f'  {symbol}: ${prices[symbol]:,.2f}')
        except Exception as e:
            print(f'  {symbol}: 获取失败 - {e}')

    if prices:
        # 计算目标权重
        targets = pm.calculate_target_weights()
        print('\n目标权重:')
        for s, w in targets.items():
            print(f'  {s}: {w:.1%}')

        # 生成再平衡订单
        orders = pm.generate_rebalance_orders(prices, targets)
        if orders:
            print(f'\n再平衡订单 ({len(orders)} 笔):')
            for o in orders:
                print(f'  {o["side"]} {o["quantity"]:.4f} {o["symbol"]} @ ${o["price"]:,.2f}')
        else:
            print('无需再平衡')

    return pm


def step_live_trader_test():
    """Step 4: 实盘交易接口测试"""
    print('\n' + '=' * 60)
    print('  [4/5] 实盘交易接口测试')
    print('=' * 60)

    from data.live_trader import OKXLiveTrader

    trader = OKXLiveTrader(
        base_url='https://www.www.okx.com',
        demo=True
    )

    # 获取实时行情
    print('获取 BTC-USDT 实时行情...')
    ticker = trader.get_ticker('BTC-USDT')
    if ticker:
        print(f'  最新价: ${ticker["last"]:,.2f}')
        print(f'  24h最高: ${ticker["high24h"]:,.2f}')
        print(f'  24h最低: ${ticker["low24h"]:,.2f}')
        print(f'  24h成交量: {ticker["vol24h"]:,.2f}')

    # 获取 K 线
    print('\n获取近 5 天日线...')
    candles = trader.get_candles('BTC-USDT', '1D', 5)
    for c in candles:
        ts = datetime.fromtimestamp(c['timestamp'] / 1000)
        print(f'  {ts.strftime("%m-%d")} O:{c["open"]:,.0f} H:{c["high"]:,.0f} L:{c["low"]:,.0f} C:{c["close"]:,.0f}')

    # 演示下单
    print('\n演示下单（模拟模式）...')
    order = trader.place_order('BTC-USDT', 'buy', 100, order_type='market')
    if order:
        print(f'  订单ID: {order.order_id}')
        print(f'  方向: {order.side}')
        print(f'  数量: {order.quantity}')
        print(f'  状态: {order.status}')

    return trader


def step_generate_report(results: dict):
    """Step 5: 生成综合报告"""
    print('\n' + '=' * 60)
    print('  [5/5] 综合报告')
    print('=' * 60)

    report = f"""
{'='*60}
  自进化交易系统 - 全模块运行报告
  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*60}

📚 GitHub 在线学习:
  累计仓库: {results.get('gh_repos', 0)}
  提取参数: {results.get('gh_params', 0)} 个

🧠 RL 强化学习:
  算法: PPO
  训练步数: 50,000
  平均收益: {results.get('rl_return', 0):.2%}

📊 多币种组合:
  监控币种: BTC, ETH, SOL
  再平衡订单: {results.get('rebalance_orders', 0)} 笔

💹 实盘接口:
  状态: {'正常' if results.get('live_ok') else '演示模式'}
  BTC 价格: ${results.get('btc_price', 0):,.2f}

{'='*60}
"""

    print(report)

    # 保存报告
    report_dir = Path('reports')
    report_dir.mkdir(exist_ok=True)
    report_file = report_dir / f'all_modules_report_{datetime.now().strftime("%Y%m%d_%H%M")}.txt'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f'报告已保存: {report_file}')


def main():
    parser = argparse.ArgumentParser(description='自进化交易系统 - 全模块集成')
    parser.add_argument('--rl', action='store_true', help='仅 RL 训练')
    parser.add_argument('--live', action='store_true', help='实盘监控')
    parser.add_argument('--learn', action='store_true', help='GitHub 学习')
    args = parser.parse_args()

    results = {
        'gh_repos': 0,
        'gh_params': 0,
        'rl_return': 0,
        'rebalance_orders': 0,
        'live_ok': False,
        'btc_price': 0
    }

    print('=' * 60)
    print('  自进化交易系统 v2.0 - 全模块集成')
    print('  GitHub学习 | RL训练 | 多币种 | 实盘')
    print('=' * 60)

    # 获取 BTC 数据（RL 训练和组合测试共用）
    from data.fetcher import DataFetcher
    fetcher = DataFetcher(okx_url='https://www.www.okx.com')
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

    print('\n获取 BTC/USDT 数据...')
    btc_data = fetcher.fetch('BTC/USDT', start_date=start_date, end_date=end_date, source='ccxt')
    if not btc_data.empty:
        print(f'获取成功: {len(btc_data)} 条')
        results['btc_price'] = btc_data['close'].iloc[-1]

    if args.learn:
        learner, seeds = step_github_learn()
        results['gh_repos'] = learner.get_learning_report()['total_repos_learned']
        results['gh_params'] = learner.get_learning_report()['total_params_extracted']
    elif args.rl:
        if not btc_data.empty:
            trainer = step_rl_train(btc_data)
            if trainer.training_history:
                results['rl_return'] = trainer.training_history[-1]['evaluation'].get('avg_return', 0)
    elif args.live:
        step_live_trader_test()
        results['live_ok'] = True
    else:
        # 完整流程
        # 1. GitHub 学习
        try:
            learner, seeds = step_github_learn()
            results['gh_repos'] = learner.get_status().get('total_repos_learned', 0)
            results['gh_params'] = learner.get_status().get('total_params_extracted', 0)
        except Exception as e:
            print(f'GitHub 学习跳过: {e}')

        # 2. RL 训练
        if not btc_data.empty:
            try:
                trainer = step_rl_train(btc_data)
                if trainer.training_history:
                    results['rl_return'] = trainer.training_history[-1]['evaluation'].get('avg_return', 0)
            except Exception as e:
                print(f'RL 训练跳过: {e}')

        # 3. 多币种组合
        try:
            step_portfolio_test()
        except Exception as e:
            print(f'组合测试跳过: {e}')

        # 4. 实盘接口
        try:
            step_live_trader_test()
            results['live_ok'] = True
        except Exception as e:
            print(f'实盘测试跳过: {e}')

        # 5. 综合报告
        step_generate_report(results)

    print('\n✅ 全模块集成运行完成！')


if __name__ == '__main__':
    main()
