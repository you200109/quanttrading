# 系统架构

## 整体架构

```
┌─────────────────────────────────────────────────┐
│                   前端 (浏览器)                    │
│  ┌───────────┐ ┌──────────┐ ┌────────────────┐  │
│  │ K线图表    │ │ 盘口深度  │ │ 交易/策略面板   │  │
│  │ (lightweight│ │ (实时更新)│ │ (模拟/实盘)    │  │
│  │  -charts)  │ │           │ │                │  │
│  └───────────┘ └──────────┘ └────────────────┘  │
└─────────────────────┬───────────────────────────┘
                      │ REST API + WebSocket
┌─────────────────────┴───────────────────────────┐
│              后端 (FastAPI + Uvicorn)              │
│  ┌───────────┐ ┌──────────┐ ┌────────────────┐  │
│  │ 数据服务   │ │ 交易服务  │ │ 指标引擎       │  │
│  │ (OKX REST  │ │ (挂单/历史│ │ (508个指标     │  │
│  │  + WS)     │ │  /成交)   │ │  pandas-ta)   │  │
│  └───────────┘ └──────────┘ └────────────────┘  │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────┴───────────────────────────┐
│           OKX 交易所 (www.okx.com)              │
│  REST API: /api/v5/market/*                       │
│  WebSocket: wss://ws.okx.com:8443/ws/v5/*       │
└─────────────────────────────────────────────────┘
```

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | HTML + CSS + JS + Chart.js (CDN) | 暗色主题，专业K线图表 |
| 后端 | Python 3.12 + FastAPI + Uvicorn | 异步API，自动文档 |
| 数据源 | OKX API (www.okx.com) | 官方域名；如需镜像网关请经 OKX_API_HOST 覆盖并自行核实域名安全 |
| 指标库 | pandas-ta 0.4.71b0 | 508个技术指标 |
| 交易所SDK | okx-exchange 0.0.169 | 社区包（内嵌 ccxt，模块名 okx，import 需 aiohttp；非 OKX 官方，官方为 python-okx） |
| CI/CD | GitHub Actions | 20个自动化工作流 |

## 项目结构

```
quanttrading/
├── backend/
│   ├── api/routes.py          # API路由
│   ├── core/
│   │   ├── okx_data_service.py    # 行情数据服务
│   │   └── okx_trade_service.py   # 交易服务
│   ├── indicators/
│   │   └── indicator_engine.py    # 技术指标引擎
│   └── main.py                # FastAPI入口
├── frontend/
│   └── index.html             # 主页面（Chart.js CDN + 内联脚本）
├── vigilant-couscous/        # AI交易进化系统
├── docs/                     # 文档
├── scripts/                  # 运维脚本
├── .github/workflows/        # 20个工作流
└── .env                      # 环境配置
```
