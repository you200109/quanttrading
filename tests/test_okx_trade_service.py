"""OKX 交易服务（K1：pyted okx 2.1.2 → okx-exchange 0.0.169 换血）单元测试（全部离线）

覆盖：
- 构造参数映射：凭证键名（apiKey/secret/password）、沙箱开关（sandbox、
  x-simulated-trading 头）、hostname（OKX_API_HOST 透传）、enableRateLimit
- 11 个私有原始端点的方法名与参数透传（含 limit 字符串、instId 可选、
  positions 空参、balance 取 data[0]）
- 响应解析契约：code=='0' 取 data；业务错误（BaseError 或 code!='0' 字典）
  落默认值并记日志；非 dict 响应落默认值
- place/cancel：校验分支（不发起调用）、参数映射、业务错误从 ccxt 异常
  消息恢复 OKX 原始响应、不可恢复时退化、NetworkError 原样上抛
- 单例工厂与私有 WS URL（跟随 OKX_API_HOST）

不发起任何网络请求；最后一条用例使用真实 okx-exchange（仅构造，零 IO）
锁定配置键名映射与真 SDK 行为一致。
"""
import logging
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import backend.core.okx_trade_service as trade_mod  # noqa: E402
from okx import OkxSync as RealOkxSync  # noqa: E402
from okx.ccxt.base.errors import BaseError, NetworkError  # noqa: E402


class FakeOkxSync:
    """伪造 OkxSync：记录构造配置与每次调用，按预置响应回放（响可为异常对象）"""

    last_config = None

    def __init__(self, config):
        FakeOkxSync.last_config = dict(config)
        self.apiKey = config.get('apiKey')
        self.secret = config.get('secret')
        self.password = config.get('password')
        self.sandbox = bool(config.get('sandbox'))
        self.headers = {'x-simulated-trading': '1'} if self.sandbox else {}
        self.calls = []
        self.responses = {}

    def _respond(self, name, params):
        self.calls.append((name, params))
        resp = self.responses.get(name, {'code': '0', 'data': []})
        if isinstance(resp, BaseException):
            raise resp
        return resp

    def __getattr__(self, name):
        if name.startswith('private_'):
            return lambda params: self._respond(name, params)
        raise AttributeError(name)


@pytest.fixture()
def svc(monkeypatch):
    monkeypatch.setattr(trade_mod, 'OkxSync', FakeOkxSync)
    monkeypatch.setattr(trade_mod, '_trade_services', {})
    monkeypatch.setenv('OKX_API_KEY', 'k-123')
    monkeypatch.setenv('OKX_SECRET_KEY', 's-456')
    monkeypatch.setenv('OKX_PASSPHRASE', 'p-789')
    monkeypatch.setenv('OKX_SIMULATED', '1')
    monkeypatch.delenv('OKX_API_HOST', raising=False)
    FakeOkxSync.last_config = None
    return trade_mod.OKXTradeService()


# ==================== 构造参数映射 ====================

def test_constructor_maps_credentials_and_sandbox(svc):
    assert svc.simulated is True
    assert FakeOkxSync.last_config == {
        'apiKey': 'k-123',
        'secret': 's-456',
        'password': 'p-789',
        'hostname': 'www.okx.com',
        'sandbox': True,
        'enableRateLimit': True,
    }
    assert svc.client.headers.get('x-simulated-trading') == '1'


def test_explicit_simulated_overrides_env(monkeypatch):
    monkeypatch.setattr(trade_mod, 'OkxSync', FakeOkxSync)
    monkeypatch.setenv('OKX_SIMULATED', '1')
    FakeOkxSync.last_config = None
    service = trade_mod.OKXTradeService(simulated=False)
    assert service.simulated is False
    assert FakeOkxSync.last_config['sandbox'] is False
    assert 'x-simulated-trading' not in service.client.headers


def test_simulated_env_default_off(monkeypatch):
    monkeypatch.setattr(trade_mod, 'OkxSync', FakeOkxSync)
    monkeypatch.setenv('OKX_SIMULATED', '0')
    FakeOkxSync.last_config = None
    trade_mod.OKXTradeService()
    assert FakeOkxSync.last_config['sandbox'] is False


def test_hostname_env_passthrough(monkeypatch):
    monkeypatch.setattr(trade_mod, 'OkxSync', FakeOkxSync)
    monkeypatch.setenv('OKX_API_HOST', 'aws.okx.com')
    FakeOkxSync.last_config = None
    service = trade_mod.OKXTradeService()
    assert FakeOkxSync.last_config['hostname'] == 'aws.okx.com'
    assert service.ws_private_url == 'wss://ws.aws.okx.com:8443/ws/v5/private'


def test_ws_private_url_default_host(svc):
    assert svc.ws_private_url == 'wss://ws.www.okx.com:8443/ws/v5/private'


# ==================== getter 参数透传与解析 ====================

