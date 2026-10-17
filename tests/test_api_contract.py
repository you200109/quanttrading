"""
API 端点契约测试（P4b）

以 openapi schema 为路由清单权威来源（40 ops），按"是否依赖外部 IO"
分三类验证，保证 CI 内确定性、无网络、无副作用：

1. 本地端点（LOCAL_*）：完整行为契约
   - 公开：无 key 可达且 <500（信封端点校验 code 字段）
   - 受保护：无 key → 401；正确 key → 放行且 <500（vc 端点校验 code 信封）
2. 外网 IO 端点（EXTERNAL_*，OKX REST）：只验认证分类，不带 key 实调
   - 公开：断言 auth.is_protected(path) 为 False（中间件放行，不打网络）
   - 受保护：无 key → 401（中间件在 handler 前拒绝，不打网络）
3. POST 端点：
   - Pydantic 体验证型：非法体 → 422（证明认证已过且脏值被拦在 handler 前）
   - body:dict 型（有真实副作用）：只验无 key → 401

完整性护栏：openapi 全量路径必须被恰好一个分类表覆盖——
新增路由若忘记补契约，test_route_inventory_complete 直接失败。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.core.auth import is_protected  # noqa: E402
from backend.main import app  # noqa: E402

KEY = 'contract-test-key-456'

# ---- 本地公开端点：无 key 可达，<500 ----
LOCAL_PUBLIC_GET = [
    '/',
    '/health',
    '/api/system/resources',
    '/api/system/dashboard',
    '/api/system/traces',
    '/api/system/traces/stats',
    '/api/system/alerts',
    '/api/indicators',
    '/api/indicators/categories',
]

# ---- 本地受保护端点：401/200 矩阵 + vc code 信封 ----
LOCAL_PROTECTED_GET = [
    '/api/vc/agi/status',
    '/api/vc/agi/learning-report',
    '/api/vc/strategies',
    '/api/vc/risk/status',
    '/api/vc/memory/nexus',
    '/api/vc/memory/nexus/version.json',
    '/api/vc/github/seeds',
]

# ---- 外网 IO 公开端点：只断言中间件分类（不打网络） ----
EXTERNAL_PUBLIC_GET = [
    '/api/klines/BTC-USDT',
    '/api/klines/multi/BTC-USDT',
    '/api/orderbook/BTC-USDT',
    '/api/ticker/BTC-USDT',
    '/api/tickers',
    '/api/instruments',
]

# ---- 外网 IO 受保护端点：无 key → 401（中间件拒绝，不打网络） ----
EXTERNAL_PROTECTED_GET = [
    '/api/account/balance',
    '/api/account/positions',
    '/api/orders/pending',
    '/api/orders/history',
    '/api/orders/history/archive',
    '/api/fills',
    '/api/fills/history',
    '/api/bills',
    '/api/bills/archive',
    '/api/history/download',
]

# ---- Pydantic POST：非法体 → 422 ----
# (path, 是否受保护)
PYDANTIC_POST = [
    ('/api/vc/backtest/vc', True),
    ('/api/backtest', True),
    ('/api/indicators/calculate', False),
    ('/api/order', True),
    ('/api/order/cancel', True),
]

# ---- body:dict POST（真实副作用）：只验无 key → 401 ----
DICT_POST = [
    '/api/vc/agi/evolve',
    '/api/vc/risk/approve',
    '/api/vc/github/learn',
]

INVALID_BODY = {'inst_id': "x';evil--", 'bar': 'bad', 'limit': 'not-a-number'}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('API_AUTH_KEY', KEY)
    return TestClient(app)


@pytest.fixture
def openapi_paths():
    return set(app.openapi()['paths'])


class TestLocalPublic:
    @pytest.mark.parametrize('path', LOCAL_PUBLIC_GET)
    def test_reachable_without_key(self, client, path):
        r = client.get(path)
        assert r.status_code < 500, f'{path} -> {r.status_code}'
        assert r.status_code != 401

    @pytest.mark.parametrize('path', LOCAL_PUBLIC_GET)
    def test_not_protected_by_middleware(self, path):
        assert is_protected(path) is False

    def test_vc_style_envelopes_have_code(self, client):
        """/api/system 与 /api/indicators 系列返回 code 信封"""
        for path in ('/api/system/resources', '/api/system/dashboard',
                     '/api/indicators', '/api/indicators/categories'):
            body = client.get(path).json()
            assert body['code'] == 0, path


class TestLocalProtected:
    @pytest.mark.parametrize('path', LOCAL_PROTECTED_GET)
    def test_no_key_401(self, client, path):
        assert client.get(path).status_code == 401

    @pytest.mark.parametrize('path', LOCAL_PROTECTED_GET)
    def test_wrong_key_401(self, client, path):
        r = client.get(path, headers={'X-API-Key': 'wrong'})
        assert r.status_code == 401

    @pytest.mark.parametrize('path', LOCAL_PROTECTED_GET)
    def test_correct_key_ok_with_envelope(self, client, path):
        r = client.get(path, headers={'X-API-Key': KEY})
        assert r.status_code == 200, f'{path} -> {r.status_code} {r.text[:80]}'
        assert r.json()['code'] == 0, path

    @pytest.mark.parametrize('path', LOCAL_PROTECTED_GET)
    def test_protected_by_middleware(self, path):
        assert is_protected(path) is True


class TestExternalAuthClassification:
    """外网端点只验认证分类，绝不在契约测试里打 OKX 网络"""

    @pytest.mark.parametrize('path', EXTERNAL_PUBLIC_GET)
    def test_public_not_protected(self, path):
        assert is_protected(path) is False

    @pytest.mark.parametrize('path', EXTERNAL_PROTECTED_GET)
    def test_protected_no_key_401(self, client, path):
        assert client.get(path).status_code == 401

    @pytest.mark.parametrize('path', EXTERNAL_PROTECTED_GET)
    def test_protected_by_middleware(self, path):
        assert is_protected(path) is True


class TestPostContracts:
    @pytest.mark.parametrize('path,protected', PYDANTIC_POST,
                             ids=[p for p, _ in PYDANTIC_POST])
    def test_invalid_body_422(self, client, path, protected):
        """非法体被 Pydantic 拦在 handler 前：证明认证已过且脏值不流向 OKX"""
        headers = {'X-API-Key': KEY} if protected else {}
        r = client.post(path, json=INVALID_BODY, headers=headers)
        assert r.status_code == 422, f'{path} -> {r.status_code} {r.text[:80]}'

    @pytest.mark.parametrize('path,protected', PYDANTIC_POST,
                             ids=[p for p, _ in PYDANTIC_POST])
    def test_auth_classification(self, path, protected):
        assert is_protected(path) is protected

    @pytest.mark.parametrize('path', DICT_POST)
    def test_dict_post_no_key_401(self, client, path):
        """body:dict 端点有真实副作用，只验证认证门（不带 key 调用）"""
        assert client.post(path, json={}).status_code == 401

    @pytest.mark.parametrize('path', DICT_POST)
    def test_dict_post_protected(self, path):
        assert is_protected(path) is True


class TestInventoryCompleteness:
    """护栏：openapi 全量路径必须恰好被一个分类表覆盖"""

    # 契约表中的具体路径 → openapi 模板路径（供清点比对）
    _TO_TEMPLATE = {
        '/api/vc/memory/nexus/version.json': '/api/vc/memory/nexus/{filename}',
        '/api/klines/BTC-USDT': '/api/klines/{inst_id}',
        '/api/klines/multi/BTC-USDT': '/api/klines/multi/{inst_id}',
        '/api/orderbook/BTC-USDT': '/api/orderbook/{inst_id}',
        '/api/ticker/BTC-USDT': '/api/ticker/{inst_id}',
    }

    def test_route_inventory_complete(self, openapi_paths):
        covered = (
            set(LOCAL_PUBLIC_GET)
            | set(LOCAL_PROTECTED_GET)
            | set(EXTERNAL_PUBLIC_GET)
            | set(EXTERNAL_PROTECTED_GET)
            | {p for p, _ in PYDANTIC_POST}
            | set(DICT_POST)
        )
        covered = {self._TO_TEMPLATE.get(p, p) for p in covered}
        # /docs、/openapi.json、/redoc、/docs/oauth2-redirect 为框架文档路由，无需契约
        framework_docs = {p for p in openapi_paths
                          if p.startswith(('/docs', '/openapi', '/redoc'))}
        expected = openapi_paths - framework_docs
        assert covered == expected, (
            f'未覆盖: {sorted(expected - covered)}; '
            f'表中多余: {sorted(covered - expected)}')

    def test_total_route_count_stable(self, openapi_paths):
        """路由总量锁定 40——新增/删除路由必须显式更新契约表"""
        assert len(openapi_paths) == 40, (
            f'路由数变为 {len(openapi_paths)}，请更新契约分类表')
