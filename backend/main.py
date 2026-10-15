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
from backend.core.resilience import graceful_shutdown, resource_limiter
from backend.core.observability import start_trace, end_trace, get_dashboard_data, get_trace_records, get_trace_stats, get_alert_history

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

# 链路追踪中间件
@app.middleware('http')
async def trace_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith('/docs') or path.startswith('/openapi') or path.startswith('/app'):
        return await call_next(request)
    start_trace(path)
    try:
        response = await call_next(request)
        end_trace(response.status_code)
        return response
    except Exception as e:
        end_trace(500, {'error': str(e)})
        raise

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

@app.get('/api/system/resources')
async def system_resources():
    """获取系统资源使用状态"""
    return {'code': 0, 'data': resource_limiter.get_status()}

@app.get('/api/system/dashboard')
async def system_dashboard():
    """获取仪表盘数据（系统资源+请求统计+告警+指标）"""
    return {'code': 0, 'data': get_dashboard_data()}

@app.get('/api/system/traces')
async def system_traces(limit: int = 50):
    """获取链路追踪记录"""
    return {'code': 0, 'count': limit, 'data': get_trace_records(limit)}

@app.get('/api/system/traces/stats')
async def system_trace_stats():
    """获取链路追踪统计"""
    return {'code': 0, 'data': get_trace_stats()}

@app.get('/api/system/alerts')
async def system_alerts(limit: int = 20):
    """获取告警历史"""
    return {'code': 0, 'count': limit, 'data': get_alert_history(limit)}

@app.on_event('shutdown')
async def shutdown_event():
    """优雅关闭 event handler"""
    graceful_shutdown.shutdown()


if __name__ == '__main__':
    import uvicorn
    host = os.getenv('API_HOST', '0.0.0.0')
    port = int(os.getenv('API_PORT', '8000'))
    uvicorn.run('backend.main:app', host=host, port=port, reload=True)
