"""
自进化交易系统 - 主入口

多Agent协同 / GitHub学习 / 400轮迭代 / 7天内化

使用方法：
    python main.py                    # 交互模式
    python main.py --evolve           # 启动进化循环
    python main.py --backtest         # 运行回测
    python main.py --live             # 实盘监控模式
"""

import argparse
import logging
import sys
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('reports/system.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


def setup_environment():
    """初始化运行环境"""
    # 确保必要目录存在
    dirs = ['memory', 'reports', 'evaluation/traces', 'benchmarks']
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)

    logger.info("运行环境初始化完成")


def run_interactive():
    """交互模式 - 逐步引导用户配置和运行系统"""
    print("\n" + "=" * 60)
    print("  自进化交易系统 v1.0")
    print("  多Agent协同 | 400轮迭代 | 7天内化")
    print("=" * 60)

    print("\n可用模块:")
    print("  1. 数据采集 - 获取市场数据")
    print("  2. 策略回测 - 评估策略表现")
    print("  3. 自进化循环 - 启动策略进化")
    print("  4. Agent 协同 - 多Agent分析")
    print("  5. 系统状态 - 查看运行状态")
    print("  0. 退出")

    while True:
        try:
            choice = input("\n请选择功能 [0-5]: ").strip()

            if choice == '1':
                run_data_demo()
            elif choice == '2':
                run_backtest_demo()
            elif choice == '3':
                run_evolution_demo()
            elif choice == '4':
                run_agent_demo()
            elif choice == '5':
                show_system_status()
            elif choice == '0':
                print("再见！")
                break
            else:
                print("无效选择，请重新输入")
        except KeyboardInterrupt:
            print("\n再见！")
            break
        except Exception as e:
            logger.error(f"运行出错: {e}")


def run_data_demo():
    """数据采集演示"""
    print("\n--- 数据采集演示 ---")
    try:
        from data.fetcher import DataFetcher

        fetcher = DataFetcher()

        # 尝试获取上证指数数据
        print("正在获取 000001（平安银行）近30天数据...")
        df = fetcher.fetch('000001', source='akshare')

        if not df.empty:
            print(f"获取成功！数据行数: {len(df)}")
            print(f"日期范围: {df.index[0]} ~ {df.index[-1]}")
            print("\n最近5天行情:")
            print(df.tail())
        else:
            print("数据获取失败，请检查网络连接")
    except ImportError as e:
        print(f"缺少依赖: {e}")
    except Exception as e:
        print(f"运行出错: {e}")


def run_backtest_demo():
    """策略回测演示"""
    print("\n--- 策略回测演示 ---")
    try:
        import numpy as np
        import pandas as pd

        from strategies.base_strategy import BaseStrategy, StrategyConfig

        # 生成模拟数据
        print("生成模拟数据用于回测演示...")
        dates = pd.date_range('2024-01-01', periods=252, freq='B')
        np.random.seed(42)
        price = 100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.02, 252)))

        mock_data = pd.DataFrame({
            'open': price * (1 + np.random.normal(0, 0.005, 252)),
            'high': price * (1 + abs(np.random.normal(0, 0.01, 252))),
            'low': price * (1 - abs(np.random.normal(0, 0.01, 252))),
            'close': price,
            'volume': np.random.randint(1000000, 10000000, 252)
        }, index=dates)

        # 创建策略实例
        config = StrategyConfig(
            name="DemoStrategy",
            symbols=["TEST"],
            initial_capital=100000
        )

        class DemoStrategy(BaseStrategy):
            def generate_signals(self, data):
                signals = []
                for symbol, df in data.items():
                    df = self.calculate_indicators(df)
                    latest = df.iloc[-1]

                    if latest['rsi'] < 30:
                        signals.append({
                            'symbol': symbol,
                            'side': 'buy',
                            'quantity': 1000,
                            'confidence': 0.7
                        })
                    elif latest['rsi'] > 70:
                        signals.append({
                            'symbol': symbol,
                            'side': 'sell',
                            'quantity': 1000,
                            'confidence': 0.7
                        })
                return signals

        strategy = DemoStrategy(config)
        signals = strategy.generate_signals({'TEST': mock_data})
        trades = strategy._simulate_trades(signals, {'TEST': mock_data})
        result = strategy.calculate_performance(trades)

        print("\n回测结果:")
        print(f"  总收益率: {result.total_return:.2%}")
        print(f"  夏普比率: {result.sharpe_ratio:.2f}")
        print(f"  最大回撤: {result.max_drawdown:.2%}")
        print(f"  胜率: {result.win_rate:.2%}")
        print(f"  交易次数: {result.total_trades}")
        print(f"  盈亏比: {result.profit_factor:.2f}")

    except Exception as e:
        print(f"运行出错: {e}")


