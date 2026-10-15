import requests, os, json

PAT = os.getenv('GITHUB_TOKEN', '')
repo = 'you200109/quanttrading'
owner = 'you200109'
h = {'Authorization': f'token {PAT}', 'Accept': 'application/vnd.github.v3+json'}

# 1. 创建 GitHub Project (使用 REST API)
# Note: GitHub Projects v2 需要 GraphQL API
graphql_url = 'https://api.github.com/graphql'
graphql_h = {'Authorization': f'Bearer {PAT}'}

# 创建 Project V2
query = '''
mutation {
  createProjectV2(input: {ownerId: "MDQ6VXNlcjIwMDIwMDEwOQ==", title: "QuantTrading Roadmap", shortDescription: "Quantitative trading system development roadmap"}) {
    projectV2 {
      id
      url
    }
  }
}
'''
r = requests.post(graphql_url, headers=graphql_h, json={'query': query}, timeout=20)
print(f'Create Project: {r.status_code}')
if r.status_code == 200:
    data = r.json().get('data', {}).get('createProjectV2', {}).get('projectV2', {})
    print(f'  Project URL: {data.get("url", "")}')
else:
    print(f'  Response: {r.text[:200]}')

# 2. 创建 Good First Issues
issues = [
    {
        'title': '[Good First Issue] Add more unit tests for AGI modules',
        'body': '## Description\n\nWe need more unit tests for the AGI modules in `vigilant-couscous/agi/`. Currently coverage is at 24%, we want to reach 40%+.\n\n## Modules needing tests:\n- `agi/agi_brain.py`\n- `agi/continuous_learner.py`\n- `agi/eternal_evolver.py`\n- `agi/memory_system.py`\n\n## How to help\n\n1. Read the existing tests in `vigilant-couscous/tests/test_extended_modules.py`\n2. Follow the same pattern to create tests for AGI modules\n3. Run: `python -m pytest tests/ -v -o addopts=''`\n\n## Labels\n`good first issue`, `enhancement`, `python`, `vc`',
        'labels': ['good first issue', 'enhancement', 'python', 'vc']
    },
    {
        'title': '[Good First Issue] Improve frontend UI with dark/light theme toggle',
        'body': '## Description\n\nThe frontend currently only supports dark theme. We want to add a light theme toggle.\n\n## Tasks\n\n1. Add a theme toggle button in the header\n2. Create CSS variables for light theme colors\n3. Save preference in localStorage\n4. Test both themes\n\n## Files to modify\n- `frontend/index.html`\n\n## Labels\n`good first issue`, `enhancement`',
        'labels': ['good first issue', 'enhancement']
    },
    {
        'title': '[Good First Issue] Add WebSocket connection status indicator',
        'body': '## Description\n\nThe WebSocket connection status is shown as a small dot. Improve it with:\n\n1. Connection latency display\n2. Reconnect countdown timer\n3. Manual reconnect button\n4. Connection history log\n\n## Files to modify\n- `frontend/index.html`\n\n## Labels\n`good first issue`, `enhancement`',
        'labels': ['good first issue', 'enhancement']
    },
]

for issue in issues:
    r = requests.post(f'https://api.github.com/repos/{repo}/issues',
                     headers=h, json=issue, timeout=20)
    if r.status_code == 201:
        print(f'Created issue #{r.json()["number"]}: {issue["title"][:50]}')
    else:
        print(f'Failed to create issue: {r.status_code} {r.text[:100]}')

# 3. 启用私密漏洞报告
r = requests.put(f'https://api.github.com/repos/{repo}/code-scanning/default-setup',
                headers={**h, 'Accept': 'application/vnd.github.v3+json'},
                json={'state': 'configured', 'languages': ['python']}, timeout=20)
print(f'Code scanning default setup: {r.status_code}')

print('\n=== Project management setup complete ===')
