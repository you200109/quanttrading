"""
OKX 交易服务模块
- 私有 REST API: 挂单、历史委托、成交明细、账单流水
- 私有 WebSocket: 订单状态实时推送
- 模拟盘/实盘切换
适配 okx 包 2.1.2 版本
"""
import os
import json
import asyncio
import threading
import websockets
import hmac
import base64
from datetime import datetime, timezone
from dotenv import load_dotenv
import okx.api.trade as Trade
import okx.api.account as Account

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))


class OKXTradeService:
    """OKX 交易所交易服务"""

    VALID_SIDES = ['buy', 'sell']
    VALID_ORD_TYPES = ['limit', 'market', 'post_only', 'fok', 'ioc']

    @property
    def ws_private_url(self):
        host = os.getenv('OKX_API_HOST', 'www.okx.com')
        return f'wss://ws.{host}:8443/ws/v5/private'

    def __init__(self, simulated=None):
        self.api_key = os.getenv('OKX_API_KEY', '')
        self.secret_key = os.getenv('OKX_SECRET_KEY', '')
        self.passphrase = os.getenv('OKX_PASSPHRASE', '')
        if simulated is None:
            simulated = os.getenv('OKX_SIMULATED', '1') == '1'
        self.simulated = simulated
        self.flag = '1' if simulated else '0'

        self.trade_api = Trade.Trade(
            key=self.api_key, secret=self.secret_key,
            passphrase=self.passphrase, flag=self.flag
        )
        self.account_api = Account.Account(
            key=self.api_key, secret=self.secret_key,
            passphrase=self.passphrase, flag=self.flag
        )
        self._ws_private = None

    # ==================== 挂单（未成交订单） ====================

    def get_pending_orders(self, inst_type='SPOT', inst_id=None):
        """获取当前未成交订单"""
        params = {'instType': inst_type}
        if inst_id:
            params['instId'] = inst_id
        resp = self.trade_api.get_orders_pending(**params)
        if isinstance(resp, dict) and resp.get('code') == '0':
            return resp.get('data', [])
        return []

    # ==================== 历史委托 ====================

    def get_orders_history(self, inst_type='SPOT', limit='50'):
        """获取近 7 天历史委托"""
        resp = self.trade_api.get_orders_history(instType=inst_type, limit=limit)
        if isinstance(resp, dict) and resp.get('code') == '0':
            return resp.get('data', [])
        return []

    def get_orders_history_archive(self, inst_type='SPOT', limit='50'):
        """获取近 3 个月历史委托（归档）"""
        resp = self.trade_api.get_orders_history_archive(instType=inst_type, limit=limit)
        if isinstance(resp, dict) and resp.get('code') == '0':
            return resp.get('data', [])
        return []

    # ==================== 成交明细 ====================

    def get_fills(self, inst_type='SPOT', limit='50'):
        """获取近 3 天成交明细"""
        resp = self.trade_api.get_fills(instType=inst_type, limit=limit)
        if isinstance(resp, dict) and resp.get('code') == '0':
            return resp.get('data', [])
        return []

    def get_fills_history(self, inst_type='SPOT', limit='50'):
        """获取近 3 个月成交明细（归档）"""
        resp = self.trade_api.get_fills_history(instType=inst_type, limit=limit)
        if isinstance(resp, dict) and resp.get('code') == '0':
            return resp.get('data', [])
        return []

    # ==================== 账户账单流水 ====================

    def get_account_bills(self, limit='50'):
        """获取近 7 天账户账单流水"""
        resp = self.account_api.get_bills(limit=limit)
        if isinstance(resp, dict) and resp.get('code') == '0':
            return resp.get('data', [])
        return []

    def get_account_bills_archive(self, limit='50'):
        """获取近 3 个月账户账单流水（归档）"""
        resp = self.account_api.get_bills_archive(limit=limit)
        if isinstance(resp, dict) and resp.get('code') == '0':
            return resp.get('data', [])
        return []

    # ==================== 账户信息 ====================

    def get_account_balance(self):
        """获取账户余额"""
        resp = self.account_api.get_balance()
        if isinstance(resp, dict) and resp.get('code') == '0' and resp.get('data'):
            return resp['data'][0]
        return {}

    def get_account_position(self, inst_type=None):
        """获取持仓信息"""
        params = {}
        if inst_type:
            params['instType'] = inst_type
        resp = self.account_api.get_positions(**params)
        if isinstance(resp, dict) and resp.get('code') == '0':
            return resp.get('data', [])
        return []

    # ==================== 下单 / 撤单 ====================

    def place_order(self, inst_id, side, ord_type, sz, px=None, td_mode='cash'):
        """下单（含参数校验）"""
        if side not in self.VALID_SIDES:
            return {'code': '1', 'msg': f'Invalid side: {side}, must be one of {self.VALID_SIDES}'}
        if ord_type not in self.VALID_ORD_TYPES:
            return {'code': '1', 'msg': f'Invalid ord_type: {ord_type}, must be one of {self.VALID_ORD_TYPES}'}
        if not inst_id or not sz:
            return {'code': '1', 'msg': 'inst_id and sz are required'}
        if ord_type == 'limit' and not px:
            return {'code': '1', 'msg': 'px is required for limit orders'}
        params = {
            'instId': inst_id,
            'tdMode': td_mode,
            'side': side,
            'ordType': ord_type,
            'sz': str(sz),
        }
        if px:
            params['px'] = str(px)
        resp = self.trade_api.set_order(**params)
        return resp

    def cancel_order(self, inst_id, ord_id):
        """撤单"""
        resp = self.trade_api.set_cancel_order(instId=inst_id, ordId=ord_id)
        return resp

    # ==================== 私有 WebSocket ====================

    async def start_private_ws(self, on_data_callback=None):
        """启动私有 WebSocket 实时推送"""
        url = self.ws_private_url
        ws = await websockets.connect(url)
        self._ws_private = ws

        # 登录签名
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.') + \
                    f'{datetime.now(timezone.utc).microsecond // 1000:03d}Z'
        message = timestamp + 'GET' + '/users/self/verify'
        mac = hmac.new(self.secret_key.encode(), message.encode(), 'sha256')
        sign = base64.b64encode(mac.digest()).decode()

        login_msg = {
            'op': 'login',
            'args': [{
                'apiKey': self.api_key,
                'passphrase': self.passphrase,
                'timestamp': timestamp,
                'sign': sign,
            }]
        }
        await ws.send(json.dumps(login_msg))

        login_resp = await ws.recv()
        login_data = json.loads(login_resp)
        if login_data.get('code') != '0':
            print(f'Private WS login failed: {login_data.get("msg", "unknown error")}')
            await ws.close()
            return

        channels = [
            {'channel': 'orders', 'instType': 'SPOT'},
            {'channel': 'account'},
            {'channel': 'positions', 'instType': 'SWAP'},
        ]
        sub_msg = {'op': 'subscribe', 'args': channels}
        await ws.send(json.dumps(sub_msg))

        try:
            async for message in ws:
                data = json.loads(message)
                if on_data_callback:
                    if asyncio.iscoroutinefunction(on_data_callback):
                        await on_data_callback(data)
                    else:
                        on_data_callback(data)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await ws.close()

    async def stop_private_ws(self):
        """停止私有 WebSocket"""
        if self._ws_private and not self._ws_private.closed:
            await self._ws_private.close()


# 线程安全单例
_trade_service = None
_trade_service_lock = threading.Lock()


def get_trade_service(simulated=None):
    global _trade_service
    if _trade_service is None:
        with _trade_service_lock:
            if _trade_service is None:
                _trade_service = OKXTradeService(simulated=simulated)
    return _trade_service
