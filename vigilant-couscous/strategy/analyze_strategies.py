"""
批量分析 GitHub 策略文件，提取可复用参数
"""
import json
import re
from datetime import datetime
from pathlib import Path

STRATEGY_DIR = Path('gh_repos/freqtrade-strategies/user_data/strategies')

print('=' * 60)
print('  批量分析 GitHub 策略文件')
print('=' * 60)

# 收集所有策略文件
py_files = list(STRATEGY_DIR.rglob('*.py'))
print(f'\n找到 {len(py_files)} 个策略文件')

all_params = []

for fpath in py_files:
    try:
        content = fpath.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        continue

    params = {'file': str(fpath.relative_to(STRATEGY_DIR))}

    # 提取止损
    m = re.search(r'stoploss\s*=\s*(-?\d+\.?\d*)', content)
    if m:
        params['stoploss'] = float(m.group(1))

    # 提取 trailing_stop
    m = re.search(r'trailing_stop\s*=\s*(True|False)', content)
    if m:
        params['trailing_stop'] = m.group(1) == 'True'

    # 提取 ROI
    roi_match = re.search(r'minimal_roi\s*=\s*\{([^}]+)\}', content, re.DOTALL)
    if roi_match:
        roi_str = roi_match.group(1)
        roi_items = re.findall(r'"(\d+)"\s*:\s*(-?\d+\.?\d*)', roi_str)
        if roi_items:
            params['roi'] = {int(k): float(v) for k, v in roi_items}

    # 提取时间框架
    m = re.search(r'timeframe\s*=\s*["\'](\w+)["\']', content)
    if m:
        params['timeframe'] = m.group(1)

    # 提取 RSI 相关
    rsi_vals = re.findall(r'rsi[\s=:]*\{?[\s"\']*(\d+)', content, re.IGNORECASE)
    if rsi_vals:
        params['rsi_values'] = [int(v) for v in rsi_vals[:3]]

    # 提取 SMA/EMA 周期
    sma_vals = re.findall(r'(?:sma|ema)[\s=:(]*?(\d+)', content, re.IGNORECASE)
    if sma_vals:
        params['sma_values'] = [int(v) for v in sma_vals[:5]]

    # 提取 MACD
    macd_vals = re.findall(r'macd[\s=:(]*?(\d+)', content, re.IGNORECASE)
    if macd_vals:
        params['macd_values'] = [int(v) for v in macd_vals[:3]]

    # 提取 buy/sell 信号参数
    buy_params = re.findall(r'buy[_\s]*(\w+)[\s=:]*["\']?([^"\'\n,]+)', content, re.IGNORECASE)
    if buy_params:
        params['buy_signals'] = {k: v.strip() for k, v in buy_params[:5]}

    # 提取 ATR
    atr_vals = re.findall(r'atr[\s=:(]*?(\d+)', content, re.IGNORECASE)
    if atr_vals:
        params['atr_values'] = [int(v) for v in atr_vals[:3]]

    # 提取 BB（布林带）
    bb_vals = re.findall(r'(?:bb|bollinger)[\s=:(]*?(\d+)', content, re.IGNORECASE)
    if bb_vals:
        params['bb_values'] = [int(v) for v in bb_vals[:3]]

    # 只保留有实际参数的
    if len(params) > 1:  # 除了 file 还有其他参数
        all_params.append(params)

# 统计
print(f'\n提取到 {len(all_params)} 个策略的参数')

# 汇总统计
stoplosses = [p['stoploss'] for p in all_params if 'stoploss' in p]
rsi_all = []
for p in all_params:
    if 'rsi_values' in p:
        rsi_all.extend(p['rsi_values'])
sma_all = []
for p in all_params:
    if 'sma_values' in p:
        sma_all.extend(p['sma_values'])

print('\n📊 参数统计:')
if stoplosses:
    print(f'  止损范围: {min(stoplosses):.3f} ~ {max(stoplosses):.3f}, 均值: {sum(stoplosses)/len(stoplosses):.3f}')
if rsi_all:
    from collections import Counter
    rsi_counter = Counter(rsi_all)
    print(f'  RSI 常用值: {rsi_counter.most_common(5)}')
if sma_all:
    sma_counter = Counter(sma_all)
    print(f'  SMA 常用值: {sma_counter.most_common(5)}')

# 生成策略参数库
strategy_lib = []
for p in all_params:
    entry = {
        'name': p['file'].replace('.py', '').replace('\\', '/'),
        'source': 'freqtrade-strategies',
    }
    if 'stoploss' in p:
        entry['stop_loss'] = abs(p['stoploss'])
    if 'rsi_values' in p:
        entry['rsi_period'] = p['rsi_values'][0]
    if 'sma_values' in p and len(p['sma_values']) >= 2:
        entry['sma_fast'] = min(p['sma_values'][:2])
        entry['sma_slow'] = max(p['sma_values'][:2])
    elif 'sma_values' in p:
        entry['sma_fast'] = 5
        entry['sma_slow'] = p['sma_values'][0]
    if 'timeframe' in p:
        entry['timeframe'] = p['timeframe']

    # 补充默认值
    entry.setdefault('rsi_period', 14)
    entry.setdefault('sma_fast', 5)
    entry.setdefault('sma_slow', 20)
    entry.setdefault('stop_loss', 0.05)
    entry.setdefault('take_profit', 0.15)
    entry.setdefault('rsi_oversold', 30)
    entry.setdefault('rsi_overbought', 70)

    strategy_lib.append(entry)

# 保存
output = {
    'timestamp': datetime.now().isoformat(),
    'total_strategies': len(strategy_lib),
    'source': 'freqtrade/freqtrade-strategies',
    'strategies': strategy_lib
}

out_path = Path('memory/nexus/gh_strategy_library.json')
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')

print(f'\n✅ 策略参数库已保存: {out_path}')
print(f'   共 {len(strategy_lib)} 个策略，可直接注入进化引擎')

# 展示前 10 个策略
print('\n📋 前 10 个策略参数:')
for s in strategy_lib[:10]:
    print(f'  {s["name"]}: RSI={s["rsi_period"]}, SMA=({s["sma_fast"]},{s["sma_slow"]}), SL={s["stop_loss"]:.0%}, TP={s["take_profit"]:.0%}')
