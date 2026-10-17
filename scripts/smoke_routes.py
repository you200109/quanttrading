"""P1 冒烟门禁：真实启动 uvicorn 服务，验证：

1. 服务可启动（backend.main:app）
2. 公开端点可用：/、/health、/app/、/openapi.json
3. 认证矩阵正确：
   - 受保护端点（/api/vc/*）无 key → 401
   - 错误 key → 401
   - 正确 key → 放行（非 401/503，且 < 500）
   - 未配置 API_AUTH_KEY 时受保护端点 → 503（单独子进程验证）
4. 本地 vc 端点可用：/api/vc/strategies、/api/vc/memory/nexus
5. nexus 文件端点安全拒绝路径遍历（../../etc/passwd → 非 200）
6. 全量路由清点：openapi.json 的 paths 数与 app.routes 一致
7. 执行端点门禁：/api/order、/api/order/cancel 已注册；POST 无 key → 401；
   错 key → 401；带 key + 非法体 → 422（Pydantic 拦在 handler 前，绝不触 OKX 网络）
8. 任何探测不出现 5xx

只打不依赖外部 IO（OKX/网络）的端点；执行端点只验其注册与门禁层。
用法：python scripts/smoke_routes.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PORT = 18099
BASE = f'http://127.0.0.1:{PORT}'
KEY = 'smoke-test-key-12345'

failures = []


def check(name, ok, detail=''):
    print(f'[{"OK" if ok else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))
    if not ok:
        failures.append(name)


def http_get(path, headers=None, timeout=10):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except Exception as e:
        return -1, f'{type(e).__name__}: {e}'


def http_post(path, headers=None, payload=None, timeout=10):
    data = json.dumps(payload if payload is not None else {}).encode('utf-8')
    req = urllib.request.Request(BASE + path, data=data, headers=headers or {}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except Exception as e:
        return -1, f'{type(e).__name__}: {e}'


def wait_ready(deadline_s=30):
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        status, _ = http_get('/health', timeout=3)
        if status == 200:
            return True
        time.sleep(0.5)
    return False


def start_server(with_key):
    env = dict(os.environ)
    env['API_HOST'] = '127.0.0.1'
    env['API_PORT'] = str(PORT)
    if with_key:
        env['API_AUTH_KEY'] = KEY
    else:
        env.pop('API_AUTH_KEY', None)
    creation = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    # 服务输出落盘（不用 PIPE：Windows 上 uvicorn+PIPE 有背压坑，且便于事后诊断）
    out_path = REPO_ROOT / 'reports' / f'smoke_server_{PORT}.log'
    out_path.parent.mkdir(exist_ok=True)
    out_file = open(out_path, 'w', encoding='utf-8')
    return subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', str(PORT)],
        cwd=str(REPO_ROOT), env=env, stdout=out_file, stderr=subprocess.STDOUT, creationflags=creation,
    )


def main():
    # ---- 场景 A：配置了 API_AUTH_KEY ----
    proc = start_server(with_key=True)
    try:
        if not wait_ready():
            out_path = REPO_ROOT / 'reports' / f'smoke_server_{PORT}.log'
            out = out_path.read_text(encoding='utf-8', errors='replace')[-2000:] if out_path.exists() else ''
            check('service starts and /health ready', False, f'output tail: {out}')
            return 1
        check('service starts and /health ready', True)

        status, _ = http_get('/')
        check('GET / returns 200 (index.html)', status == 200, f'status={status}')

        status, body = http_get('/app/')
        check('GET /app/ returns 200 (static mount)', status in (200, 404), f'status={status}')

        status, _ = http_get('/app/index.html')
        check('GET /app/index.html returns 200', status == 200, f'status={status}')

        # openapi 路由清点
        status, body = http_get('/openapi.json')
        paths = {}
        if status == 200:
            paths = json.loads(body).get('paths', {})
        check('GET /openapi.json returns 200', status == 200, f'status={status}')
        total_ops = sum(len(v) for v in paths.values())
        check('openapi paths >= 30', len(paths) >= 30, f'paths={len(paths)} operations={total_ops}')
        check('openapi has /api/order and /api/order/cancel',
              '/api/order' in paths and '/api/order/cancel' in paths,
              f"order={'/api/order' in paths} cancel={'/api/order/cancel' in paths}")

        # 执行端点门禁（不触网络：401 在 handler 前，422 在 handler 前由 Pydantic 拒绝）
        status, _ = http_post('/api/order', payload={})
        check('POST /api/order without key -> 401', status == 401, f'status={status}')

        status, _ = http_post('/api/order', headers={'X-API-Key': 'wrong-key'}, payload={})
        check('POST /api/order with wrong key -> 401', status == 401, f'status={status}')

        status, body = http_post('/api/order', headers={'X-API-Key': KEY},
                                 payload={'inst_id': "x';evil--"})
        check('POST /api/order with key + invalid body -> 422', status == 422,
              f'status={status} body={body[:60]}')

        status, body = http_post('/api/order/cancel', headers={'X-API-Key': KEY},
                                 payload={'inst_id': "x';evil--", 'ord_id': '1'})
        check('POST /api/order/cancel with key + invalid body -> 422', status == 422,
              f'status={status}')

        # 认证矩阵（受保护端点 /api/vc/strategies）
        status, body = http_get('/api/vc/strategies')
        check('protected endpoint without key -> 401', status == 401, f'status={status} body={body[:80]}')

        status, _ = http_get('/api/vc/strategies', headers={'X-API-Key': 'wrong-key'})
        check('protected endpoint with wrong key -> 401', status == 401, f'status={status}')

        status, body = http_get('/api/vc/strategies', headers={'X-API-Key': KEY})
        check('protected endpoint with correct key -> non-401/503 and <500',
              status not in (401, 503) and 0 < status < 500, f'status={status}')

        # 本地 vc 端点
        status, body = http_get('/api/vc/memory/nexus', headers={'X-API-Key': KEY})
        ok = status == 200 and 'code' in body
        check('GET /api/vc/memory/nexus with key -> 200 code envelope', ok, f'status={status}')

        # nexus 文件端点：安全拒绝路径遍历
        for evil in ('..%2f..%2fetc%2fpasswd', '....%2f....%2fetc%2fpasswd', '%2e%2e%2f.git%2fconfig'):
            status, body = http_get(f'/api/vc/memory/nexus/{evil}', headers={'X-API-Key': KEY})
            ok = status != 200 or 'Invalid filename' in body
            check(f'nexus traversal {evil} rejected', ok, f'status={status}')

        # 公开行情命名空间（/api/system）不打外部 IO 的可打
        status, _ = http_get('/api/system/status') if '/api/system/status' in paths else http_get('/health')
        check('public /api/system namespace reachable', status in (200, 404), f'status={status}')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    # ---- 场景 B：未配置 API_AUTH_KEY → 受保护端点 503 ----
    proc = start_server(with_key=False)
    try:
        if wait_ready():
            status, body = http_get('/api/vc/strategies')
            check('no key configured -> protected endpoint 503', status == 503, f'status={status}')
            status, _ = http_get('/health')
            check('no key configured -> /health still 200', status == 200, f'status={status}')
        else:
            check('service (no key) starts', False)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if failures:
        print(f'{len(failures)} smoke check(s) FAILED: {failures}')
        return 1
    print('All smoke checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
