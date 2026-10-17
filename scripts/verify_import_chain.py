"""导入链验证：确认 FastAPI 服务（backend.main）可完整导入，
且其导入链满足以下不变量（P1 清障后的回归保护）：

1. backend.main 可导入（含全部路由注册）
2. 服务导入链不引入 vigilant-couscous.data.*（fetcher/cache_manager/
   portfolio_manager/live_trader 仅被 vc 内部使用；服务对 nexus 的
   访问走 vc_routes 的直接文件读写，已带三层路径防护）
3. 已删除的死代码模块（backend.core.vc_adapter、vigilant-couscous 的
   core/cli/web/trading 包）不出现在导入链中

用法：python scripts/verify_import_chain.py
退出码：0 = 全部不变量成立；1 = 有违反
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DELETED_MODULES = [
    'backend.core.vc_adapter',
    'core',                      # vigilant-couscous/core（已删整包）
    'core.error_handler',
    'cli',                       # vigilant-couscous/cli（已删整包）
    'web',                       # vigilant-couscous/web（已删整包）
    'trading',                   # vigilant-couscous/trading（已删整包）
    'auto_trade',
    'web_console',
]

VC_DATA_MODULES = [
    'data.fetcher',
    'data.cache_manager',
    'data.portfolio_manager',
    'data.live_trader',
]

failures = []

# 不变量 1：服务可导入
try:
    import backend.main  # noqa: F401
    print('[OK] backend.main imported successfully')
except Exception as e:
    failures.append(f'backend.main import failed: {type(e).__name__}: {e}')
    print(f'[FAIL] backend.main import failed: {type(e).__name__}: {e}')

# 不变量 2：导入链不触及 vc/data
for mod in VC_DATA_MODULES:
    if mod in sys.modules:
        failures.append(f'import chain reached {mod} (should not be reachable from service)')
        print(f'[FAIL] {mod} present in sys.modules')
    else:
        print(f'[OK] {mod} not in service import chain')

# 不变量 3：已删模块未复活
for mod in DELETED_MODULES:
    if mod in sys.modules:
        failures.append(f'deleted module {mod} was imported (resurrection!)')
        print(f'[FAIL] deleted module {mod} imported')
    else:
        print(f'[OK] deleted module {mod} absent')

# 附加信息：服务实际导入的 vc 模块（保持可见，便于回归比对）
vc_mods = sorted(m for m in sys.modules if m.startswith(('agi', 'agents', 'evolution', 'strategy', 'data', 'config')) and not m.startswith('backend'))
print(f'[INFO] vc modules in chain: {vc_mods if vc_mods else "(none)"}')

if failures:
    print(f'\n{len(failures)} invariant(s) violated')
    sys.exit(1)
print('\nAll import-chain invariants hold')
sys.exit(0)
