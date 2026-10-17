"""Helpers for the weekly agents: GitHub Issues, optional LLM, pure functions."""
import json
import os
import urllib.request
from collections import Counter

API = "https://api.github.com"
REPO = os.getenv("GITHUB_REPOSITORY", "you200109/quanttrading")
PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}


def gh(path, method="GET", data=None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(data).encode() if data else None,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def issue_titles():
    out = []
    for page in (1, 2, 3):
        items = gh(f"/repos/{REPO}/issues?state=all&per_page=100&page={page}")
        out += [i["title"] for i in items if "pull_request" not in i]
        if len(items) < 100:
            break
    return set(out)


def create_issue(title, body, labels):
    return gh(f"/repos/{REPO}/issues", "POST",
              {"title": title, "body": body, "labels": labels})


def llm(prompt, max_tokens=900):
    """Return model text, or None when no API key is configured."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic
    msg = anthropic.Anthropic(api_key=key).messages.create(
        model=os.getenv("MODEL", "claude-sonnet-5-5"), max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if b.type == "text")


def permissive(repo):
    lic = (repo.get("license") or {}).get("spdx_id")
    return lic in PERMISSIVE and not repo.get("archived") and not repo.get("fork")


def weekly_stats(history, days=7):
    rows = history[-days:]
    if not rows:
        return {}

    def avg(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    params = Counter(f'{r["fast"]}/{r["slow"]}' for r in rows)
    return {"days": len(rows),
            "pass_rate": round(sum(bool(r.get("passed")) for r in rows) / len(rows), 2),
            "avg_test_sharpe": avg("test_sharpe"),
            "avg_test_return_pct": avg("test_return_pct"),
            "avg_buy_hold_pct": avg("buy_hold_return_pct"),
            "distinct_params": len(params),
            "most_common_params": params.most_common(1)[0][0]}
