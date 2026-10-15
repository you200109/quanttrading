import requests, os

PAT = os.getenv('GITHUB_TOKEN', '')
repo = 'you200109/quanttrading'
h = {'Authorization': f'token {PAT}', 'Accept': 'application/vnd.github.v3+json'}

r = requests.get(f'https://api.github.com/repos/{repo}/actions/runs?per_page=5', headers=h, timeout=20)
runs = r.json().get('workflow_runs', [])
print(f'Recent runs: {len(runs)}')
for x in runs:
    name = x.get('name', '')
    status = x.get('status', '')
    conclusion = x.get('conclusion', '')
    url = x.get('html_url', '')[:80]
    print(f'  {name} | {status} | {conclusion} | {url}')
