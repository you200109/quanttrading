"""
OKX 数据服务核心模块
- REST API: 多周期 K 线、盘口深度、Ticker 行情（requests 直连 OKX v5，不依赖交易所 SDK）
- WebSocket: 实时数据推送通道（websockets 直连）
支持代理和超时保护
"""
import os
import json
import asyncio
import threading
import logging
import websockets
import requests
from dotenv import load_dotenv
from backend.core.rate_limiter import okx_rate_limiter

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

REST_TIMEOUT = 15
OKX_PROXY = os.getenv('OKX_PROXY', '')
OKX_API_HOST = os.getenv('OKX_API_HOST', 'www.okx.com')


class OKXDataService:
    """OKX 交易所数据服务"""

    SUPPORTED_BAR = ['15m', '30m', '1H', '4H']

    @property
    def ws_public_url(self):
        return f'wss://ws.{self.api_host}:8443/ws/v5/public'

    def __init__(self, simulated=True):
        self.simulated = simulated
        self.flag = '1' if simulated else '0'
        self.proxy = OKX_PROXY if OKX_PROXY else None
        self.proxies = {'http': self.proxy, 'https': self.proxy} if self.proxy else None
        self.api_host = OKX_API_HOST
        self._ws_clients = {}

    def _rest_get(self, path, params=None):
        """带超时、代理和限速的 REST GET 请求"""
        okx_rate_limiter.acquire()
        url = f'https://{self.api_host}{path}'
        try:
            r = requests.get(url, params=params or {}, timeout=REST_TIMEOUT, proxies=self.proxies)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logging.getLogger('OKXDataService').error(f'REST GET {path} error: {e}')
        return {}

    # ==================== REST API ====================

    def get_candlesticks(self, inst_id='BTC-USDT', bar='1H', limit='300'):
        """获取 K 线数据"""
        resp = self._rest_get('/api/v5/market/candles', {'instId': inst_id, 'bar': bar, 'limit': limit})
        if resp.get('code') == '0':
            return resp.get('data', [])
        return []

    def get_multi_period_klines(self, inst_id='BTC-USDT', limit='300'):
        """获取多周期 K 线数据"""
        result = {}
        for bar in self.SUPPORTED_BAR:
            result[bar] = self.get_candlesticks(inst_id, bar, limit)
        return result

    def get_orderbook(self, inst_id='BTC-USDT', depth='5'):
        """获取盘口深度数据"""
        resp = self._rest_get('/api/v5/market/books', {'instId': inst_id, 'sz': depth})
        if resp.get('code') == '0' and resp.get('data'):
            return resp['data'][0]
        return {}

    def get_ticker(self, inst_id='BTC-USDT'):
        """获取最新行情"""
        resp = self._rest_get('/api/v5/market/ticker', {'instId': inst_id})
        if resp.get('code') == '0' and resp.get('data'):
            return resp['data'][0]
        return {}

    def get_all_tickers(self, inst_type='SPOT'):
        """获取所有行情"""
        resp = self._rest_get('/api/v5/market/tickers', {'instType': inst_type})
        if resp.get('code') == '0':
            return resp.get('data', [])
        return []

    def get_instruments(self, inst_type='SPOT'):
        """获取交易产品列表"""
        resp = self._rest_get('/api/v5/public/instruments', {'instType': inst_type})
        if resp.get('code') == '0':
            return resp.get('data', [])
        return []

    # ==================== WebSocket 实时推送 ====================

    async def _ws_connect(self, url):
        """建立 WebSocket 连接"""
        ws = await websockets.connect(url)
        return ws

    async def _ws_subscribe(self, ws, channels):
        """订阅频道"""
        sub_msg = {'op': 'subscribe', 'args': channels}
        await ws.send(json.dumps(sub_msg))

    async def start_public_ws(self, inst_id='BTC-USDT', on_data_callback=None):
        """启动公共 WebSocket 实时数据推送（含自动重连）"""
        import asyncio as aio
        
        max_retries = 5
        base_delay = 1
        
        for attempt in range(max_retries + 1):
            try:
                url = self.ws_public_url
                ws = await self._ws_connect(url)
                self._ws_clients['public'] = ws

                channels = [
                    {'channel': 'candle15m', 'instId': inst_id},
                    {'channel': 'candle30m', 'instId': inst_id},
                    {'channel': 'candle1H', 'instId': inst_id},
                    {'channel': 'candle4H', 'instId': inst_id},
                    {'channel': 'books5', 'instId': inst_id},
                    {'channel': 'tickers', 'instId': inst_id},
                ]
                await self._ws_subscribe(ws, channels)
                
                logging.getLogger('OKXDataService').info(f'WebSocket connected (attempt {attempt + 1})')

                async for message in ws:
                    data = json.loads(message)
                    if on_data_callback:
                        if asyncio.iscoroutinefunction(on_data_callback):
                            await on_data_callback(data)
                        else:
                            on_data_callback(data)
                            
            except websockets.exceptions.ConnectionClosed:
                logging.getLogger('OKXDataService').warning(f'WebSocket disconnected (attempt {attempt + 1}/{max_retries})')
            except Exception as e:
                logging.getLogger('OKXDataService').error(f'WebSocket error: {e}')
            finally:
                await self.stop_ws('public')
            
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logging.getLogger('OKXDataService').info(f'Reconnecting in {delay}s...')
                await aio.sleep(delay)
        
        logging.getLogger('OKXDataService').error('WebSocket max retries reached, giving up')

    async def stop_ws(self, client_key='public'):
        """停止 WebSocket 连接"""
        ws = self._ws_clients.get(client_key)
        if ws and not ws.closed:
            await ws.close()

    async def stop_all_ws(self):
        """停止所有 WebSocket 连接"""
        for key in list(self._ws_clients.keys()):
            await self.stop_ws(key)


# 线程安全单例
_data_service = None
_data_service_lock = threading.Lock()


def get_data_service(simulated=True):
    global _data_service
    if _data_service is None:
        with _data_service_lock:
            if _data_service is None:
                _data_service = OKXDataService(simulated=simulated)
    return _data_service
