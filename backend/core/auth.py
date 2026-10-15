"""
API Key 认证中间件
- 保护私有交易接口（挂单、历史、成交、账单、余额、持仓、下单、撤单）
- 行情接口（K线、盘口、Ticker、指标）保持公开
- 安全策略：
  1. 不在代码中硬编码任何默认密钥；API_AUTH_KEY 未配置时交易接口全部 503 拒绝
  2. 常量时间比较，防止计时侧信道攻击
  3. 默认拒绝：/api/ 与 /ws/ 下未显式声明为公开的路径一律要求认证
"""
import hmac
import os
from fastapi import Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# 受保护的命名空间：/api/ 与 /ws/ 下未显式放行的路径一律要求认证（默认拒绝）
# 典型受保护端点：/api/orders/* /api/fills/* /api/bills/* /api/account/* /ws/trade /api/vc/*

# 公开接口路径前缀（精确匹配或作为目录前缀）
PUBLIC_PREFIXES = (
    '/api/klines',
    '/api/orderbook',
    '/api/ticker',
    '/api/tickers',
    '/api/instruments',
    '/api/indicators',
    '/api/system',
    '/ws/market',
    '/app',
)

# 公开的精确路径
PUBLIC_EXACT = ('/', '/health', '/docs', '/openapi', '/redoc')

# 需要认证的命名空间（默认拒绝）
_GUARDED_NAMESPACES = ('/api/', '/ws/')

# API Key 未配置时的提示信息
_KEY_MISSING_MSG = (
    'API_AUTH_KEY is not configured. '
    'Set the API_AUTH_KEY environment variable before enabling trading endpoints.'
)


def is_protected(path: str) -> bool:
    """判断路径是否需要认证：/api/ 与 /ws/ 命名空间默认拒绝，白名单显式放行"""
    if path in PUBLIC_EXACT:
        return False
    for prefix in PUBLIC_PREFIXES:
        if path == prefix or path.startswith(prefix + '/'):
            return False
    for ns in _GUARDED_NAMESPACES:
        if path.startswith(ns):
            return True
    return False


def get_api_key():
    """从环境变量获取 API Key；未配置时返回 None（触发 503 拒绝）"""
    return os.getenv('API_AUTH_KEY') or None


async def auth_middleware(request: Request, call_next):
    """API Key 认证中间件"""
    path = request.url.path

    if not is_protected(path):
        return await call_next(request)

    # 检查 API Key
    api_key = request.headers.get('X-API-Key')
    expected_key = get_api_key()

    if not expected_key:
        # 服务端未配置密钥：拒绝所有受保护请求，绝不使用硬编码默认值
        return JSONResponse(
            status_code=503,
            content={'code': 503, 'msg': _KEY_MISSING_MSG},
        )

    if not api_key or not hmac.compare_digest(api_key, expected_key):
        return JSONResponse(
            status_code=401,
            content={'code': 401, 'msg': 'Unauthorized: invalid or missing API key'},
        )

    return await call_next(request)
