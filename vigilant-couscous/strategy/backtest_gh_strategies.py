"""
GitHub 策略批量回测 - 68 个策略在 BTC 真实数据上验�?
"""
import json
import logging
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

print('=' * 60)
print('  GitHub 策略批量回测 - BTC/USDT 真实数据')
print('=' * 60)

# 加载策略�?
with open('memory/nexus/gh_strategy_library.json', encoding='utf-8') as f:
    lib = json.load(f)
strategies = lib['strategies']
print(f'\n加载 {len(strategies)} 个策�?)

# 获取 BTC 数据
from data.fetcher import DataFetcher

fetcher = DataFetcher(okx_url='https://www.www.okx.com')
end_date = datetime.now().strftime('%Y-%m-%d')
start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
btc_data = fetcher.fetch('BTC/USDT', start_date=start_date, end_date=end_date, source='ccxt')
print(f'BTC 数据: {len(btc_data)} �? 最新价: ${btc_data["close"].iloc[-1]:,.2f}')

close = btc_data['close'].values
n = len(close)

# 回测函数
def backtest(params, data):
    close = data
    n = len(close)
    rsi_period = int(params.get('rsi_period', 14))
    sma_fast = int(params.get('sma_fast', 5))
    sma_slow = int(params.get('sma_slow', 20))
    stop_loss = params.get('stop_loss', 0.05)
    take_profit = params.get('take_profit', 0.15)
    rsi_oversold = params.get('rsi_oversold', 30)
    rsi_overbought = params.get('rsi_overbought', 70)

    if n < sma_slow + 1:
        return {'total_return': 0, 'trades': 0, 'win_rate': 0, 'sharpe': 0, 'max_dd': 0}

    # RSI
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = np.array([np.mean(gain[max(0, i-rsi_period+1):i+1]) for i in range(n)])
    avg_loss = np.array([np.mean(loss[max(0, i-rsi_period+1):i+1]) for i in range(n)])
    rs = np.divide(avg_gain, avg_loss, out=np.ones(n)*100, where=avg_loss!=0)
    rsi = 100 - (100 / (1 + rs))

    # SMA
    sma_f = pd.Series(close).rolling(sma_fast).mean().values
    sma_s = pd.Series(close).rolling(sma_slow).mean().values

    capital = 100000
    position = 0
    entry_price = 0
    trades = []

    for i in range(sma_slow, n):
        price = close[i]
        if position > 0:
            pnl_pct = (price - entry_price) / entry_price
            if pnl_pct <= -stop_loss or pnl_pct >= take_profit:
                capital += position * price
                trades.append(pnl_pct)
                position = 0
                continue
        if position == 0 and not np.isnan(sma_f[i]) and not np.isnan(sma_s[i]):
            rsi_signal = rsi[i] < rsi_oversold
            sma_signal = sma_f[i] > sma_s[i] and sma_f[i-1] <= sma_s[i-1]
            if rsi_signal or sma_signal:
                confidence = 0.85 if (rsi_signal and sma_signal) else 0.65
                position_size = capital * 0.2 * confidence
                position = position_size / price
                entry_price = price
                capital -= position_size
        elif position > 0 and not np.isnan(sma_f[i]) and not np.isnan(sma_s[i]):
            rsi_signal = rsi[i] > rsi_overbought
            sma_signal = sma_f[i] < sma_s[i] and sma_f[i-1] >= sma_s[i-1]
            if rsi_signal or sma_signal:
                pnl_pct = (price - entry_price) / entry_price
                capital += position * price
                trades.append(pnl_pct)
                position = 0
    if position > 0:
        pnl_pct = (close[-1] - entry_price) / entry_price
        capital += position * close[-1]
        trades.append(pnl_pct)

    if len(trades) < 2:
        return {'total_return': (capital-100000)/100000, 'trades': len(trades), 'win_rate': 0, 'sharpe': 0, 'max_dd': 0}

    total_return = (capital - 100000) / 100000
    win_rate = sum(1 for t in trades if t > 0) / len(trades)
    avg_ret = np.mean(trades)
    std_ret = np.std(trades) if len(trades) > 1 else 0.01
    sharpe = (avg_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0
    cumulative = np.cumprod(1 + np.array(trades))
    running_max = np.maximum.accumulate(cumulative)
    max_dd = np.max((running_max - cumulative) / (running_max + 1e-8))

    return {'total_return': total_return, 'trades': len(trades), 'win_rate': win_rate, 'sharpe': sharpe, 'max_dd': max_dd}

# 批量回测
print(f'\n回测 {len(strategies)} 个策�?..')
results = []
for i, s in enumerate(strategies):
    r = backtest(s, close)
    r['name'] = s['name']
    r['params'] = {k: v for k, v in s.items() if k != 'name'}
    results.append(r)
    if (i+1) % 20 == 0:
        print(f'  进度: {i+1}/{len(strategies)}')

# 排序
results.sort(key=lambda x: x['total_return'], reverse=True)

# 输出 Top 10
print(f'\n{"=" * 60}')
print('  Top 10 策略（按收益率排序）')
print(f'{"=" * 60}')
for i, r in enumerate(results[:10]):
    print(f'\n  #{i+1} {r["name"]}')
    print(f'    收益�? {r["total_return"]:+.2%} | 交易: {r["trades"]}�?| 胜率: {r["win_rate"]:.0%} | 夏普: {r["sharpe"]:.2f} | 回撤: {r["max_dd"]:.1%}')
    p = r['params']
    print(f'    参数: RSI={p.get("rsi_period","?")}, SMA=({p.get("sma_fast","?")},{p.get("sma_slow","?")}), SL={p.get("stop_loss","?")}, TP={p.get("take_profit","?")}')

# 统计
positive = [r for r in results if r['total_return'] > 0]
traded = [r for r in results if r['trades'] > 0]
print('\n📊 统计:')
print(f'  正收益策�? {len(positive)}/{len(results)} ({len(positive)/len(results)*100:.0f}%)')
print(f'  有交易策�? {len(traded)}/{len(results)}')
if positive:
    print(f'  最佳收�? {results[0]["total_return"]:+.2%}')
    print(f'  平均收益: {np.mean([r["total_return"] for r in positive]):+.2%}')

# 保存结果
output = {
    'timestamp': datetime.now().isoformat(),
    'total_strategies': len(results),
    'positive_strategies': len(positive),
    'top10': results[:10],
    'all_results': results
}
Path('memory/nexus').mkdir(parents=True, exist_ok=True)
with open('memory/nexus/backtest_results.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)
print('\n�?回测结果已保�? memory/nexus/backtest_results.json')
