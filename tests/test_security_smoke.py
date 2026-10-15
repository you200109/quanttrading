"""
安全冒烟测试（P4a 迁移产物，smoke_routes.py 的 pytest 化）

迁移自 scripts/smoke_routes.py——原脚本需真实拉起 uvicorn 子进程
（Windows/CI 均慢且偶发端口竞争）。本版用 FastAPI TestClient 覆盖同一组
安全不变量，认证中间件在请求时读取 API_AUTH_KEY 环境变量，
因此 401/503 两个场景均可通过 monkeypatch 环境变量在进程内验证：

1. 公开端点可用：/、/health、/openapi.json
2. 认证矩阵：无 key → 401；错误 key → 401；正确 key → 放行且 <500
3. 未配置 API_AUTH_KEY → 受保护端点 503（绝不使用硬编码默认密钥）
4. vc 端点信封结构（code 字段）
5. nexus 文件端点 HTTP 层拒绝路径遍历
6. openapi 路由清点 >= 30
7. 全部探测不出现 5xx

外网 IO 端点（OKX REST）不在本文件范围（见 test_api_contract.py）。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.main import app  # noqa: E402

KEY = 'smoke-test-key-12345'

TRAVERSAL_PAYLOADS = (
    '..%2f..%2fetc%2fpasswd',
    '....%2f....%2fetc%2fpasswd',
    '%2e%2e%2f.git%2fconfig',
)


@pytest.fixture
def client_with_key(monkeypatch):
    monkeypatch.setenv('API_AUTH_KEY', KEY)
    return TestClient(app)


@pytest.fixture
def client_no_key(monkeypatch):
    monkeypatch.delenv('API_AUTH_KEY', raising=False)
    return TestClient(app)


class TestPublicEndpoints:
    def test_index(self, client_with_key):
        assert client_with_key.get('/').status_code == 200

    def test_health(self, client_with_key):
        r = client_with_key.get('/health')
        assert r.status_code == 200
        assert r.json()['status'] == 'ok'

    def test_openapi_inventory(self, client_with_key):
        r = client_with_key.get('/openapi.json')
        assert r.status_code == 200
        paths = r.json()['paths']
        assert len(paths) >= 30, f'paths={len(paths)}'


class TestAuthMatrix:
    def test_no_key_401(self, client_with_key):
        assert client_with_key.get('/api/vc/strategies').status_code == 401

    def test_wrong_key_401(self, client_with_key):
        r = client_with_key.get('/api/vc/strategies', headers={'X-API-Key': 'wrong-key'})
        assert r.status_code == 401

    def test_correct_key_passes(self, client_with_key):
        r = client_with_key.get('/api/vc/strategies', headers={'X-API-Key': KEY})
        assert r.status_code not in (401, 503)
        assert 0 < r.status_code < 500

    def test_vc_envelope_shape(self, client_with_key):
        r = client_with_key.get('/api/vc/memory/nexus', headers={'X-API-Key': KEY})
        assert r.status_code == 200
        assert 'code' in r.json()


class TestNoKeyConfigured:
    """未配置 API_AUTH_KEY：受保护端点 503，公开端点不受影响"""

    def test_protected_503(self, client_no_key):
        r = client_no_key.get('/api/vc/strategies')
        assert r.status_code == 503
        assert 'API_AUTH_KEY' in r.json()['msg']

    def test_health_still_200(self, client_no_key):
        assert client_no_key.get('/health').status_code == 200

    def test_no_hardcoded_fallback(self, client_no_key):
        """503 而非放行：证明没有硬编码默认密钥"""
        for key in ('', 'admin', 'test', 'quanttrading'):
            r = client_no_key.get('/api/vc/strategies', headers={'X-API-Key': key})
            assert r.status_code == 503, f'key={key!r} 不应放行'


class TestTraversalOverHttp:
    @pytest.mark.parametrize('payload', TRAVERSAL_PAYLOADS)
    def test_nexus_traversal_rejected(self, client_with_key, payload):
        r = client_with_key.get(f'/api/vc/memory/nexus/{payload}',
                                headers={'X-API-Key': KEY})
        assert r.status_code != 200 or 'Invalid filename' in r.text

    def test_legal_file_still_served(self, client_with_key):
        r = client_with_key.get('/api/vc/memory/nexus/version.json',
                                headers={'X-API-Key': KEY})
        assert r.status_code == 200
        assert r.json()['code'] == 0
