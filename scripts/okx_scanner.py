import requests
import json
import os
from datetime import datetime

token = os.getenv('GITHUB_TOKEN', '')
headers = {'Authorization': f'token {token}'} if token else {}

queries = [
    'okx trading bot python',
    'okx api python',
    'okx quantitative trading',
    'okx websocket python',
    'okx backtest'
]

results = []
for q in queries:
    url = f'https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=5'
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            for repo in r.json().get('items', []):
                results.append({
                    'query': q,
                    'full_name': repo['full_name'],
                    'stars': repo['stargazers_count'],
                    'description': (repo.get('description') or '')[:100],
                    'url': repo['html_url'],
                    'updated_at': repo['updated_at']
                })
        else:
            print(f'Query "{q}" returned {r.status_code}')
    except Exception as e:
        print(f'Query "{q}" failed: {e}')

output = {
    'timestamp': datetime.now().isoformat(),
    'total_found': len(results),
    'results': results
}

os.makedirs('reports', exist_ok=True)
with open('reports/okx_scan_results.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f'Found {len(results)} OKX-related projects')
for r in results[:10]:
    print(f'  {r["full_name"]} ({r["stars"]} stars)')
