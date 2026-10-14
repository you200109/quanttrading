"""
API Key 认证中间件
- 保护私有交易接口（挂单、历史、成交、账单、余额、持仓、下单、撤单）
- 行情接口（K线、盘口、Ticker、指标）保持公开
"""
import os
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# 需要认证的接口路径前缀
PROTECTED_PREFIXES = [
    '/api/orders',
    '/api/fills',
    '/api/bills',
    '/api/account',
    '/ws/trade',
]

# 公开接口路径前缀
PUBLIC_PREFIXES = [
    '/api/klines',
    '/api/orderbook',
    '/api/ticker',
    '/api/tickers',
    '/api/instruments',
    '/api/indicators',
    '/ws/market',
    '/health',
    '/docs',
    '/openapi',
    '/redoc',
    '/app',
]


def is_protected(path: str) -> bool:
    """判断路径是否需要认证"""
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return False
    for prefix in PROTECTED_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def get_api_key() -> str:
    """从环境变量获取 API Key"""
    return os.getenv('API_AUTH_KEY', 'quanttrading-secret-key')


async def auth_middleware(request: Request, call_next):
    """API Key 认证中间件"""
    path = request.url.path
    
    if not is_protected(path):
        return await call_next(request)
    
    # 检查 API Key
    api_key = request.headers.get('X-API-Key')
    expected_key = get_api_key()
    
    if not api_key or api_key != expected_key:
        return JSONResponse(
            status_code=401,
            content={'code': 401, 'msg': 'Unauthorized: invalid or missing API key'},
        )
    
    return await call_next(request)
