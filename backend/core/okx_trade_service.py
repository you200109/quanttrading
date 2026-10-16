"""
OKX 交易服务模块
- 私有 REST API: 挂单、历史委托、成交明细、账单流水（okx-exchange 原始端点）
- 私有 WebSocket: 订单状态实时推送（自实现 HMAC 登录，与 SDK 无关）
- 模拟盘/实盘切换（sandbox 模式 = x-simulated-trading: 1 请求头）
SDK: okx-exchange 0.0.169（内嵌 ccxt 的 OkxSync 同步客户端；模块名 okx）

错误契约（与换血前 pyted okx 2.1.2 的对外行为对齐）：
- 业务错误（HTTP 200 但 code != '0'）：ccxt 会抛 BaseError。
  getter 记 warning 日志后按旧版语义返回默认值（[] / {}）；
  下单/撤单尽力从异常消息恢复 OKX 原始响应 dict 返回。
- 传输层错误（NetworkError 家族，含超时）：原样上抛（与旧版一致）。
"""
import os
import json
import asyncio
import logging
import threading
import websockets
import hmac
import base64
from datetime import datetime, timezone
from dotenv import load_dotenv
from okx import OkxSync
from okx.ccxt.base.errors import BaseError, NetworkError

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

logger = logging.getLogger('OKXTradeService')


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
        self.client = OkxSync({
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'password': self.passphrase,
            'hostname': os.getenv('OKX_API_HOST', 'www.okx.com'),
            'sandbox': simulated,
            'enableRateLimit': True,
        })
        self._ws_private = None

    # ==================== 响应解析 ====================

    @staticmethod
    def _recover_response(exc):
        """从 ccxt 异常消息尽力恢复 OKX 原始响应体。

        ccxt 的 handle_errors 在异常消息中携带接口原始 JSON
        （格式："okx {原始响应}"）；恢复成功可保持下单/撤单
        返回"OKX 原始响应 dict"的旧版契约。恢复失败返回 None。
        """
        text = str(exc)
        start = text.find('{')
        if start != -1:
            try:
                parsed = json.loads(text[start:])
            except ValueError:
                return None
            if isinstance(parsed, dict):
                return parsed
        return None

    def _call(self, name, request, params, default):
        """调用 okx-exchange 原始端点并按旧版契约解析响应。

        - 传输层错误（NetworkError 家族）：原样上抛
        - 业务错误（BaseError）：记 warning，按旧版语义落 default
        - code == '0'：返回 data（缺省 default）
        """
        try:
            resp = request(params)
        except NetworkError:
            raise
        except BaseError as exc:
            logger.warning('OKX %s 业务错误: %s', name, exc)
            return default
        if isinstance(resp, dict) and resp.get('code') == '0':
            return resp.get('data', default)
        return default

    # ==================== 挂单（未成交订单） ====================

    def get_pending_orders(self, inst_type='SPOT', inst_id=None):
        """获取当前未成交订单"""
        params = {'instType': inst_type}
        if inst_id:
            params['instId'] = inst_id
        return self._call(
            'private_get_trade_orders_pending',
            self.client.private_get_trade_orders_pending, params, [])

    # ==================== 历史委托 ====================

    def get_orders_history(self, inst_type='SPOT', limit='50'):
        """获取近 7 天历史委托"""
        return self._call(
            'private_get_trade_orders_history',
            self.client.private_get_trade_orders_history,
            {'instType': inst_type, 'limit': limit}, [])

    def get_orders_history_archive(self, inst_type='SPOT', limit='50'):
        """获取近 3 个月历史委托（归档）"""
        return self._call(
            'private_get_trade_orders_history_archive',
            self.client.private_get_trade_orders_history_archive,
            {'instType': inst_type, 'limit': limit}, [])

    # ==================== 成交明细 ====================

    def get_fills(self, inst_type='SPOT', limit='50'):
        """获取近 3 天成交明细"""
        return self._call(
            'private_get_trade_fills',
            self.client.private_get_trade_fills,
            {'instType': inst_type, 'limit': limit}, [])

    def get_fills_history(self, inst_type='SPOT', limit='50'):
        """获取近 3 个月成交明细（归档）"""
        return self._call(
            'private_get_trade_fills_history',
            self.client.private_get_trade_fills_history,
            {'instType': inst_type, 'limit': limit}, [])

    # ==================== 账户账单流水 ====================

    def get_account_bills(self, limit='50'):
        """获取近 7 天账户账单流水"""
        return self._call(
            'private_get_account_bills',
            self.client.private_get_account_bills, {'limit': limit}, [])

    def get_account_bills_archive(self, limit='50'):
        """获取近 3 个月账户账单流水（归档）"""
        return self._call(
            'private_get_account_bills_archive',
            self.client.private_get_account_bills_archive, {'limit': limit}, [])

    # ==================== 账户信息 ====================

    def get_account_balance(self):
        """获取账户余额"""
        data = self._call(
            'private_get_account_balance',
            self.client.private_get_account_balance, {}, [])
        if data:
            return data[0]
        return {}

    def get_account_position(self, inst_type=None):
        """获取持仓信息"""
        params = {}
        if inst_type:
            params['instType'] = inst_type
        return self._call(
            'private_get_account_positions',
            self.client.private_get_account_positions, params, [])

    # ==================== 下单 / 撤单 ====================

    def place_order(self, inst_id, side, ord_type, sz, px=None, td_mode='cash'):
        """下单（含参数校验；业务错误返回 OKX 原始响应 dict）"""
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
        try:
            return self.client.private_post_trade_order(params)
        except NetworkError:
            raise
        except BaseError as exc:
            logger.warning('OKX 下单业务错误: %s', exc)
            return self._recover_response(exc) or {'code': '1', 'msg': str(exc)}

    def cancel_order(self, inst_id, ord_id):
        """撤单（业务错误返回 OKX 原始响应 dict）"""
        try:
            return self.client.private_post_trade_cancel_order(
                {'instId': inst_id, 'ordId': ord_id})
        except NetworkError:
            raise
        except BaseError as exc:
            logger.warning('OKX 撤单业务错误: %s', exc)
            return self._recover_response(exc) or {'code': '1', 'msg': str(exc)}

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
            logger.warning('Private WS login failed: %s', login_data.get('msg', 'unknown error'))
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
