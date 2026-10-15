"""路径遍历攻击测试：复刻 get_nexus_file 两层校验逻辑（realpath + commonpath 版）"""
import os
import re

VC_ROOT = os.path.abspath('C:/Users/Administrator/WorkBuddy/ww/quanttrading/vigilant-couscous')
nexus_dir = os.path.realpath(os.path.join(VC_ROOT, 'memory', 'nexus'))


def validate(filename):
    """与 backend/api/vc_routes.py get_nexus_file 相同的校验逻辑"""
    # 安全校验 1：白名单字符集
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9._-]*', filename):
        return False
    # 安全校验 2：realpath 归一化 + commonpath 包含检查
    filepath = os.path.realpath(os.path.join(nexus_dir, filename))
    if os.path.commonpath([nexus_dir, filepath]) != nexus_dir:
        return False
    if not os.path.isfile(filepath):
        return False
    return True


cases = [
    ('evolution_state.json', True),
    ('version.json', True),
    ('gh_strategy_library.json', True),
    ('normal_file-123.json', False),  # 字符合法但文件不存在 -> File not found
    ('../.env', False),
    ('../../backend/.env', False),
    ('..%2f.env', False),
    ('/etc/passwd', False),
    ('C:\\Windows\\win.ini', False),
    ('\\\\server\\share\\x', False),
    ('.', False),
    ('..', False),
    ('.hidden', False),
    ('a/b.json', False),
    ('a\\b.json', False),
    ('....//x', False),
    ('sub/../../../etc/passwd', False),
    ('', False),
    ('空格 文件.json', False),
    ('中文.json', False),
    ('file\x00.json', False),
]

fails = 0
for name, expect_ok in cases:
    ok = validate(name)
    good = ok == expect_ok
    if not good:
        fails += 1
    print(f"{'PASS' if good else 'FAIL'}  {name!r:35s} -> {'ALLOW' if ok else 'DENY '} (expect {'ALLOW' if expect_ok else 'DENY '})")
print(f"\n{len(cases) - fails}/{len(cases)} passed")
raise SystemExit(1 if fails else 0)
