"""
实盘交易接口 - 欧易(OKX) API

功能:
- 实时行情订阅
- 自动下单（市价/限价）
- 持仓查询与管理
- 订单状态追踪
- 账户余额查询
"""

import json
import time
import hmac
import base64
import hashlib
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass
import requests
import logging

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    """订单结果"""
    order_id: str
    symbol: str
    side: str
    price: float
    quantity: float
    status: str
    timestamp: str


@dataclass
class Position:
    """持仓信息"""
    symbol: str
    quantity: float
    avg_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: int


class OKXLiveTrader:
    """欧易实盘交易接口
    
    支持公开行情（无需 API Key）和私有交易（需要 API Key）。
    """
    
    def __init__(
        self,
        api_key: str = "",
        secret_key: str = "",
        passphrase: str = "",
        base_url: str = "https://www.www.okx.com",
        demo: bool = True
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.base_url = base_url
        self.demo = demo
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        
        if not demo and (not api_key or not secret_key or not passphrase):
            logger.warning("实盘模式需要完整的 API 三件套，当前为演示模式")
            self.demo = True
    
    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """生成签名"""
        message = timestamp + method + path + body
        mac = hmac.new(
            self.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode('utf-8')
    
    def _request(self, method: str, path: str, params: dict = None, body: dict = None) -> dict:
        """发送签名请求"""
        url = self.base_url + path
        timestamp = str(int(time.time()))
        body_str = json.dumps(body) if body else ""
        
        headers = {}
        if not self.demo and self.api_key:
            sign = self._sign(timestamp, method, path, body_str)
            headers.update({
                'OK-ACCESS-KEY': self.api_key,
                'OK-ACCESS-SIGN': sign,
                'OK-ACCESS-TIMESTAMP': timestamp,
                'OK-ACCESS-PASSPHRASE': self.passphrase,
            })
        
        try:
            if method == 'GET':
                resp = self.session.get(url, params=params, headers=headers, timeout=15)
            elif method == 'POST':
                resp = self.session.post(url, json=body, headers=headers, timeout=15)
            else:
                raise ValueError(f"不支持的请求方法: {method}")
            
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error(f"API 请求失败: {resp.status_code} - {resp.text[:200]}")
                return {'code': '-1', 'msg': f'HTTP {resp.status_code}'}
        except Exception as e:
            logger.error(f"请求异常: {e}")
            return {'code': '-1', 'msg': str(e)}
    
    # ===== 公开行情接口 =====
    
    def get_ticker(self, symbol: str = "BTC-USDT") -> dict:
        """获取实时行情
        
        Returns:
            {'last': 价格, 'high24h': 最高, 'low24h': 最低, 'vol24h': 成交量, ...}
        """
        result = self._request('GET', '/api/v5/market/ticker', params={'instId': symbol})
        if result.get('code') == '0' and result.get('data'):
            data = result['data'][0]
            return {
                'symbol': symbol,
                'last': float(data['last']),
                'high24h': float(data['high24h']),
                'low24h': float(data['low24h']),
                'bid': float(data['bidPx']),
                'ask': float(data['askPx']),
                'vol24h': float(data['vol24h']),
                'change24h': float(data.get('sodUtc8', '0')),
                'timestamp': datetime.now().isoformat()
            }
        return {}
    
    def get_candles(self, symbol: str = "BTC-USDT", bar: str = "1D", limit: int = 100) -> List[dict]:
        """获取 K 线数据"""
        result = self._request('GET', '/api/v5/market/candles', params={
            'instId': symbol, 'bar': bar, 'limit': limit
        })
        if result.get('code') == '0' and result.get('data'):
            candles = []
            for c in result['data']:
                candles.append({
                    'timestamp': int(c[0]),
                    'open': float(c[1]),
                    'high': float(c[2]),
                    'low': float(c[3]),
                    'close': float(c[4]),
                    'volume': float(c[5])
                })
            return candles
        return []
    
    def get_orderbook(self, symbol: str = "BTC-USDT", depth: int = 5) -> dict:
        """获取订单簿"""
        result = self._request('GET', '/api/v5/market/books', params={
            'instId': symbol, 'sz': depth
        })
        if result.get('code') == '0' and result.get('data'):
            data = result['data'][0]
            return {
                'asks': [(float(a[0]), float(a[1])) for a in data.get('asks', [])],
                'bids': [(float(b[0]), float(b[1])) for b in data.get('bids', [])],
                'timestamp': data.get('ts')
            }
        return {}
    
    # ===== 私有交易接口（需要 API Key）====
    
    def get_balance(self) -> dict:
        """获取账户余额"""
        if self.demo:
            return {'demo': True, 'USDT': 100000, 'BTC': 0, 'ETH': 0}
        
        result = self._request('GET', '/api/v5/account/balance')
        if result.get('code') == '0' and result.get('data'):
            balances = {}
            for item in result['data'][0].get('details', []):
                ccy = item['ccy']
                avail = float(item.get('availBal', 0))
                frozen = float(item.get('frozenBal', 0))
                balances[ccy] = {'available': avail, 'frozen': frozen, 'total': avail + frozen}
            return balances
        return {}
    
    def get_positions(self) -> List[Position]:
        """获取当前持仓"""
        if self.demo:
            return []
        
        result = self._request('GET', '/api/v5/account/positions')
        positions = []
        if result.get('code') == '0' and result.get('data'):
            for item in result['data']:
                pos = float(item.get('pos', 0))
                if pos != 0:
                    positions.append(Position(
                        symbol=item['instId'],
                        quantity=pos,
                        avg_price=float(item.get('avgPx', 0)),
                        mark_price=float(item.get('markPx', 0)),
                        unrealized_pnl=float(item.get('upl', 0)),
                        leverage=int(item.get('lever', 1))
                    ))
        return positions
    
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: str = "market"
    ) -> Optional[OrderResult]:
        """下单
        
        Args:
            symbol: 交易对，如 BTC-USDT
            side: buy / sell
            quantity: 数量（市价买入时为 USDT 金额）
            price: 限价单价格（市价单不需要）
            order_type: market / limit
        """
        if self.demo:
            logger.info(f"[演示] {side} {quantity} {symbol} @ {order_type}")
            return OrderResult(
                order_id=f"demo_{int(time.time())}",
                symbol=symbol,
                side=side,
                price=price or 0,
                quantity=quantity,
                status="filled",
                timestamp=datetime.now().isoformat()
            )
        
        body = {
            'instId': symbol,
            'tdMode': 'cash',
            'side': side,
            'ordType': order_type,
        }
        
        if order_type == 'market':
            if side == 'buy':
                # OKX 现货市价买入 sz 为 USDT 金额，非币数量
                # 若 quantity 为币数量，需乘以当前价格转换为金额
                buy_amount = quantity * price if price else quantity
                body['sz'] = str(buy_amount)
            else:
                body['sz'] = str(quantity)  # 卖出数量
        else:
            body['sz'] = str(quantity)
            body['px'] = str(price)
        
        result = self._request('POST', '/api/v5/trade/order', body=body)
        
        if result.get('code') == '0' and result.get('data'):
            data = result['data'][0]
            return OrderResult(
                order_id=data['ordId'],
                symbol=symbol,
                side=side,
                price=float(data.get('px', 0)),
                quantity=float(data.get('sz', 0)),
                status=data.get('state', 'unknown'),
                timestamp=datetime.now().isoformat()
            )
        
        logger.error(f"下单失败: {result.get('msg')}")
        return None
    
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """撤销订单"""
        if self.demo:
            return True
        
        result = self._request('POST', '/api/v5/trade/cancel-order', body={
            'instId': symbol, 'ordId': order_id
        })
        return result.get('code') == '0'
    
    def get_order_status(self, order_id: str, symbol: str) -> dict:
        """查询订单状态"""
        if self.demo:
            return {'order_id': order_id, 'status': 'filled'}
        
        result = self._request('GET', '/api/v5/trade/order', params={
            'instId': symbol, 'ordId': order_id
        })
        if result.get('code') == '0' and result.get('data'):
            return result['data'][0]
        return {}
    
    def get_pending_orders(self) -> List[dict]:
        """获取挂单列表"""
        if self.demo:
            return []
        
        result = self._request('GET', '/api/v5/trade/orders-pending')
        if result.get('code') == '0':
            return result.get('data', [])
        return []
