import requests, base64, os

PAT = os.getenv('GITHUB_TOKEN', '')
repo = 'you200109/quanttrading'
h = {'Authorization': f'token {PAT}', 'Accept': 'application/vnd.github.v3+json'}

files = [
    ('.github/CONTRIBUTING.md', 'docs: contributing guidelines'),
    ('.github/CODE_OF_CONDUCT.md', 'docs: code of conduct'),
    ('.github/SECURITY.md', 'docs: security policy'),
    ('.github/FUNDING.yml', 'feat: enable sponsor button'),
    ('.github/copilot-instructions.md', 'feat: copilot instructions'),
    ('.github/ISSUE_TEMPLATE/bug_report.yml', 'feat: bug report template'),
    ('.github/ISSUE_TEMPLATE/feature_request.yml', 'feat: feature request template'),
    ('.github/pull_request_template.md', 'feat: PR template'),
    ('.github/dependabot.yml', 'feat: dependabot config for pip + actions'),
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
