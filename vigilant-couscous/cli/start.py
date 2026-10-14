"""
自进化交易系统 - 统一入口
所有功能通过本脚本调用，不再散落多个脚本

用法:
    python start.py status      查看系统状态
    python start.py analyze     分析当前行情
    python start.py trade       执行一轮交易
    python start.py auto        自动循环运行
    python start.py evolve      进化优化
    python start.py learn       从GitHub学习策略
    python start.py report      生成可视化报告
"""
import sys

import config


def cmd_status():
    """查看系统状态"""
    print("=" * 60)
    print("  自进化交易系统 - 状态")
    print("=" * 60)

    # 模块检查
    modules = {
        "agents": "多Agent协同",
        "data": "数据采集",
        "evolution": "自进化引擎",
        "strategies": "策略模块",
    }
    print("\n模块:")
    for m, desc in modules.items():
        p = config.ROOT_DIR / m
        cnt = len(list(p.glob("*.py"))) if p.exists() else 0
        print(f"  {'OK' if cnt else '--'} {desc}: {cnt} 个文件")

    # 依赖检查
    print("\n依赖:")
    deps = [("crewai", "多Agent"), ("langchain", "LLM"), ("backtrader", "回测"),
            ("torch", "深度学习"), ("gymnasium", "RL环境"), ("ccxt", "交易所"),
            ("pandas", "数据处理"), ("numpy", "数值计算")]
    for dep, desc in deps:
        try:
            __import__(dep)
            print(f"  OK {desc} ({dep})")
        except ImportError:
            print(f"  -- {desc} ({dep}) 未安装")

    # 数据文件
    print("\n数据:")
    nexus = config.NEXUS_DIR
    for f in ["gh_strategy_library.json", "backtest_results.json", "version.json"]:
        fp = nexus / f
        print(f"  {'OK' if fp.exists() else '--'} {f}")

    print(f"\n配置: 币种={config.SYMBOLS}, 风控阈值={config.RISK['min_confidence']}")


def cmd_analyze():
    """分析当前行情"""
    from datetime import datetime, timedelta

    from agents.researcher import ResearcherAgent
    from data.fetcher import DataFetcher

    fetcher = DataFetcher(okx_url=config.DATA_SOURCE["okx_url"])
    researcher = ResearcherAgent(verbose=False)

    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')

    print("=" * 60)
    print("  行情分析")
    print("=" * 60)

    for symbol in config.SYMBOLS:
        data = fetcher.fetch(symbol, start_date=start, end_date=end, source='ccxt')
        if data.empty:
            print(f"\n{symbol}: 数据获取失败")
            continue

        r = researcher.analyze(symbol, data)
        s = r['signals']
        print(f"\n{symbol}  ${data['close'].iloc[-1]:,.2f}")
        print(f"  趋势: {r['trend']}  建议: {r['recommendation']}  置信度: {r['confidence']:.0%}")
        print(f"  指标数: {s.get('total_indicators', 0)}  RSI14: {s.get('rsi_14')}  ADX: {s.get('adx')}")


def cmd_trade():
    """执行一轮交易"""
    from auto_trade import AutoTradingSystem
    AutoTradingSystem().run_once()


def cmd_auto():
    """自动循环运行"""
    from auto_trade import AutoTradingSystem
    AutoTradingSystem().run_loop(interval_minutes=config.SYSTEM["trade_interval_minutes"])


def cmd_evolve():
    """进化优化（daily/weekly/once 三种模式）"""
    import subprocess
    mode = sys.argv[2] if len(sys.argv) > 2 else "once"
    subprocess.run([sys.executable, "unified_evolve.py", mode])


def cmd_learn():
    """从 GitHub 学习（统一学习引擎）"""
    from learning_engine import LearningEngine
    engine = LearningEngine(token=config.GITHUB["token"])
    cycle = engine.full_cycle()
    print(f"学习完成: 静态新增 {cycle['static_added']} 组")
    for cat, cnt in cycle["discovered"].items():
        print(f"  {cat}: 发现 {cnt} 个")
    print(f"参数入库: {cycle['params_added']} 组")
    print(f"累计仓库: {cycle['total_repos']} | 累计资源: {cycle['total_resources']}")


def cmd_report():
    """生成可视化报告"""
    import subprocess
    subprocess.run([sys.executable, "visualize.py"])


def cmd_hotreload():
    """启动热更新监测，代码或配置改动后即时生效"""
    from hot_reload import HotReloadManager
    mgr = HotReloadManager()
    status = mgr.get_status()
    print(f"热更新监测已启动，共 {status['watching']} 个模块")
    print("保持运行即可自动重载改动，按 Ctrl+C 退出")
    try:
        mgr.start_watch_loop(interval_seconds=3)
    except KeyboardInterrupt:
        print(f"\n热更新已停止，本次共重载 {mgr.reload_count} 次")


def cmd_selfupdate():
    """检查并应用自更新"""
    from self_update import SelfUpdater
    updater = SelfUpdater()
    status = updater.get_status()
    print(f"当前版本: {status['current_version']}")
    print(f"备份数量: {len(status['backups'])}")
    print(f"更新历史: {status['history_count']} 次")
    print("提示: 在 self_update.py 配置 UPDATE_SOURCES 后可自动拉取远端更新")


def cmd_iterate():
    """自动迭代闭环：学习→进化→版本升级→热更新"""
    from auto_iterate import AutoIterator
    it = AutoIterator()
    mode = sys.argv[2] if len(sys.argv) > 2 else "once"
    if mode == "loop":
        hours = float(sys.argv[3]) if len(sys.argv) > 3 else 168
        it.run_loop(interval_hours=hours)
    elif mode == "status":
        import json as _json
        print(_json.dumps(it.status(), indent=2, ensure_ascii=False))
    else:
        it.iterate_once()


COMMANDS = {
    "status": cmd_status,
    "analyze": cmd_analyze,
    "trade": cmd_trade,
    "auto": cmd_auto,
    "evolve": cmd_evolve,
    "learn": cmd_learn,
    "report": cmd_report,
    "hotreload": cmd_hotreload,
    "selfupdate": cmd_selfupdate,
    "iterate": cmd_iterate,
}

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("自进化交易系统 - 统一入口")
        print("\n可用命令:")
        for cmd in COMMANDS:
            print(f"  python start.py {cmd}")
        print()
    else:
        cmd = sys.argv[1]
        if cmd in COMMANDS:
            COMMANDS[cmd]()
        else:
            print(f"未知命令: {cmd}")
            print(f"可用: {', '.join(COMMANDS.keys())}")
