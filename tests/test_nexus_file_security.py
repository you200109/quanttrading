"""
nexus 文件端点安全测试（P4a 迁移产物）

合并原 scripts/test_path_traversal.py（复刻校验逻辑）与
scripts/test_nexus_endpoint_e2e.py（真实代码路径）——迁移后直接调用
backend.api.vc_routes.get_nexus_file 真实函数，覆盖两脚本用例并集。

2026-10-16 P4a：原脚本硬编码旧副本绝对路径（ww/quanttrading/...），
在当前工作副本下失效；改为 Path(__file__) 参数化，并收入 CI 的
pytest tests/ 步骤（原为无人调用的孤儿脚本）。
"""
import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.api.vc_routes import get_nexus_file  # noqa: E402

# (filename, 期望 code)：0=合法放行 / 1=拒绝
CASES = [
    # ---- 合法文件（须真实存在于 memory/nexus）----
    ('version.json', 0),
    ('evolution_state.json', 0),
    ('gh_strategy_library.json', 0),
    # ---- 合法字符但文件不存在 ----
    ('normal_file-123.json', 1),
    ('nonexistent.json', 1),
    # ---- 路径遍历 ----
    ('../.env', 1),
    ('../../backend/.env', 1),
    ('..%2f.env', 1),
    ('sub/../../../etc/passwd', 1),
    ('a/b.json', 1),
    ('a\\b.json', 1),
    ('....//x', 1),
    # ---- 绝对路径 / UNC / 点文件 / 空 / 非法字符 ----
    ('/etc/passwd', 1),
    ('C:\\Windows\\win.ini', 1),
    ('\\\\server\\share\\x', 1),
    ('.', 1),
    ('..', 1),
    ('.hidden', 1),
    ('', 1),
    ('空格 文件.json', 1),
    ('中文.json', 1),
    ('file\x00.json', 1),
]


@pytest.mark.parametrize('filename,expected_code', CASES,
                         ids=[repr(c[0]) for c in CASES])
def test_get_nexus_file_security(filename, expected_code):
    """真实路由函数：合法文件放行（code 0），其余一律拒绝（code 1）"""
    result = asyncio.run(get_nexus_file(filename))
    assert result['code'] == expected_code, (
        f"{filename!r} -> code={result['code']} msg={result.get('msg', '')[:60]}")


def test_legal_files_actually_exist():
    """防止契约文件被误删导致合法用例名不副实（code 0 的前提）"""
    nexus = REPO_ROOT / 'vigilant-couscous' / 'memory' / 'nexus'
    for name, code in CASES:
        if code == 0:
            assert (nexus / name).is_file(), f"合法用例 {name!r} 在 nexus 目录不存在"
