import requests, base64, os

PAT = os.getenv('GITHUB_TOKEN', '')
repo = 'you200109/quanttrading'
h = {'Authorization': f'token {PAT}', 'Accept': 'application/vnd.github.v3+json'}

files = [
    ('vigilant-couscous/cli/run_all.py', 'fix: E999 unterminated f-string'),
    ('vigilant-couscous/data/live_trader.py', 'fix: E999 unterminated string'),
    ('vigilant-couscous/strategy/backtest_gh_strategies.py', 'fix: E999 unterminated f-string'),
    ('vigilant-couscous/trading/auto_trade.py', 'fix: E999 invalid char U+0089'),
    ('vigilant-couscous/web/visualize.py', 'fix: E999 unterminated string'),
    ('vigilant-couscous/data/cache_manager.py', 'fix: remove unused timedelta import'),
    ('vigilant-couscous/data/fetcher.py', 'fix: remove unused typing imports'),
    ('vigilant-couscous/data/portfolio_manager.py', 'fix: remove unused Tuple import'),
    ('vigilant-couscous/strategies/base_strategy.py', 'fix: remove unused Optional import'),
    ('vigilant-couscous/tests/test_core_modules.py', 'fix: remove unused imports + adjust tests'),
    ('scripts/post_merge_check.py', 'fix: dependency conflict detection logic'),
    ('backend/core/vc_adapter.py', 'feat: vc deep integration adapter'),
]

for path, desc in files:
    try:
        if not os.path.exists(path):
            print(f'SKIP {path}')
            continue
        c = base64.b64encode(open(path, 'rb').read()).decode()
        r = requests.get(f'https://api.github.com/repos/{repo}/contents/{path}', headers=h, timeout=20)
        sha = r.json().get('sha') if r.status_code == 200 else None
        pl = {'message': desc, 'content': c}
        if sha:
            pl['sha'] = sha
        r = requests.put(f'https://api.github.com/repos/{repo}/contents/{path}', headers=h, json=pl, timeout=20)
        print(f'{r.status_code} {path}')
    except Exception as e:
        print(f'ERR {path}: {e}')
