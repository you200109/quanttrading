import requests, base64, os

PAT = os.getenv('GITHUB_TOKEN', '')
repo = 'you200109/quanttrading'
h = {'Authorization': f'token {PAT}', 'Accept': 'application/vnd.github.v3+json'}

files = [
    ('.github/workflows/okx-scanner.yml', 'fix: use standalone script instead of inline python'),
    ('scripts/okx_scanner.py', 'feat: standalone OKX scanner script'),
    ('scripts/setup_repo.py', 'feat: repo setup optimization script'),
    ('scripts/close_issues.py', 'feat: batch close issues script'),
    ('scripts/check_ci.py', 'feat: CI status check script'),
    ('scripts/push_remaining.py', 'feat: batch push remaining files script'),
    ('vigilant-couscous/agents/researcher.py', 'vc: researcher agent module'),
    ('vigilant-couscous/evolution/backtest_validator.py', 'vc: backtest validator module'),
    ('vigilant-couscous/evolution/learning_loop.py', 'vc: learning loop module'),
    ('vigilant-couscous/evolution/rl_environment.py', 'vc: RL environment module'),
    ('vigilant-couscous/evolution/rl_trainer.py', 'vc: RL trainer module'),
    ('vigilant-couscous/agents/multi_timeframe.py', 'vc: multi timeframe analyzer'),
    ('vigilant-couscous/agents/alert_manager.py', 'vc: alert manager module'),
    ('vigilant-couscous/agents/parallel_scheduler.py', 'vc: parallel scheduler module'),
    ('vigilant-couscous/data/portfolio_manager.py', 'vc: portfolio manager (already pushed, skip if duplicate)'),
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