def run_evolution_demo():
    """自进化循环演示"""
    print("\n--- 自进化循环演示 ---")
    try:
        import random

        from evolution.learning_loop import EvolutionConfig, EvolutionEngine

        # 创建进化引擎
        config = EvolutionConfig(
            population_size=20,
            max_generations=50,  # 演示用，实际应为 400
            elite_count=3,
            mutation_rate=0.1
        )

        engine = EvolutionEngine(config=config)

        # 定义适应度函数（演示用）
        def fitness_func(gene, data):
            """简单的适应度函数：参数越接近目标值越好"""
            target = {'rsi_period': 14, 'sma_fast': 5, 'sma_slow': 20}
            score = 0
            for key, target_val in target.items():
                actual = gene.params.get(key, 0)
                score += max(0, 1 - abs(actual - target_val) / target_val)
            return score / len(target) + random.uniform(-0.05, 0.05)

        # 参数模板
        param_template = {
            'rsi_period': (5, 30),
            'sma_fast': (3, 15),
            'sma_slow': (10, 50),
            'stop_loss': (0.01, 0.1),
            'take_profit': (0.05, 0.3)
        }

        print(f"开始进化，共 {config.max_generations} 轮...")

        def progress_callback(gen, best, population):
            if gen % 10 == 0:
                avg_fitness = sum(g.fitness for g in population) / len(population)
                print(f"  第 {gen:3d} 代 | 最优: {best.fitness:.4f} | 平均: {avg_fitness:.4f}")

        best = engine.run_evolution(
            fitness_func=fitness_func,
            data=None,
            param_template=param_template,
            callback=progress_callback
        )

        print("\n进化完成！")
        print(f"最优参数: {best.params}")
        print(f"最优适应度: {best.fitness:.4f}")

        report = engine.get_evolution_report()
        print(f"总代数: {report['total_generations']}")
        print(f"精英数量: {report['elite_count']}")
        print(f"已内化策略: {report['internalized_count']}")

    except Exception as e:
        print(f"运行出错: {e}")