GETTER_CASES = [
    ('pending-默认',
     lambda s: s.get_pending_orders(),
     'private_get_trade_orders_pending', {'instType': 'SPOT'}),
    ('pending-带instId',
     lambda s: s.get_pending_orders('SWAP', 'BTC-USDT-SWAP'),
     'private_get_trade_orders_pending', {'instType': 'SWAP', 'instId': 'BTC-USDT-SWAP'}),
    ('orders-history',
     lambda s: s.get_orders_history('SPOT', '20'),
     'private_get_trade_orders_history', {'instType': 'SPOT', 'limit': '20'}),
    ('orders-history-archive',
     lambda s: s.get_orders_history_archive(),
     'private_get_trade_orders_history_archive', {'instType': 'SPOT', 'limit': '50'}),
    ('fills',
     lambda s: s.get_fills(),
     'private_get_trade_fills', {'instType': 'SPOT', 'limit': '50'}),
    ('fills-history',
     lambda s: s.get_fills_history(),
     'private_get_trade_fills_history', {'instType': 'SPOT', 'limit': '50'}),
    ('bills',
     lambda s: s.get_account_bills(),
     'private_get_account_bills', {'limit': '50'}),
    ('bills-archive',
     lambda s: s.get_account_bills_archive('10'),
     'private_get_account_bills_archive', {'limit': '10'}),
    ('positions-默认',
     lambda s: s.get_account_position(),
     'private_get_account_positions', {}),
    ('positions-带instType',
     lambda s: s.get_account_position('SWAP'),
     'private_get_account_positions', {'instType': 'SWAP'}),
]


@pytest.mark.parametrize('label,call,expected_name,expected_params',
                         GETTER_CASES, ids=[c[0] for c in GETTER_CASES])
def test_getter_param_mapping_and_data(svc, label, call, expected_name, expected_params):
    svc.client.responses[expected_name] = {'code': '0', 'data': [{'id': 'x'}]}
    result = call(svc)
    assert svc.client.calls == [(expected_name, expected_params)]
    assert result == [{'id': 'x'}]


def test_balance_returns_first_entry_and_empty_default(svc):
    svc.client.responses['private_get_account_balance'] = {
        'code': '0', 'data': [{'totalEq': '1'}, {'ignored': True}]}
    assert svc.get_account_balance() == {'totalEq': '1'}
    svc.client.responses['private_get_account_balance'] = {'code': '0', 'data': []}
    assert svc.get_account_balance() == {}


# ==================== 错误契约 ====================

def test_business_error_dict_falls_back_to_default(svc):
    svc.client.responses['private_get_trade_fills'] = {'code': '51008', 'msg': 'Insufficient'}
    assert svc.get_fills() == []


def test_business_error_exception_falls_back_with_warning(svc, caplog):
    svc.client.responses['private_get_trade_orders_pending'] = BaseError(
        'okx {"code":"51008","msg":"Insufficient balance"}')
    with caplog.at_level(logging.WARNING, logger='OKXTradeService'):
        assert svc.get_pending_orders() == []
    assert any(r.name == 'OKXTradeService' and '业务错误' in r.getMessage()
               for r in caplog.records)


def test_unexpected_response_shape_falls_back(svc):
    svc.client.responses['private_get_trade_fills'] = ['unexpected']
    assert svc.get_fills() == []


def test_network_error_propagates(svc):
    svc.client.responses['private_get_trade_orders_pending'] = NetworkError('conn reset')
    with pytest.raises(NetworkError):
        svc.get_pending_orders()

    svc.client.responses['private_post_trade_order'] = NetworkError('conn reset')
    with pytest.raises(NetworkError):
        svc.place_order('BTC-USDT', 'buy', 'market', '1')

    svc.client.responses['private_post_trade_cancel_order'] = NetworkError('conn reset')
    with pytest.raises(NetworkError):
        svc.cancel_order('BTC-USDT', '1')


# ==================== 下单 / 撤单 ====================

def test_place_order_validation_never_calls_sdk(svc):
    assert svc.place_order('BTC-USDT', 'hodl', 'limit', '1', px='2') == {
        'code': '1', 'msg': f'Invalid side: hodl, must be one of {svc.VALID_SIDES}'}
    assert svc.place_order('BTC-USDT', 'buy', 'stop', '1', px='2') == {
        'code': '1', 'msg': f'Invalid ord_type: stop, must be one of {svc.VALID_ORD_TYPES}'}
    assert svc.place_order('', 'buy', 'limit', '1', px='2') == {
        'code': '1', 'msg': 'inst_id and sz are required'}
    assert svc.place_order('BTC-USDT', 'buy', 'limit', '') == {
        'code': '1', 'msg': 'inst_id and sz are required'}
    assert svc.place_order('BTC-USDT', 'buy', 'limit', '1') == {
        'code': '1', 'msg': 'px is required for limit orders'}
    assert svc.client.calls == []


