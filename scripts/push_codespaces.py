import requests, base64, os

PAT = os.getenv('GITHUB_TOKEN', '')
repo = 'you200109/quanttrading'
h = {'Authorization': f'token {PAT}', 'Accept': 'application/vnd.github.v3+json'}

files = [
    ('.devcontainer/devcontainer.json', 'feat: GitHub Codespaces configuration'),
    ('docs/codespaces-guide.md', 'docs: GitHub Codespaces usage guide'),
    ('scripts/okx_scanner.py', 'feat: standalone OKX scanner script (already pushed, verify)'),
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
