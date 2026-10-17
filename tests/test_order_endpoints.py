"""交易执行端点契约测试（/api/order、/api/order/cancel）——全程离线。

分层拦截点（每层都断言"拦截后不落下一层"）：
1. 认证中间件：无/错 key → 401（不触发 handler）
2. Pydantic 校验：非法体 → 422（不触发 handler）
3. 实盘确认：simulated=false 且 confirm_live 不显式 → 403（不触 SDK）
4. 前置风控闸（backend/core/trade_gate.py）：
   - 拒绝 → 403；模块不可用 → 403（显式失败不静默放行）
   - ORDER_RISK_GATE=0 时显式旁路
5. SDK 层以 FakeTradeSvc 截停（绝不发起真实网络请求）：
   - 可成交 → 200 信封 code=0；业务拒单 → 200 信封 code=1；NetworkError → 502

另覆盖 WS 鉴权（WebSocketAuthMiddleware）：受保护 /ws/trade 无 key → 4401、
未配置 key → 4503；带 query api_key 放行（fake ws 服务离线 stub）。
"""
import asyncio
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.main import app  # noqa: E402
import backend.api.routes as routes  # noqa: E402
from okx.ccxt.base.errors import NetworkError  # noqa: E402

KEY = 'order-test-key-789'
STATE = {'svc': None}


class FakeTradeSvc:
    """伪造交易服务：记录调用、按预置响应回放；network='error' 时抛 NetworkError"""

    def __init__(self, responses=None, network='none'):
        self.calls = []
        self.responses = responses or {}
        self.network = network
        self.simulated_seen = None

    def place_order(self, inst_id, side, ord_type, sz, px=None, td_mode='cash'):
        self.calls.append(('place', {'inst_id': inst_id, 'side': side, 'ord_type': ord_type,
                                     'sz': sz, 'px': px, 'td_mode': td_mode}))
        if self.network == 'error':
            raise NetworkError('conn refused')
        return self.responses.get('place', {'code': '0', 'data': [{'ordId': '9'}]})

    def cancel_order(self, inst_id, ord_id):
        self.calls.append(('cancel', {'inst_id': inst_id, 'ord_id': ord_id}))
        if self.network == 'error':
            raise NetworkError('conn refused')
        return self.responses.get('cancel', {'code': '0', 'data': [{'ordId': ord_id}]})

    async def start_private_ws(self, on_data_callback=None):
        raise RuntimeError('offline-stub')

    async def stop_private_ws(self):
        pass


def _install_risk(monkeypatch, approve=True, reason='LIMIT-OK'):
    """以 stub 模块替换 agents.risk_manager（不 import 真实 vc 模块）"""
    mod = types.ModuleType('agents.risk_manager')

    class _Limits:
        pass

    class _Agent:
        def __init__(self, limits=None):
            self.limits = limits

        def approve_trade(self, signal, portfolio):
            return (approve, reason)

    mod.RiskManagerAgent = _Agent
    mod.RiskLimits = _Limits
    monkeypatch.setitem(sys.modules, 'agents', types.ModuleType('agents'))
    monkeypatch.setitem(sys.modules, 'agents.risk_manager', mod)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('API_AUTH_KEY', KEY)
    monkeypatch.setenv('ORDER_RISK_GATE', '1')
    STATE['svc'] = FakeTradeSvc()
    monkeypatch.setattr(routes, 'get_trade_service', lambda simulated=None: _seen_svc(simulated))
    return TestClient(app)


_SEEN = {}


def _seen_svc(simulated):
    STATE['svc'].simulated_seen = simulated
    return STATE['svc']


ORDER_BODY = {'inst_id': 'BTC-USDT', 'side': 'buy', 'ord_type': 'limit',
              'sz': '0.01', 'px': '27000', 'td_mode': 'cash'}


# ==================== 认证门 ====================

def test_place_order_no_key_401(client):
    assert client.post('/api/order', json=ORDER_BODY).status_code == 401
    assert STATE['svc'].calls == []


def test_place_order_wrong_key_401(client):
    r = client.post('/api/order', json=ORDER_BODY, headers={'X-API-Key': 'wrong'})
    assert r.status_code == 401
    assert STATE['svc'].calls == []


def test_cancel_no_key_401(client):
    assert client.post('/api/order/cancel',
                       json={'inst_id': 'BTC-USDT', 'ord_id': '1'}).status_code == 401


# ==================== Pydantic 校验门 ====================

