"""
FastAPI 主应用入口
- 挂载所有 API 路由
- 配置 CORS 跨域
- 启动 WebSocket 端点
"""
import os
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from backend.api.routes import router
from backend.core.auth import auth_middleware

# 日志系统配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('quanttrading.log', encoding='utf-8'),
    ],
)
logger = logging.getLogger('QuantTrading')

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

app = FastAPI(
    title='QuantTrading API',
    description='量化交易可视化交互系统后端 API',
    version='1.0.0',
)

# CORS 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# API Key 认证中间件
app.middleware('http')(auth_middleware)

# 挂载路由
app.include_router(router)

# 挂载前端静态文件
frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend')
if os.path.exists(frontend_path):
    app.mount('/app', StaticFiles(directory=frontend_path, html=True), name='frontend')


@app.get('/')
async def root():
    """重定向到前端页面"""
    index_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        'name': 'QuantTrading API',
        'version': '1.0.0',
        'status': 'running',
        'docs': '/docs',
        'endpoints': {
            'klines': '/api/klines/{inst_id}',
            'multi_klines': '/api/klines/multi/{inst_id}',
            'orderbook': '/api/orderbook/{inst_id}',
            'ticker': '/api/ticker/{inst_id}',
            'tickers': '/api/tickers',
            'instruments': '/api/instruments',
            'pending_orders': '/api/orders/pending',
            'orders_history': '/api/orders/history',
            'fills': '/api/fills',
            'bills': '/api/bills',
            'balance': '/api/account/balance',
            'positions': '/api/account/positions',
            'indicators': '/api/indicators',
            'indicator_categories': '/api/indicators/categories',
            'calculate_indicators': '/api/indicators/calculate',
            'ws_market': '/ws/market',
            'ws_trade': '/ws/trade',
        },
    }


@app.get('/health')
async def health():
    logger.info('Health check OK')
    return {'status': 'ok'}


if __name__ == '__main__':
    import uvicorn
    host = os.getenv('API_HOST', '0.0.0.0')
    port = int(os.getenv('API_PORT', '8000'))
    uvicorn.run('backend.main:app', host=host, port=port, reload=True)
