import requests, os, json

PAT = os.getenv('GITHUB_TOKEN', '')
repo = 'you200109/quanttrading'
h = {'Authorization': f'token {PAT}', 'Accept': 'application/vnd.github.v3+json'}

# 1. 启用 Vulnerability Alerts
r = requests.put(f'https://api.github.com/repos/{repo}/vulnerability-alerts', headers=h, timeout=20)
print(f'Vulnerability alerts: {r.status_code}')

# 2. 启用 Automated Security Fixes
r = requests.put(f'https://api.github.com/repos/{repo}/automated-security-fixes', headers=h, timeout=20)
print(f'Automated security fixes: {r.status_code}')

# 3. 启用 Secret Scanning (需要通过仓库设置 API)
# 检查当前 secret scanning 状态
r = requests.get(f'https://api.github.com/repos/{repo}/secret-scanning-alerts', headers=h, timeout=20)
print(f'Secret scanning alerts query: {r.status_code}')

# 4. 启用 Push Protection (通过 secret scanning settings)
# 使用 repos API 更新安全相关设置
security_updates = {
    'security_and_analysis': {
        'secret_scanning': {'status': 'enabled'},
        'secret_scanning_push_protection': {'status': 'enabled'},
    }
}
r = requests.patch(f'https://api.github.com/repos/{repo}',
                    headers={**h, 'Accept': 'application/vnd.github.v3+json'},
                    json=security_updates, timeout=20)
print(f'Enable secret scanning + push protection: {r.status_code}')
if r.status_code != 200:
    print(f'  Response: {r.text[:200]}')

# 5. 创建 CodeQL 工作流
codeql_workflow = '''name: CodeQL Analysis

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 0 * * 0'
  workflow_dispatch:

jobs:
  analyze:
    name: Analyze
    runs-on: ubuntu-latest
    permissions:
      actions: read
      contents: read
      security-events: write

    strategy:
      matrix:
        language: ['python']

    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: ${{ matrix.language }}
      - uses: github/codeql-action/analyze@v3
'''

# 推送 CodeQL 工作流
import base64
c = base64.b64encode(codeql_workflow.encode()).decode()
p = '.github/workflows/codeql.yml'
r = requests.get(f'https://api.github.com/repos/{repo}/contents/{p}', headers=h, timeout=20)
sha = r.json().get('sha') if r.status_code == 200 else None
pl = {'message': 'feat: CodeQL code scanning workflow', 'content': c}
if sha:
    pl['sha'] = sha
r = requests.put(f'https://api.github.com/repos/{repo}/contents/{p}', headers=h, json=pl, timeout=20)
print(f'CodeQL workflow: {r.status_code}')

# 6. 创建标签体系
labels = [
    ('bug', 'd73a4a', 'Something is not working'),
    ('enhancement', 'a2eeef', 'New feature or request'),
    ('dependencies', '0366d6', 'Pull requests that update a dependency file'),
    ('python', '3572A5', 'Python related'),
    ('vc', '5319e7', 'vigilant-couscous related'),
    ('github-actions', '2188ff', 'GitHub Actions related'),
    ('security', 'd1242f', 'Security related'),
    ('documentation', '0075ca', 'Documentation improvements'),
    ('good first issue', '7057ff', 'Good for newcomers'),
    ('help wanted', '008672', 'Extra attention is needed'),
    ('needs-triage', 'fbca04', 'Needs initial assessment'),
    ('ci', 'e99695', 'CI/CD related'),
]

for name, color, desc in labels:
    r = requests.post(f'https://api.github.com/repos/{repo}/labels',
                     headers=h, json={'name': name, 'color': color, 'description': desc}, timeout=20)
    if r.status_code == 201:
        print(f'Created label: {name}')
    elif r.status_code == 422:
        # Label already exists, update it
        r = requests.patch(f'https://api.github.com/repos/{repo}/labels/{name}',
                         headers=h, json={'color': color, 'description': desc}, timeout=20)
        print(f'Updated label: {name} ({r.status_code})')
    else:
        print(f'Label {name}: {r.status_code}')

# 7. 创建里程碑
r = requests.post(f'https://api.github.com/repos/{repo}/milestones',
                 headers=h, json={'title': 'v2.0', 'description': 'Next major release with full AI integration', 'state': 'open'}, timeout=20)
print(f'Milestone v2.0: {r.status_code}')

print('\n=== Security and community setup complete ===')
