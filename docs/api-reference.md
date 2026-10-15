# API 接口文档

## 基础信息

- Base URL: `http://localhost:8000`
- API 文档: `http://localhost:8000/docs`
- 认证: 当前无认证（本地使用）

## 行情接口

### 获取K线数据
```
GET /api/klines/{inst_id}?bar=1H&limit=300
```

### 获取多周期K线
```
GET /api/klines/multi/{inst_id}?limit=300
```

### 获取盘口深度
```
GET /api/orderbook/{inst_id}?depth=5
```

### 获取最新行情
```
GET /api/ticker/{inst_id}
```

### 获取所有行情
```
GET /api/tickers?inst_type=SPOT
```

## 交易接口

### 获取挂单
```
GET /api/orders/pending?inst_type=SPOT
```

### 获取历史委托
```
GET /api/orders/history?inst_type=SPOT&limit=50
```

### 获取成交明细
```
GET /api/fills?inst_type=SPOT&limit=50
```

### 获取账单流水
```
GET /api/bills?limit=50
```

### 获取账户余额
```
GET /api/account/balance
```

## 指标接口

### 列出所有指标
```
GET /api/indicators?category=trend
```

### 获取指标分类统计
```
GET /api/indicators/categories
```

### 计算指标
```
POST /api/indicators/calculate
Body: {"inst_id":"BTC-USDT","bar":"1H","indicators":["sma_20","rsi_14"],"limit":"100"}
```

## WebSocket

### 实时行情
```
WS /ws/market?inst_id=BTC-USDT
```

### 交易状态推送
```
WS /ws/trade
```
