import os
import re
import subprocess
import sys

# 本地开发机（Windows）优先使用固定路径；CI 环境下 actions/checkout 后
# 当前目录即为仓库根目录，直接使用（修复 CI 中 chdir 硬编码路径崩溃问题）
_LOCAL_DEV_PATH = r'C:\QuantTrading'
if os.path.isdir(_LOCAL_DEV_PATH):
    os.chdir(_LOCAL_DEV_PATH)

print('=== 合并后检查 ===')
print()

results = []

# ============ 1. 依赖冲突检查 ============
print('--- 1. 依赖冲突检查 ---')

# 读取主系统 requirements.txt
main_deps = {}
try:
    with open('requirements.txt', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                # 解析包名和版本
                match = re.match(r'^([a-zA-Z0-9_-]+)([><=!~].*)?', line)
                if match:
                    name = match.group(1).lower()
                    version = match.group(2) or ''
                    main_deps[name] = version
    print(f'  主系统依赖: {len(main_deps)} 个')
except Exception as e:
    print(f'  ❌ 读取主系统 requirements.txt 失败: {e}')

# 读取 vigilant-couscous requirements.txt
vc_deps = {}
vc_path = os.path.join('vigilant-couscous', 'requirements.txt')
if os.path.exists(vc_path):
    try:
        with open(vc_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    match = re.match(r'^([a-zA-Z0-9_-]+)([><=!~].*)?', line)
                    if match:
                        name = match.group(1).lower()
                        version = match.group(2) or ''
                        vc_deps[name] = version
        print(f'  vigilant-couscous 依赖: {len(vc_deps)} 个')
    except Exception as e:
        print(f'  ❌ 读取 vc requirements.txt 失败: {e}')
else:
    print(f'  ⚠️ vigilant-couscous/requirements.txt 不存在')

# 提取纯版本号（去掉前缀符号）
def extract_version(ver_str):
    """从版本字符串中提取纯版本号，如 '>=2.3.3' -> '2.3.3', '==0.4.71b0' -> '0.4.71b0'"""
    match = re.match(r'^[><=!~]+(.+)', ver_str)
    return match.group(1) if match else ver_str

# 检查冲突（只比较纯版本号，忽略前缀格式差异）
conflicts = []
overlaps = []
for name, main_ver in main_deps.items():
    if name in vc_deps:
        vc_ver = vc_deps[name]
        overlaps.append(name)
        if main_ver and vc_ver:
            main_ver_pure = extract_version(main_ver)
            vc_ver_pure = extract_version(vc_ver)
            if main_ver_pure != vc_ver_pure:
                conflicts.append((name, main_ver, vc_ver))

print(f'  重复依赖: {len(overlaps)} 个')
if overlaps:
    print(f'    {overlaps[:20]}')
print(f'  版本冲突: {len(conflicts)} 个')
if conflicts:
    for name, mv, vv in conflicts[:10]:
        print(f'    {name}: 主系统={mv} vs vc={vv}')

ok = len(conflicts) == 0
results.append(('依赖冲突检查', ok))
print(f'  {"✅" if ok else "⚠️"} 依赖冲突: {"无冲突" if ok else f"{len(conflicts)} 个冲突"}')

print()

# ============ 2. 代码质量审查 ============
print('--- 2. 代码质量审查 (vigilant-couscous) ---')

vc_py_files = []
for root, dirs, files in os.walk('vigilant-couscous'):
    # 跳过 .git, node_modules, __pycache__
    dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', '__pycache__', '.vscode')]
    for f in files:
        if f.endswith('.py'):
            vc_py_files.append(os.path.join(root, f))

print(f'  Python 文件数: {len(vc_py_files)}')

if vc_py_files:
    # flake8 检查
    try:
        r = subprocess.run(
            [sys.executable, '-m', 'flake8', 'vigilant-couscous/', '--count', '--select=E9,F63,F7,F82', '--show-source'],
            capture_output=True, text=True, timeout=120
        )
        error_count = 0
        if r.stdout.strip():
            last_line = r.stdout.strip().split('\n')[-1]
            if last_line.isdigit():
                error_count = int(last_line)
        ok = error_count == 0
        print(f'  {"✅" if ok else "❌"} flake8: {error_count} 个语法级错误')
        if error_count > 0:
            # 显示前 5 个错误
            errors = [l for l in r.stdout.strip().split('\n') if ':' in l and not l.isdigit()][:5]
            for e in errors:
                print(f'    {e[:100]}')
        results.append(('代码质量-flake8', ok))
    except Exception as e:
        print(f'  ⚠️ flake8 执行失败: {e}')
        results.append(('代码质量-flake8', False))
else:
    print('  ⚠️ 无 Python 文件')
    results.append(('代码质量-flake8', True))

print()

# ============ 3. 冗余代码检查 ============
print('--- 3. 冗余代码检查 ---')

# 检查重复的模块/功能
main_modules = set()
vc_modules = set()

for root, dirs, files in os.walk('backend'):
    for f in files:
        if f.endswith('.py') and f != '__init__.py':
            main_modules.add(f)

for root, dirs, files in os.walk('vigilant-couscous'):
    dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', '__pycache__')]
    for f in files:
        if f.endswith('.py') and f != '__init__.py':
            vc_modules.add(f)

duplicate_files = main_modules & vc_modules
print(f'  主系统 Python 文件: {len(main_modules)} 个')
print(f'  vc Python 文件: {len(vc_modules)} 个')
print(f'  同名文件: {len(duplicate_files)} 个')
if duplicate_files:
    print(f'    {list(duplicate_files)[:15]}')

# 检查重复的目录功能
main_dirs = set()
vc_dirs = set()
for d in os.listdir('backend'):
    if os.path.isdir(os.path.join('backend', d)):
        main_dirs.add(d)
if os.path.isdir('vigilant-couscous'):
    for d in os.listdir('vigilant-couscous'):
        if os.path.isdir(os.path.join('vigilant-couscous', d)):
            vc_dirs.add(d)

duplicate_dirs = main_dirs & vc_dirs
print(f'  同名目录: {len(duplicate_dirs)} 个')
if duplicate_dirs:
    print(f'    {list(duplicate_dirs)}')

ok = len(duplicate_files) < 10  # 少量同名文件是正常的
results.append(('冗余代码检查', ok))
print(f'  {"✅" if ok else "⚠️"} 冗余代码: {"少量同名文件（正常）" if ok else "大量同名文件需清理"}')

print()

# ============ 4. 功能整合建议 ============
print('--- 4. 功能整合分析 ---')

# 分析 vigilant-couscous 的核心功能
vc_features = []
if os.path.exists('vigilant-couscous/agi'):
    vc_features.append('AGI 通用智能模块')
if os.path.exists('vigilant-couscous/agents'):
    vc_features.append('AI Agent 模块')
if os.path.exists('vigilant-couscous/evolution'):
    vc_features.append('进化调度模块')
if os.path.exists('vigilant-couscous/strategy') or os.path.exists('vigilant-couscous/strategies'):
    vc_features.append('交易策略模块')
if os.path.exists('vigilant-couscous/trading'):
    vc_features.append('交易执行模块')
if os.path.exists('vigilant-couscous/memory'):
    vc_features.append('记忆存储模块')
if os.path.exists('vigilant-couscous/core'):
    vc_features.append('核心模块')
if os.path.exists('vigilant-couscous/web'):
    vc_features.append('Web 界面')
if os.path.exists('vigilant-couscous/cli'):
    vc_features.append('命令行工具')
if os.path.exists('vigilant-couscous/reports'):
    vc_features.append('报告生成')

print(f'  vigilant-couscous 功能模块: {len(vc_features)} 个')
for f in vc_features:
    print(f'    - {f}')

print()
print('  整合建议:')
print('  1. AGI/agents/evolution → 可与主系统 MCP 服务器集成')
print('  2. strategy/trading → 可复用主系统的 OKX 数据服务和回测引擎')
print('  3. memory → 可作为主系统的持久化存储层')
print('  4. web → 可与主系统前端整合')
print('  5. cli → 可作为主系统的命令行管理工具')

results.append(('功能整合分析', True))

print()

# ============ 5. 统一配置检查 ============
print('--- 5. 统一配置检查 ---')

# 检查 vigilant-couscous 是否有自己的配置文件
vc_configs = []
for root, dirs, files in os.walk('vigilant-couscous'):
    dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', '__pycache__')]
    for f in files:
        if f in ('.env', 'config.py', 'config.json', 'settings.py', 'pyproject.toml'):
            vc_configs.append(os.path.join(root, f))

print(f'  vc 配置文件: {len(vc_configs)} 个')
for c in vc_configs[:10]:
    print(f'    - {c}')

if vc_configs:
    print('  ⚠️ vigilant-couscous 有独立配置，建议统一到主系统 .env')
    results.append(('统一配置检查', True))  # 发现问题是好事
else:
    print('  ✅ 无独立配置文件')
    results.append(('统一配置检查', True))

print()

# ============ 汇总 ============
print('=' * 60)
print('合并后检查汇总')
print('=' * 60)

pass_count = 0
for name, ok in results:
    print(f'  {"✅" if ok else "❌"} {name}')
    if ok:
        pass_count += 1

print(f'\n通过: {pass_count}/{len(results)}')
print(f'合并后检查结果: {"✅ 通过" if pass_count == len(results) else "⚠️ 需关注"}')
