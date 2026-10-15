import requests, os, json

PAT = os.getenv('GITHUB_TOKEN', '')
repo = 'you200109/quanttrading'
h = {'Authorization': f'token {PAT}', 'Accept': 'application/vnd.github.v3+json'}

# 1. 检查当前仓库设置
r = requests.get(f'https://api.github.com/repos/{repo}', headers=h, timeout=20)
repo_data = r.json()
print('=== Current Repo Settings ===')
print(f'  has_issues: {repo_data.get("has_issues")}')
print(f'  has_projects: {repo_data.get("has_projects")}')
print(f'  has_wiki: {repo_data.get("has_wiki")}')
print(f'  has_pages: {repo_data.get("has_pages")}')
print(f'  has_discussions: {repo_data.get("has_discussions")}')
print(f'  has_downloads: {repo_data.get("has_downloads")}')
print(f'  allow_squash_merge: {repo_data.get("allow_squash_merge")}')
print(f'  allow_merge_commit: {repo_data.get("allow_merge_commit")}')
print(f'  allow_rebase_merge: {repo_data.get("allow_rebase_merge")}')
print(f'  delete_branch_on_merge: {repo_data.get("delete_branch_on_merge")}')
print(f'  vulnerability_alerts: {repo_data.get("vulnerability_alerts")}')

# 2. 启用所有功能
updates = {
    'has_issues': True,
    'has_projects': True,
    'has_wiki': True,
    'has_discussions': True,
    'has_downloads': True,
    'allow_squash_merge': True,
    'allow_merge_commit': True,
    'allow_rebase_merge': True,
    'delete_branch_on_merge': True,
    'allow_auto_merge': True,
    'use_squash_pr_title_as_default': True,
    'squash_merge_commit_title': 'PR_TITLE_AND_COMMIT',
    'squash_merge_commit_message': 'PR_BODY',
}
r = requests.patch(f'https://api.github.com/repos/{repo}', headers=h, json=updates, timeout=20)
print(f'\nEnable features: {r.status_code}')

# 3. 启用 vulnerability alerts
r = requests.put(f'https://api.github.com/repos/{repo}/vulnerability-alerts', headers=h, timeout=20)
print(f'Enable vulnerability alerts: {r.status_code}')

# 4. 启用 automated security fixes
r = requests.put(f'https://api.github.com/repos/{repo}/automated-security-fixes', headers=h, timeout=20)
print(f'Enable automated security fixes: {r.status_code}')

# 5. 检查分支保护
r = requests.get(f'https://api.github.com/repos/{repo}/branches/main/protection', headers=h, timeout=20)
print(f'\nBranch protection (main): {r.status_code}')
if r.status_code == 200:
    bp = r.json()
    print(f'  required_pull_request_reviews: {"required_pull_request_reviews" in bp}')
    print(f'  required_status_checks: {"required_status_checks" in bp}')
    print(f'  enforce_admins: {bp.get("enforce_admins", {}).get("enabled", False)}')
else:
    print(f'  Response: {r.text[:100]}')

# 6. 配置分支保护规则
protection = {
    'required_status_checks': {
        'strict': True,
        'contexts': ['continuous-integration']
    },
    'enforce_admins': False,
    'required_pull_request_reviews': {
        'dismiss_stale_reviews': True,
        'require_code_owner_reviews': False,
        'required_approving_review_count': 0
    },
    'restrictions': None,
    'required_linear_history': False,
    'allow_force_pushes': False,
    'allow_deletions': False,
    'block_creations': False,
    'required_conversation_resolution': False
}
r = requests.put(f'https://api.github.com/repos/{repo}/branches/main/protection',
                headers={**h, 'Accept': 'application/vnd.github.luke-cage-preview+json'},
                json=protection, timeout=20)
print(f'Set branch protection: {r.status_code}')

# 7. 启用 GitHub Pages
r = requests.post(f'https://api.github.com/repos/{repo}/pages',
                 headers=h, json={'source': {'branch': 'main', 'path': '/frontend'}}, timeout=20)
print(f'\nEnable GitHub Pages: {r.status_code}')
if r.status_code == 422:
    # Pages already enabled, get current config
    r = requests.get(f'https://api.github.com/repos/{repo}/pages', headers=h, timeout=20)
    if r.status_code == 200:
        pages = r.json()
        print(f'  Pages already enabled: {pages.get("html_url", "")}')
        # Update to serve from frontend directory
        r = requests.put(f'https://api.github.com/repos/{repo}/pages',
                        headers=h, json={'source': {'branch': 'main', 'path': '/frontend'}}, timeout=20)
        print(f'  Update Pages source: {r.status_code}')

# 8. 列出 Actions 权限设置
r = requests.get(f'https://api.github.com/repos/{repo}/actions/permissions', headers=h, timeout=20)
print(f'\nActions permissions: {r.status_code}')
if r.status_code == 200:
    perms = r.json()
    print(f'  enabled: {perms.get("enabled")}')
    print(f'  allowed_actions: {perms.get("allowed_actions")}')

print('\n=== Repository setup complete ===')