def test_place_order_maps_params(svc):
    svc.client.responses['private_post_trade_order'] = {'code': '0', 'data': [{'ordId': '9'}]}
    resp = svc.place_order('BTC-USDT', 'buy', 'limit', 1, px=2)
    assert resp == {'code': '0', 'data': [{'ordId': '9'}]}
    assert svc.client.calls == [('private_post_trade_order', {
        'instId': 'BTC-USDT', 'tdMode': 'cash', 'side': 'buy',
        'ordType': 'limit', 'sz': '1', 'px': '2'})]

    svc.place_order('BTC-USDT', 'sell', 'market', '1', td_mode='cross')
    assert svc.client.calls[-1] == ('private_post_trade_order', {
        'instId': 'BTC-USDT', 'tdMode': 'cross', 'side': 'sell',
        'ordType': 'market', 'sz': '1'})


def test_place_order_recovers_raw_response_from_sdk_error(svc):
    raw = '{"code":"51008","msg":"Insufficient balance","data":[]}'
    svc.client.responses['private_post_trade_order'] = BaseError('okx ' + raw)
    assert svc.place_order('BTC-USDT', 'buy', 'market', '1') == {
        'code': '51008', 'msg': 'Insufficient balance', 'data': []}


def test_place_order_unrecoverable_error_falls_back(svc):
    svc.client.responses['private_post_trade_order'] = BaseError('boom')
    assert svc.place_order('BTC-USDT', 'buy', 'market', '1') == {
        'code': '1', 'msg': 'boom'}


def test_cancel_order_maps_params_and_recovers(svc):
    svc.client.responses['private_post_trade_cancel_order'] = {
        'code': '0', 'data': [{'ordId': '7'}]}
    assert svc.cancel_order('BTC-USDT', '7') == {'code': '0', 'data': [{'ordId': '7'}]}
    assert svc.client.calls == [('private_post_trade_cancel_order',
                                 {'instId': 'BTC-USDT', 'ordId': '7'})]

    svc.client.responses['private_post_trade_cancel_order'] = BaseError(
        'okx {"code":"51603","msg":"Order does not exist."}')
    assert svc.cancel_order('BTC-USDT', '7')['code'] == '51603'


# ==================== 按模式缓存工厂 ====================

def test_get_trade_service_same_mode_singleton(monkeypatch):
    """同一模式复用同一实例（SDK sandbox 头构造期绑定，不可热切换）。"""
    monkeypatch.setattr(trade_mod, 'OkxSync', FakeOkxSync)
    monkeypatch.setattr(trade_mod, '_trade_services', {})
    first = trade_mod.get_trade_service(simulated=True)
    second = trade_mod.get_trade_service(simulated=True)
    assert first is second
    assert isinstance(first, trade_mod.OKXTradeService)


def test_get_trade_service_modes_are_separate(monkeypatch):
    """模拟盘/实盘返回不同实例，且互不污染缓存桶。"""
    monkeypatch.setattr(trade_mod, 'OkxSync', FakeOkxSync)
    monkeypatch.setattr(trade_mod, '_trade_services', {})
    demo = trade_mod.get_trade_service(simulated=True)
    live = trade_mod.get_trade_service(simulated=False)
    assert demo is not live
    assert trade_mod.get_trade_service(simulated=True) is demo
    assert trade_mod.get_trade_service(simulated=False) is live
    assert demo.simulated is True
    assert live.simulated is False
    assert trade_mod.get_trade_service(simulated=True).client.headers.get('x-simulated-trading') == '1'
    assert 'x-simulated-trading' not in trade_mod.get_trade_service(simulated=False).client.headers


def test_get_trade_service_none_follows_env(monkeypatch):
    monkeypatch.setattr(trade_mod, 'OkxSync', FakeOkxSync)
    monkeypatch.setattr(trade_mod, '_trade_services', {})
    monkeypatch.setenv('OKX_SIMULATED', '0')
    assert trade_mod.get_trade_service().simulated is False
    monkeypatch.setenv('OKX_SIMULATED', '1')
    assert trade_mod.get_trade_service().simulated is True


# ==================== 真 SDK 配置键名锁定（零网络） ====================

def test_real_sdk_accepts_our_config_mapping(monkeypatch):
    """用真实 okx-exchange（不 mock）验证构造键名：password/sandbox/hostname/enableRateLimit。

    仅构造客户端，不发起任何请求；防止未来换包时键名静默漂移（如 passphrase 写错）。
    """
    monkeypatch.setenv('OKX_API_KEY', 'k1')
    monkeypatch.setenv('OKX_SECRET_KEY', 's1')
    monkeypatch.setenv('OKX_PASSPHRASE', 'p1')
    monkeypatch.setenv('OKX_SIMULATED', '1')
    monkeypatch.delenv('OKX_API_HOST', raising=False)
    service = trade_mod.OKXTradeService()
    client = service.client
    assert isinstance(client, RealOkxSync)
    assert client.apiKey == 'k1'
    assert client.secret == 's1'
    assert client.password == 'p1'
    assert client.sandbox is True
    assert client.enableRateLimit is True
    assert client.headers.get('x-simulated-trading') == '1'
    assert client.hostname == 'www.okx.com'
