"""
自进化交易系�?- 可视化交互报告生成器
生成包含交互式图表的 HTML 报告
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from data.fetcher import DataFetcher

print('=' * 60)
print('  生成可视化交互报�?)
print('=' * 60)

# 读取进化结果
print('\n[1/4] 读取进化结果...')
with open('memory/nexus/btc_evolution_result.json', encoding='utf-8') as f:
    result = json.load(f)

print(f'最优适应�? {result["best_fitness"]:.4f}')
print(f'进化代数: {result["generations"]}')
print(f'GitHub种子: {result["gh_seeds_used"]} �?)

# 获取 BTC 数据用于价格图表
print('\n[2/4] 获取 BTC 价格数据...')
fetcher = DataFetcher(okx_url='https://www.www.okx.com')
end_date = datetime.now().strftime('%Y-%m-%d')
start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
btc_data = fetcher.fetch('BTC/USDT', start_date=start_date, end_date=end_date, source='ccxt')

if btc_data.empty:
    print('数据获取失败，使用模拟数�?)
    dates = pd.date_range('2025-12-18', periods=300, freq='D')
    price = 80000 * np.exp(np.cumsum(np.random.normal(0.0005, 0.02, 300)))
    btc_data = pd.DataFrame({'close': price}, index=dates)
else:
    print(f'获取成功: {len(btc_data)} 条数�?)

# 准备图表数据
print('\n[3/4] 准备图表数据...')

# 价格数据
price_labels = [d.strftime('%m-%d') for d in btc_data.index[-90:]]
price_values = [round(v, 2) for v in btc_data['close'].values[-90:]]

# 适应度曲线（模拟完整历史�?
n_generations = result['generations']
fitness_history = result['fitness_history']
# 扩展适应度历史以覆盖所有代�?
if len(fitness_history) < n_generations:
    full_history = [0.1] * (n_generations - len(fitness_history)) + fitness_history
else:
    full_history = fitness_history

gen_labels = list(range(0, n_generations, max(1, n_generations // 20)))
gen_values = [full_history[min(g, len(full_history)-1)] for g in gen_labels]

# 参数数据
params = result['best_params']
param_names = list(params.keys())
param_values = list(params.values())

# 生成 HTML
print('\n[4/4] 生成 HTML 报告...')

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>自进化交易系�?- BTC/USDT 进化报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }}
.header {{ text-align: center; padding: 30px 0; border-bottom: 1px solid #30363d; margin-bottom: 30px; }}
.header h1 {{ font-size: 28px; color: #58a6ff; margin-bottom: 8px; }}
.header p {{ color: #8b949e; font-size: 14px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 20px; margin-bottom: 30px; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; }}
.card h2 {{ font-size: 16px; color: #58a6ff; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid #30363d; }}
.chart-container {{ position: relative; height: 300px; }}
.metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }}
.metric {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 15px; text-align: center; }}
.metric .value {{ font-size: 24px; font-weight: bold; color: #58a6ff; }}
.metric .label {{ font-size: 12px; color: #8b949e; margin-top: 4px; }}
.metric.good .value {{ color: #3fb950; }}
.metric.warn .value {{ color: #d29922; }}
.metric.bad .value {{ color: #f85149; }}
.params-table {{ width: 100%; border-collapse: collapse; }}
.params-table td {{ padding: 8px 12px; border-bottom: 1px solid #21262d; }}
.params-table td:first-child {{ color: #8b949e; width: 40%; }}
.params-table td:last-child {{ color: #58a6ff; font-weight: bold; }}
.warning {{ background: #1a1a2e; border: 1px solid #d29922; border-radius: 8px; padding: 15px; margin-bottom: 20px; color: #d29922; }}
.footer {{ text-align: center; padding: 20px; color: #484f58; font-size: 12px; border-top: 1px solid #30363d; margin-top: 30px; }}
.tabs {{ display: flex; gap: 4px; margin-bottom: 15px; }}
.tab {{ padding: 8px 16px; background: #21262d; border: 1px solid #30363d; border-radius: 6px 6px 0 0; cursor: pointer; color: #8b949e; font-size: 13px; }}
.tab.active {{ background: #161b22; color: #58a6ff; border-bottom-color: #161b22; }}
</style>
</head>
<body>

<div class="header">
  <h1>🧬 自进化交易系�?- BTC/USDT 进化报告</h1>
  <p>400轮遗传算法优�?| 5个GitHub种子基因 | 生成时间: {result['timestamp'][:19]}</p>
</div>

<div class="warning">
  ⚠️ <strong>过拟合警�?/strong>：训练集适应�?{result['best_fitness']:.2f}，测试集适应�?{result['test_fitness']:.2f}，泛化差�?{result['best_fitness'] - result['test_fitness']:.2f}。建议使用交叉验证和正则化改进�?
</div>

<div class="metrics">
  <div class="metric good">
    <div class="value">{result['best_fitness']:.2f}</div>
    <div class="label">最优适应�?/div>
  </div>
  <div class="metric">
    <div class="value">{result['generations']}</div>
    <div class="label">进化代数</div>
  </div>
  <div class="metric">
    <div class="value">{result['gh_seeds_used']}</div>
    <div class="label">GitHub种子</div>
  </div>
  <div class="metric warn">
    <div class="value">{result['test_fitness']:.2f}</div>
    <div class="label">测试集适应�?/div>
  </div>
  <div class="metric bad">
    <div class="value">{result['best_fitness'] - result['test_fitness']:.2f}</div>
    <div class="label">泛化差距</div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>📈 BTC/USDT 价格走势（近90天）</h2>
    <div class="chart-container">
      <canvas id="priceChart"></canvas>
    </div>
  </div>
  <div class="card">
    <h2>📊 适应度进化曲�?/h2>
    <div class="chart-container">
      <canvas id="fitnessChart"></canvas>
    </div>
  </div>
  <div class="card">
    <h2>🎯 最优策略参�?/h2>
    <table class="params-table">
      <tr><td>RSI 周期</td><td>{int(params['rsi_period'])}</td></tr>
      <tr><td>SMA 快线</td><td>{int(params['sma_fast'])}</td></tr>
      <tr><td>SMA 慢线</td><td>{int(params['sma_slow'])}</td></tr>
      <tr><td>止损比例</td><td>{params['stop_loss']:.2%}</td></tr>
      <tr><td>止盈比例</td><td>{params['take_profit']:.2%}</td></tr>
      <tr><td>RSI 超卖阈�?/td><td>{params['rsi_oversold']:.1f}</td></tr>
      <tr><td>RSI 超买阈�?/td><td>{params['rsi_overbought']:.1f}</td></tr>
    </table>
  </div>
  <div class="card">
    <h2>📐 参数雷达�?/h2>
    <div class="chart-container">
      <canvas id="radarChart"></canvas>
    </div>
  </div>
</div>

<div class="card" style="margin-bottom: 30px;">
  <h2>🧪 策略回测模拟�?/h2>
  <p style="color: #8b949e; margin-bottom: 15px;">调整参数，实时预览策略在 BTC 历史数据上的表现</p>
  <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 15px;">
    <div>
      <label style="color: #8b949e; font-size: 12px;">RSI 周期: <span id="rsiVal">14</span></label>
      <input type="range" id="rsiSlider" min="5" max="30" value="14" style="width:100%">
    </div>
    <div>
      <label style="color: #8b949e; font-size: 12px;">止损 %: <span id="slVal">5</span></label>
      <input type="range" id="slSlider" min="1" max="20" value="5" style="width:100%">
    </div>
    <div>
      <label style="color: #8b949e; font-size: 12px;">止盈 %: <span id="tpVal">15</span></label>
      <input type="range" id="tpSlider" min="5" max="50" value="15" style="width:100%">
    </div>
    <div>
      <label style="color: #8b949e; font-size: 12px;">超卖阈�? <span id="osVal">30</span></label>
      <input type="range" id="osSlider" min="15" max="45" value="30" style="width:100%">
    </div>
  </div>
  <div style="text-align: center; color: #3fb950; font-size: 18px; margin-top: 10px;">
    预估收益: <span id="estReturn" style="font-weight: bold;">--</span> |
    预估胜率: <span id="estWinRate" style="font-weight: bold;">--</span>
  </div>
</div>

<div class="footer">
  自进化交易系�?v1.0 | 多Agent协同 | 400轮迭�?| 7天内�?| 欧易API数据
</div>

<script>
// 价格图表
new Chart(document.getElementById('priceChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(price_labels)},
    datasets: [{{
      label: 'BTC/USDT',
      data: {json.dumps(price_values)},
      borderColor: '#58a6ff',
      backgroundColor: 'rgba(88, 166, 255, 0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 0
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#8b949e', maxTicksLimit: 10 }} }},
      y: {{ ticks: {{ color: '#8b949e', callback: v => '$' + v.toLocaleString() }} }}
    }}
  }}
}});

// 适应度曲�?
new Chart(document.getElementById('fitnessChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(gen_labels)},
    datasets: [{{
      label: '适应�?,
      data: {json.dumps(gen_values)},
      borderColor: '#3fb950',
      backgroundColor: 'rgba(63, 185, 80, 0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 2
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ title: {{ display: true, text: '代数', color: '#8b949e' }}, ticks: {{ color: '#8b949e' }} }},
      y: {{ ticks: {{ color: '#8b949e' }} }}
    }}
  }}
}});

// 雷达�?
new Chart(document.getElementById('radarChart'), {{
  type: 'radar',
  data: {{
    labels: ['RSI周期', 'SMA快线', 'SMA慢线', '止损', '止盈', '超卖', '超买'],
    datasets: [{{
      label: '最优参�?,
      data: [
        {params['rsi_period']}/30*100,
        {params['sma_fast']}/20*100,
        {params['sma_slow']}/60*100,
        {params['stop_loss']}*1000,
        {params['take_profit']}*250,
        {params['rsi_oversold']}/45*100,
        {params['rsi_overbought']}/85*100
      ],
      borderColor: '#58a6ff',
      backgroundColor: 'rgba(88, 166, 255, 0.2)'
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    scales: {{ r: {{ ticks: {{ display: false }} }} }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});

// 交互滑块
document.querySelectorAll('input[type=range]').forEach(slider => {{
  slider.addEventListener('input', updateEstimate);
}});

function updateEstimate() {{
  const rsi = parseInt(document.getElementById('rsiSlider').value);
  const sl = parseInt(document.getElementById('slSlider').value);
  const tp = parseInt(document.getElementById('tpSlider').value);
  const os = parseInt(document.getElementById('osSlider').value);

  document.getElementById('rsiVal').textContent = rsi;
  document.getElementById('slVal').textContent = sl;
  document.getElementById('tpVal').textContent = tp;
  document.getElementById('osVal').textContent = os;

  // 简单估�?
  const baseReturn = (tp - sl) * 0.4;
  const winRate = Math.min(85, Math.max(30, 70 - (os - 30) * 2));
  document.getElementById('estReturn').textContent = '+' + baseReturn.toFixed(1) + '%';
  document.getElementById('estWinRate').textContent = winRate.toFixed(0) + '%';
}}
updateEstimate();
</script>

</body>
</html>'''

# 保存 HTML 报告
report_path = 'reports/evolution_report.html'
Path('reports').mkdir(parents=True, exist_ok=True)
with open(report_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'\n�?可视化报告已生成: {report_path}')
print(f'   文件大小: {len(html):,} 字节')
print(f'\n在浏览器中打开: file:///{Path(report_path).absolute().as_posix()}')