@pytest.mark.parametrize('bad_body', [
    dict(ORDER_BODY, side='hodl'),
    dict(ORDER_BODY, px=None),
    {'inst_id': 'BTC-USDT'},
    dict(ORDER_BODY, sz='-1'),
])
def test_place_order_invalid_body_422(client, bad_body):
    r = client.post('/api/order', json=bad_body, headers={'X-API-Key': KEY})
    assert r.status_code == 422
    assert STATE['svc'].calls == []


def test_cancel_invalid_body_422(client):
    r = client.post('/api/order/cancel', json={'inst_id': "x';evil--", 'ord_id': '1'},
                    headers={'X-API-Key': KEY})
    assert r.status_code == 422
    assert STATE['svc'].calls == []


# ==================== 实盘确认门 ====================

def test_live_without_confirm_403(client, monkeypatch):
    _install_risk(monkeypatch)
    r = client.post('/api/order', json=dict(ORDER_BODY, simulated=False),
                    headers={'X-API-Key': KEY})
    assert r.status_code == 403
    assert r.json()['code'] == 1
    assert 'confirm_live' in r.json()['msg']
    assert STATE['svc'].calls == []


def test_live_with_confirm_reaches_sdk(client, monkeypatch):
    _install_risk(monkeypatch)
    r = client.post('/api/order',
                    json=dict(ORDER_BODY, simulated=False, confirm_live=True),
                    headers={'X-API-Key': KEY})
    assert r.status_code == 200 and r.json()['code'] == 0
    assert STATE['svc'].calls == [(
        'place', {'inst_id': 'BTC-USDT', 'side': 'buy', 'ord_type': 'limit',
                  'sz': '0.01', 'px': '27000', 'td_mode': 'cash'})]
    assert STATE['svc'].simulated_seen is False


# ==================== 前置风控闸 ====================

def test_risk_reject_403(client, monkeypatch):
    _install_risk(monkeypatch, approve=False, reason='max_position_pct exceeded')
    r = client.post('/api/order', json=ORDER_BODY, headers={'X-API-Key': KEY})
    assert r.status_code == 403
    assert 'max_position_pct exceeded' in r.json()['msg']
    assert STATE['svc'].calls == []


def test_risk_unavailable_rejects(client, monkeypatch):
    """风控模块不可用必须显式拒绝（不静默降级放行）"""
    monkeypatch.setitem(sys.modules, 'agents', types.ModuleType('agents'))
    monkeypatch.setitem(sys.modules, 'agents.risk_manager', None)
    r = client.post('/api/order', json=ORDER_BODY, headers={'X-API-Key': KEY})
    assert r.status_code == 403
    assert '不可用' in r.json()['msg']
    assert STATE['svc'].calls == []


def test_risk_gate_disabled_bypasses(client, monkeypatch):
    monkeypatch.setenv('ORDER_RISK_GATE', '0')   # 不装风控 stub 也应直通（闸已显式关闭）
    r = client.post('/api/order', json=ORDER_BODY, headers={'X-API-Key': KEY})
    assert r.status_code == 200 and r.json()['code'] == 0


def test_default_mode_goes_to_demo(client, monkeypatch):
    _install_risk(monkeypatch)
    r = client.post('/api/order', json=ORDER_BODY, headers={'X-API-Key': KEY})
    assert r.json()['code'] == 0
    assert STATE['svc'].simulated_seen is True


# ==================== SDK 层错误契约 ====================

def test_place_order_business_reject_envelope(client, monkeypatch):
    _install_risk(monkeypatch)
    STATE['svc'] = FakeTradeSvc(
        responses={'place': {'code': '51008', 'msg': 'Insufficient balance', 'data': []}})
    r = client.post('/api/order', json=ORDER_BODY, headers={'X-API-Key': KEY})
    assert r.status_code == 200
    assert r.json()['code'] == 1
    assert '51008' in r.json()['msg'] or 'Insufficient' in r.json()['msg']


def test_place_order_network_error_502(client, monkeypatch):
    _install_risk(monkeypatch)
    STATE['svc'] = FakeTradeSvc(network='error')
    r = client.post('/api/order', json=ORDER_BODY, headers={'X-API-Key': KEY})
    assert r.status_code == 502
    assert r.json()['code'] == 1
    assert 'OKX 网络错误' in r.json()['msg']


