# QuantTrading - 量化交易可视化交互系统

> OKX 实时行情 + 508 技术指标 + AI 交易进化系统 + 20 自动化工作流

## ✨ 功能特性

- 📊 实时行情看板（多品种 Ticker 汇总）
- 📈 交互式 K 线图表（多周期切换 15m/30m/1H/4H）
- 📋 盘口深度数据展示
- 📐 技术指标叠加（508 个指标，基于 pandas-ta）
- ⚙️ 策略参数配置面板（交互式调参）
- 💰 模拟交易 / 实盘交易切换
- 📝 挂单、历史委托、成交明细、账单流水
- 🔄 WebSocket 实时数据推送
- 🤖 AI 交易进化系统（vigilant-couscous）
- ⚙️ 20 个 GitHub Actions 自动化工作流

## 🚀 快速开始

```bash
git clone https://github.com/you200109/quanttrading.git
cd quanttrading
pip install -r requirements.txt
cp .env.example .env  # 填入 OKX API 凭据
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

访问 http://localhost:8000 即可使用。

## 🏗️ 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | Python 3.12 + FastAPI + Uvicorn |
| 前端 | HTML + CSS + JS + Chart.js (CDN) |
| 数据源 | OKX API (www.okx.com) |
| 指标库 | pandas-ta (508 个指标) |
| CI/CD | GitHub Actions (20 个工作流) |

## 📚 文档

- [系统架构](docs/architecture.md)
- [API 接口文档](docs/api-reference.md)
- [部署指南](docs/deployment-guide.md)
- [量化交易语言选型指南](docs/quant-language-guide.md)

## 🔧 配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| OKX_API_KEY | OKX API Key | - |
| OKX_SECRET_KEY | OKX Secret Key | - |
| OKX_PASSPHRASE | OKX Passphrase | - |
| OKX_SIMULATED | 模拟盘(1)/实盘(0) | 1 |
| OKX_API_HOST | API域名 | www.okx.com |
| OKX_PROXY | 代理地址 | - |

## 📄 License

MIT

## 🤝 Contributing

欢迎提交 Issue 和 PR！