def run_agent_demo():
    """多Agent协同演示"""
    print("\n--- 多Agent协同演示 ---")
    try:
        import numpy as np
        import pandas as pd

        from agents.researcher import ResearcherAgent
        from agents.risk_manager import RiskManagerAgent
        from agents.trader import TraderAgent

        # 生成模拟数据
        dates = pd.date_range('2024-01-01', periods=100, freq='B')
        np.random.seed(42)
        price = 50 * np.exp(np.cumsum(np.random.normal(0.001, 0.02, 100)))

        mock_data = pd.DataFrame({
            'open': price * (1 + np.random.normal(0, 0.005, 100)),
            'high': price * (1 + abs(np.random.normal(0, 0.01, 100))),
            'low': price * (1 - abs(np.random.normal(0, 0.01, 100))),
            'close': price,
            'volume': np.random.randint(1000000, 10000000, 100)
        }, index=dates)

        # 初始化 Agent
        researcher = ResearcherAgent(verbose=False)
        trader = TraderAgent(initial_capital=100000)
        risk_mgr = RiskManagerAgent()

        print("Agent 初始化完成")
        print("  - 研究员: 就绪")
        print(f"  - 交易员: 就绪 (资金: {trader.capital:,.0f})")
        print("  - 风控员: 就绪")

        # 执行分析流程
        print("\n执行分析流程...")

        # Step 1: 研究员分析
        analysis = researcher.analyze('TEST', mock_data)
        print("\n[研究员] 分析结果:")
        print(f"  趋势: {analysis['trend']}")
        print(f"  建议: {analysis['recommendation']}")
        print(f"  置信度: {analysis['confidence']:.2%}")
        print(f"  RSI: {analysis['signals']['rsi']}")

        # Step 2: 风控审批
        portfolio = trader.get_portfolio_summary()
        approved, reason = risk_mgr.approve_trade(analysis, portfolio)
        print(f"\n[风控员] 审批结果: {'通过' if approved else '拒绝'}")
        print(f"  原因: {reason}")

        # Step 3: 交易执行
        if approved:
            order = trader.execute_signal(analysis)
            if order:
                print("\n[交易员] 订单已生成:")
                print(f"  标的: {order.symbol}")
                print(f"  方向: {order.side}")
                print(f"  数量: {order.quantity}")

                # 模拟成交
                fill_price = mock_data['close'].iloc[-1]
                trader.update_position(order, fill_price)
                risk_mgr.set_stop_levels(order.symbol, fill_price)

                print(f"  成交价: {fill_price:.2f}")
                print(f"  止损价: {risk_mgr.stop_loss_levels.get(order.symbol, 'N/A')}")
                print(f"  止盈价: {risk_mgr.take_profit_levels.get(order.symbol, 'N/A')}")

        # 组合摘要
        summary = trader.get_portfolio_summary()
        print("\n[投资组合]")
        print(f"  总资产: {summary['total_value']:,.2f}")
        print(f"  持仓数: {summary['position_count']}")
        print(f"  总收益: {summary['total_return']:.2%}")

    except Exception as e:
        print(f"运行出错: {e}")


def show_system_status():
    """显示系统状态"""
    print("\n--- 系统状态 ---")

    # 检查各模块
    modules = {
        'agents': '多Agent协同模块',
        'strategies': '策略模块',
        'evolution': '自进化引擎',
        'data': '数据采集模块'
    }

    for module, desc in modules.items():
        path = Path(module)
        if path.exists():
            files = list(path.glob('*.py'))
            print(f"  ✅ {desc}: {len(files)} 个文件")
        else:
            print(f"  ❌ {desc}: 未找到")

    # 检查依赖
    print("\n依赖检查:")
    deps = [
        ('crewai', '多Agent框架'),
        ('langchain', 'LLM框架'),
        ('backtrader', '回测框架'),
        ('akshare', 'A股数据'),
        ('yfinance', '全球数据'),
        ('pandas', '数据处理'),
        ('numpy', '数值计算')
    ]

    for dep, desc in deps:
        try:
            __import__(dep.replace('-', '_'))
            print(f"  ✅ {desc} ({dep})")
        except ImportError:
            print(f"  ⚠️ {desc} ({dep}) - 未安装")

    # 内存使用
    print("\n记忆系统:")
    memory_path = Path('memory')
    if memory_path.exists():
        for subdir in memory_path.iterdir():
            if subdir.is_dir():
                file_count = len(list(subdir.glob('*')))
                print(f"  📁 {subdir.name}: {file_count} 个文件")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='自进化交易系统 - 多Agent协同 / 400轮迭代 / 7天内化'
    )
    parser.add_argument(
        '--evolve', action='store_true',
        help='启动进化循环'
    )
    parser.add_argument(
        '--backtest', action='store_true',
        help='运行回测'
    )
    parser.add_argument(
        '--live', action='store_true',
        help='实盘监控模式'
    )
    parser.add_argument(
        '--status', action='store_true',
        help='显示系统状态'
    )

    args = parser.parse_args()

    setup_environment()

    if args.status:
        show_system_status()
    elif args.evolve:
        run_evolution_demo()
    elif args.backtest:
        run_backtest_demo()
    elif args.live:
        print("实盘监控模式开发中...")
    else:
        run_interactive()


if __name__ == '__main__':
    main()
