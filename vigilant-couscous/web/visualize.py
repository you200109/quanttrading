import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from data.fetcher import DataFetcher

print('=' * 60)
print('  生成可视化交互报告')
print('=' * 60)

# 读取进化结果
print('\n[1/4] 读取进化结果...')
with open('memory/nexus/btc_evolution_result.json', encoding='utf-8') as f:
    result = json.load(f)

print(f'最优适应度: {result["best_fitness"]:.4f}')
print(f'进化代数: {result["generations"]}')
print(f'GitHub种子: {result["gh_seeds_used"]} 个')

# 获取 BTC 数据用于价格图表
print('\n[2/4] 获取 BTC 价格数据...')
fetcher = DataFetcher(okx_url='https://www.okx.com')
end_date = datetime.now().strftime('%Y-%m-%d')
start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
btc_data = fetcher.fetch('BTC/USDT', start_date=start_date, end_date=end_date, source='ccxt')

if btc_data.empty:
    print('数据获取失败，使用模拟数据')
    np.random.seed(42)
    dates = pd.date_range(start=start_date, end=end_date, freq='D')
    btc_data = pd.DataFrame({
        'date': dates,
        'open': np.cumsum(np.random.randn(len(dates)) * 100 + 80000),
        'high': np.cumsum(np.random.randn(len(dates)) * 100 + 81000),
        'low': np.cumsum(np.random.randn(len(dates)) * 100 + 79000),
        'close': np.cumsum(np.random.randn(len(dates)) * 100 + 80000),
        'volume': np.random.randint(100, 10000, len(dates))
    })
else:
    print(f'获取成功: {len(btc_data)} 条数据')

# 生成 HTML 报告
print('\n[3/4] 生成 HTML 报告...')

# 准备图表数据
close_prices = btc_data['close'].tolist()
dates = btc_data['date'].dt.strftime('%Y-%m-%d').tolist() if 'date' in btc_data else [str(i) for i in range(len(close_prices))]

# 进化曲线数据
fitness_history = result.get('fitness_history', [])
best_params = result.get('best_params', {})

html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>自进化交易系统 - 交互报告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            background: linear-gradient(135deg, #0f0f23, #1a1a3e);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }}
        .header {{
            text-align: center;
            padding: 30px 0;
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            margin-bottom: 20px;
        }}
        .header h1 {{
            font-size: 28px;
            background: linear-gradient(90deg, #00d4ff, #7b2ff7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header .subtitle {{ color: #888; margin-top: 8px; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        .card {{
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 20px;
        }}
        .card h2 {{
            font-size: 16px;
            color: #00d4ff;
            margin-bottom: 15px;
        }}
        .chart-container {{ position: relative; height: 300px; }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }}
        .stat-box {{
            background: rgba(255,255,255,0.06);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .stat-box .value {{
            font-size: 28px;
            font-weight: bold;
            color: #00d4ff;
        }}
        .stat-box .label {{
            font-size: 12px;
            color: #888;
            margin-top: 5px;
        }}
        .params-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .params-table td {{
            padding: 8px 12px;
            border-bottom: 1px solid rgba(255,255,255,0.08);
        }}
        .params-table td:first-child {{ color: #888; }}
        .params-table td:last-child {{ color: #00d4ff; font-family: monospace; }}
        .footer {{
            text-align: center;
            color: #555;
            padding: 20px 0;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>自进化交易系统 - 交互报告</h1>
        <div class="subtitle">生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
    </div>

    <div class="stats">
        <div class="stat-box">
            <div class="value">{result["best_fitness"]:.4f}</div>
            <div class="label">最优适应度</div>
        </div>
        <div class="stat-box">
            <div class="value">{result["generations"]}</div>
            <div class="label">进化代数</div>
        </div>
        <div class="stat-box">
            <div class="value">{result["gh_seeds_used"]}</div>
            <div class="label">GitHub种子数</div>
        </div>
        <div class="stat-box">
            <div class="value">${btc_data["close"].iloc[-1]:,.0f}</div>
            <div class="label">BTC最新价</div>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <h2>BTC/USDT 价格走势</h2>
            <div class="chart-container">
                <canvas id="priceChart"></canvas>
            </div>
        </div>
        <div class="card">
            <h2>进化适应度曲线</h2>
            <div class="chart-container">
                <canvas id="fitnessChart"></canvas>
            </div>
        </div>
    </div>

    <div class="card" style="margin-bottom: 20px;">
        <h2>最优策略参数</h2>
        <table class="params-table">
            {''.join(f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in best_params.items())}
        </table>
    </div>

    <div class="footer">
        自进化交易系统 v2.0 | 数据来源: OKX | 报告生成: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    </div>

    <script>
        // 价格图表
        new Chart(document.getElementById('priceChart'), {{
            type: 'line',
            data: {{
                labels: {json.dumps(dates[-60:])},
                datasets: [{{
                    label: 'BTC/USDT 收盘价',
                    data: {json.dumps(close_prices[-60:])},
                    borderColor: '#00d4ff',
                    backgroundColor: 'rgba(0, 212, 255, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ labels: {{ color: '#e0e0e0' }} }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#888', maxTicksLimit: 10 }} }},
                    y: {{ ticks: {{ color: '#888' }} }}
                }}
            }}
        }});

        // 适应度图表
        new Chart(document.getElementById('fitnessChart'), {{
            type: 'line',
            data: {{
                labels: {json.dumps([f'Gen {i+1}' for i in range(len(fitness_history))])},
                datasets: [{{
                    label: '最优适应度',
                    data: {json.dumps(fitness_history)},
                    borderColor: '#7b2ff7',
                    backgroundColor: 'rgba(123, 47, 247, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ labels: {{ color: '#e0e0e0' }} }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#888', maxTicksLimit: 10 }} }},
                    y: {{ ticks: {{ color: '#888' }} }}
                }}
            }}
        }});
    </script>
</body>
</html>'''

# 保存报告
print('\n[4/4] 保存报告...')
report_dir = Path('reports')
report_dir.mkdir(parents=True, exist_ok=True)
report_file = report_dir / f'evolution_report_{datetime.now().strftime("%Y%m%d_%H%M")}.html'
with open(report_file, 'w', encoding='utf-8') as f:
    f.write(html_content)
print(f'\n✅ 报告已保存: {report_file}')
print(f'   文件大小: {report_file.stat().st_size / 1024:.1f} KB')
