# Architecture

## Backend Structure
- `backend/api/` - FastAPI routes (routes.py, vc_routes.py)
- `backend/core/` - Core services (OKX data, trade, auth, resilience, observability)
- `backend/indicators/` - 508 technical indicators (pandas-ta)
- `backend/mcp/` - MCP server with 9 tools

## Frontend
- Single-page HTML app with Chart.js
- Real-time market data, K-line charts, order book
- Indicator calculation, strategy backtesting
- AGI evolution control, risk management

## Vigilant-Couscous Modules
- `agi/` - AGI brain, continuous learner, eternal evolver
- `agents/` - Risk manager, trader, alert manager, parallel scheduler
- `evolution/` - Backtest validator, RL environment, learning loop
- `strategy/` - GitHub scanner, learning engine, unified evolve
- `trading/` - Auto trade, auto iterate, hot reload
- `data/` - Fetcher, cache manager, live trader, portfolio manager
- `memory/` - Persistent storage layer
- `web/` - Web console, visualizer
- `cli/` - Command line tools

## CI/CD Pipeline
- CI: Matrix build (Python 3.11/3.12) + flake8 + pytest + merge check
- CodeQL: Code security scanning
- Docker: Build and push to GHCR
- Publish: PyPI package publishing
- OKX Scanner: Hourly OKX project search
- Dependabot: Dependency updates