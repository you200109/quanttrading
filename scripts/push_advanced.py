import requests, base64, os

PAT = os.getenv('GITHUB_TOKEN', '')
repo = 'you200109/quanttrading'
h = {'Authorization': f'token {PAT}', 'Accept': 'application/vnd.github.v3+json'}

files = [
    ('.github/workflows/ci.yml', 'feat: matrix build + pip cache + security scan'),
    ('.github/workflows/publish.yml', 'feat: GitHub Packages publish workflow'),
    ('.github/workflows/docker.yml', 'feat: Docker build and push to GHCR'),
    ('.github/CODEOWNERS', 'feat: code owners configuration'),
    ('.github/profile/README.md', 'feat: GitHub profile README'),
    ('Dockerfile', 'feat: Dockerfile for containerized deployment'),
    ('scripts/enable_security.py', 'feat: security enablement script'),
    ('scripts/push_community.py', 'feat: community files push script'),
    ('scripts/push_advanced.py', 'feat: advanced config push script'),
    ('scripts/push_codespaces.py', 'feat: codespaces push script'),
    ('scripts/push_phase2.py', 'feat: phase2 push script'),
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
