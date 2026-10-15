import requests, os

PAT = os.getenv('GITHUB_TOKEN', '')
repo = 'you200109/quanttrading'
h = {'Authorization': f'token {PAT}', 'Accept': 'application/vnd.github.v3+json'}

r = requests.get(f'https://api.github.com/repos/{repo}/issues?state=open&per_page=30', headers=h, timeout=20)
issues = r.json()
print(f'Open issues: {len(issues)}')

closed = 0
for i in issues:
    num = i.get('number')
    r2 = requests.patch(f'https://api.github.com/repos/{repo}/issues/{num}', headers=h, json={'state': 'closed'}, timeout=20)
    if r2.status_code == 200:
        closed += 1
        print(f'Closed #{num}')
    else:
        print(f'Failed #{num}: {r2.status_code}')

print(f'Total closed: {closed}/{len(issues)}')
