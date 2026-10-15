# API Reference

## Market Data
- `GET /api/klines/{inst_id}` - K-line data
- `GET /api/klines/multi/{inst_id}` - Multi-period K-lines
- `GET /api/orderbook/{inst_id}` - Order book depth
- `GET /api/ticker/{inst_id}` - Latest ticker
- `GET /api/tickers` - All tickers
- `GET /api/instruments` - Instrument list

## Trading
- `GET /api/orders/pending` - Pending orders
- `GET /api/orders/history` - Order history
- `GET /api/fills` - Trade fills
- `GET /api/bills` - Account bills
- `GET /api/account/balance` - Account balance
- `GET /api/account/positions` - Positions

## Indicators
- `GET /api/indicators` - List 508 indicators
- `GET /api/indicators/categories` - Indicator categories
- `POST /api/indicators/calculate` - Calculate indicators

## Backtesting
- `POST /api/backtest` - Run strategy backtest

## VC Integration (11 endpoints)
- `GET /api/vc/agi/status` - AGI status
- `POST /api/vc/agi/evolve` - Trigger evolution
- `GET /api/vc/strategies` - List strategies
- `POST /api/vc/backtest/vc` - VC backtest
- `GET /api/vc/risk/status` - Risk status
- `POST /api/vc/risk/approve` - Approve trade
- `GET /api/vc/memory/nexus` - Memory data
- `POST /api/vc/github/learn` - GitHub learning
- `GET /api/vc/github/seeds` - Seed params

## WebSocket
- `WS /ws/market` - Real-time market data
- `WS /ws/trade` - Trade status updates

## System
- `GET /health` - Health check
- `GET /api/system/resources` - System resources
- `GET /api/system/dashboard` - Dashboard data
- `GET /api/system/traces` - Trace records
- `GET /api/system/alerts` - Alert history