"""①发现 scripts/gov/discover.py 单元测试

离线：把 github_api.request 换成按 query 返回伪造数据的函数。
重点验证四件事：配额预算会被执行、增量去重真的去重、单查询报错被隔离、
产物符合 candidate 契约且真的落盘。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.gov import config as gconfig  # noqa: E402
from scripts.gov import discover  # noqa: E402
from scripts.gov import github_api as gh  # noqa: E402
from scripts.gov import schemas  # noqa: E402
from scripts.gov import store  # noqa: E402

GOV_CONFIG = REPO_ROOT / "scripts" / "gov" / "config.yml"
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)


def _repo(name, stars=100, *, fork=False, archived=False, pushed="2026-10-01T00:00:00Z",
          language="Python", topics=None, license_id="MIT"):
    owner, repo = name.split("/")
    return {
        "full_name": name,
        "html_url": f"https://github.com/{name}",
        "stargazers_count": stars,
        "forks_count": 1,
        "open_issues_count": 2,
        "language": language,
        "license": {"spdx_id": license_id, "key": (license_id or "").lower()},
        "topics": topics or [],
        "pushed_at": pushed,
        "description": f"desc of {repo}",
        "archived": archived,
        "fork": fork,
    }


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    base = gconfig.load_config(GOV_CONFIG)
    base["knowledge"]["root"] = "kb"
    monkeypatch.setattr(store, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(store, "REPORTS_DIR", tmp_path / "reports")
    return base


def _install_fake_search(monkeypatch, handler):
    calls = []

    def fake(path, params=None, *, token=None, **kwargs):
        calls.append((path, params or {}))
        # github_api.request 的契约是返回 (payload, meta)
        return handler(params or {}), {"status": 200, "rate_remaining": 29}

    monkeypatch.setattr(gh, "request", fake)
    return calls


# ---------------- 查询计划 ----------------
def test_build_queries_expands_domains_and_filters(cfg):
    plan = discover.build_queries(cfg, now=NOW)
    domains = {p["domain"] for p in plan}
    assert domains == {"quant", "ai_agent", "eng_infra"}
    assert all("stars:>200" in p["query"] for p in plan)
    assert all("pushed:>2025-10-16" in p["query"] for p in plan)  # 今天往前 365 天


def test_disabled_domain_is_not_planned(cfg):
    cfg["discovery"]["domains"]["eng_infra"]["enabled"] = False
    plan = discover.build_queries(cfg, now=NOW)
    assert {p["domain"] for p in plan} == {"quant", "ai_agent"}


def test_plan_size_equals_keywords_plus_topics(cfg):
    dom = cfg["discovery"]["domains"]
    expected = sum(len(d["keywords"]) + len(d["topics"]) for d in dom.values())
    assert len(discover.build_queries(cfg, now=NOW)) == expected


# ---------------- 发现主流程 ----------------
def test_filters_drop_forks_and_archived_and_low_stars(cfg, monkeypatch):
    _install_fake_search(monkeypatch, lambda p: {"items": [
        _repo("a/forked", 500, fork=True),
        _repo("a/old", 500, archived=True),
        _repo("a/low", 5),
        _repo("a/keep", 900),
    ]})
    report = discover.run(cfg, now=NOW, write=False)
    assert [c["full_name"] for c in report["candidates"]] == ["a/keep"]


def test_dedup_keeps_highest_stars_and_counts_merges(cfg, monkeypatch):
    seen = {"n": 0}

    def handler(p):
        seen["n"] += 1
        stars = 250 if seen["n"] == 1 else 400
        return {"items": [_repo("dup/tool", stars)]}

    _install_fake_search(monkeypatch, handler)
    # 限两次查询：每次都命中同一个仓库，才能精确断言去重/跳过的次数
    report = discover.run(cfg, now=NOW, write=False, max_requests=2)
    assert len(report["candidates"]) == 1
    assert report["candidates"][0]["stars"] == 400
    assert report["duplicate_merged"] == 1


def test_known_cards_are_skipped_once(cfg, monkeypatch, tmp_path):
    store.save_project_card(schemas.new_record(
        "project_card", name="known/tool", url="u", domain="quant",
        status="discovered"), cfg)
    _install_fake_search(monkeypatch, lambda p: {"items": [_repo("known/tool", 999),
                                                           _repo("new/tool", 300)]})
    # 两次查询都会把 known/tool 捞回来：应各计一次 skipped，但不重复进候选表
    report = discover.run(cfg, now=NOW, write=False, max_requests=2)
    assert [c["full_name"] for c in report["candidates"]] == ["new/tool"]
    assert report["skipped_known"] == 2
    assert report["duplicate_merged"] == 1


def test_blacklist_is_excluded(cfg, monkeypatch):
    cfg["scoring"]["blacklist"] = ["nope/spam"]
    _install_fake_search(monkeypatch, lambda p: {"items": [_repo("nope/spam", 9999)]})
    report = discover.run(cfg, now=NOW, write=False)
    assert report["count"] == 0


def test_request_budget_is_enforced_and_marked_truncated(cfg, monkeypatch):
    calls = _install_fake_search(monkeypatch, lambda p: {"items": [_repo("o/r", 10)]})
    report = discover.run(cfg, max_requests=2, now=NOW, write=False)
    assert report["requests_used"] == 2 and len(calls) == 2
    assert report["truncated"] is True
    assert report["plan_total"] > 2


def test_single_query_error_is_isolated(cfg, monkeypatch):
    state = {"n": 0}

    def handler(p):
        state["n"] += 1
        if state["n"] == 1:
            raise gh.GitHubError(503, "temporarily unavailable")
        return {"items": [_repo("o/after-error", 300)]}

    _install_fake_search(monkeypatch, handler)
    report = discover.run(cfg, now=NOW, write=False)
    assert report["status"] == "partial"
    assert report["count"] == 1
    assert any("o/after-error" in c["full_name"] for c in report["candidates"])
    assert any("503" in e for e in report["errors"])


def test_missing_credentials_is_failure_not_silence(cfg, monkeypatch):
    def fake(path, params=None, *, token=None, **kw):
        raise gh.NoCredentials("缺少 GITHUB_TOKEN / GH_TOKEN")

    monkeypatch.setattr(gh, "request", fake)
    report = discover.run(cfg, now=NOW, write=False)
    assert report["status"] == "failed"
    assert report["requests_used"] == 1        # 第一条就发现没凭据，不再浪费配额
    assert any("credentials" in e for e in report["errors"])


def test_candidates_satisfy_schema(cfg, monkeypatch):
    _install_fake_search(monkeypatch, lambda p: {"items": [
        _repo("o/one", 300, topics=["quant"], language="Python")]})
    report = discover.run(cfg, now=NOW, write=False)
    for cand in report["candidates"]:
        assert schemas.problems("candidate", cand) == []
    cand = report["candidates"][0]
    assert cand["license"] == "MIT" and cand["topics"] == ["quant"]
    assert cand["discovered_at"] == NOW.isoformat()


def test_report_is_persisted(cfg, monkeypatch, tmp_path):
    _install_fake_search(monkeypatch, lambda p: {"items": [_repo("o/saved", 420)]})
    discover.run(cfg, now=NOW)
    path = tmp_path / "reports" / "2026-10-16" / "discovery.json"
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["count"] == 1 and saved["candidates"][0]["full_name"] == "o/saved"


# ---------------- CLI ----------------
def test_cli_dry_run_prints_and_no_file(cfg, monkeypatch, capsys, tmp_path):
    _install_fake_search(monkeypatch, lambda p: {"items": [_repo("o/cli", 700)]})
    rc = discover.main(["--config", str(GOV_CONFIG), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "o/cli" in out
    assert not (tmp_path / "reports" / "2026-10-16" / "discovery.json").exists()


def test_cli_bad_config_exits_two(monkeypatch):
    monkeypatch.setattr(discover, "run", lambda *a, **k: pytest.fail("不应在配置错误时执行发现"))
    assert discover.main(["--config", "nope.yml"]) == 2


def test_cli_all_failed_exits_one(cfg, monkeypatch):
    monkeypatch.setattr(gh, "request",
                        lambda path, params=None, **kw: (_ for _ in ()).throw(
                            gh.NoCredentials("缺少 GITHUB_TOKEN / GH_TOKEN")))
    assert discover.main(["--config", str(GOV_CONFIG), "--dry-run"]) == 1
