"""路径遍历攻击测试：复刻 get_nexus_file 两层校验逻辑"""
import os

VC_ROOT = os.path.abspath('C:/Users/Administrator/WorkBuddy/ww/quanttrading/vigilant-couscous')
nexus_dir = os.path.abspath(os.path.join(VC_ROOT, 'memory', 'nexus'))


def validate(filename):
    """与 backend/api/vc_routes.py get_nexus_file 相同的校验逻辑"""
    if (filename != os.path.basename(filename)
            or '/' in filename or '\\' in filename
            or filename in ('.', '..') or filename.startswith('.')):
        return False
    filepath = os.path.abspath(os.path.join(nexus_dir, filename))
    try:
        escaped = os.path.commonpath([nexus_dir, filepath]) != nexus_dir
    except ValueError:
        escaped = True
    return not escaped


cases = [
    ('state.json', True),
    ('data.json', True),
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
    ('normal_file-123.json', True),
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