def test_cancel_happy_and_business(client, monkeypatch):
    _install_risk(monkeypatch)
    r = client.post('/api/order/cancel',
                    json={'inst_id': 'BTC-USDT', 'ord_id': '7'}, headers={'X-API-Key': KEY})
    assert r.status_code == 200 and r.json()['code'] == 0
    assert STATE['svc'].calls == [('cancel', {'inst_id': 'BTC-USDT', 'ord_id': '7'})]

    STATE['svc'] = FakeTradeSvc(responses={'cancel': {'code': '51603', 'msg': 'Order does not exist.'}})
    r = client.post('/api/order/cancel',
                    json={'inst_id': 'BTC-USDT', 'ord_id': '7'}, headers={'X-API-Key': KEY})
    assert r.status_code == 200 and r.json()['code'] == 1


def test_cancel_network_error_502(client, monkeypatch):
    _install_risk(monkeypatch)
    STATE['svc'] = FakeTradeSvc(network='error')
    r = client.post('/api/order/cancel',
                    json={'inst_id': 'BTC-USDT', 'ord_id': '7'}, headers={'X-API-Key': KEY})
    assert r.status_code == 502 and r.json()['code'] == 1


# ==================== WebSocket 鉴权 ====================
# 注：TestClient 的 websocket portal 与"中间件 accept 后立刻 close"组合会挂起，
# 这里改为对 WebSocketAuthMiddleware 的纯 asyncio 直接单测（不开 portal，确定性强）。

def _run_ws_middleware(monkeypatch, scope, configured=True):
    """驱动 WebSocketAuthMiddleware：返回 (send 日志, 内层 app 是否被调用)

    configured=True 以 KEY 常量配置 API_AUTH_KEY（确定性，不依赖进程残留环境）。
    """
    if configured:
        monkeypatch.setenv('API_AUTH_KEY', KEY)
    else:
        monkeypatch.delenv('API_AUTH_KEY', raising=False)

    sent = []
    called = {'inner': False}

    async def inner_app(s, receive, send):
        called['inner'] = True

    events = [{'type': 'websocket.connect'},
              {'type': 'websocket.disconnect', 'code': 1000}]

    async def receive():
        if events:
            return events.pop(0)
        return {'type': 'websocket.disconnect', 'code': 1000}

    async def send(msg):
        sent.append(msg)

    from backend.main import WebSocketAuthMiddleware
    mw = WebSocketAuthMiddleware(inner_app)
    asyncio.run(mw(scope, receive, send))
    return sent, called['inner']


def test_ws_trade_wrong_key_close_4401(monkeypatch):
    sent, inner_called = _run_ws_middleware(
        monkeypatch,
        {'type': 'websocket', 'path': '/ws/trade', 'query_string': b'api_key=wrong'})
    assert [m['type'] for m in sent] == ['websocket.accept', 'websocket.close']
    assert sent[-1]['code'] == 4401
    assert inner_called is False


def test_ws_trade_missing_key_close_4401(monkeypatch):
    sent, inner_called = _run_ws_middleware(
        monkeypatch,
        {'type': 'websocket', 'path': '/ws/trade', 'query_string': b''})
    assert sent[-1]['type'] == 'websocket.close' and sent[-1]['code'] == 4401
    assert inner_called is False


def test_ws_trade_key_not_configured_close_4503(monkeypatch):
    sent, inner_called = _run_ws_middleware(
        monkeypatch,
        {'type': 'websocket', 'path': '/ws/trade', 'query_string': b'api_key=x'},
        configured=False)
    assert [m['type'] for m in sent] == ['websocket.accept', 'websocket.close']
    assert sent[-1]['code'] == 4503
    assert inner_called is False


def test_ws_trade_query_key_passes_to_router(monkeypatch):
    sent, inner_called = _run_ws_middleware(
        monkeypatch,
        {'type': 'websocket', 'path': '/ws/trade',
         'query_string': 'api_key='.encode('latin-1') + KEY.encode('latin-1')})
    assert sent == []            # 不拦截、不回包
    assert inner_called is True  # 放行到路由层


def test_ws_market_public_bypasses_mw(monkeypatch):
    """公开 /ws/market：不拦不回，直达路由层（因此契约测试绝不触公共 WS 网络路）"""
    sent, inner_called = _run_ws_middleware(
        monkeypatch,
        {'type': 'websocket', 'path': '/ws/market', 'query_string': b'inst_id=BTC-USDT'})
    assert sent == []
    assert inner_called is True
