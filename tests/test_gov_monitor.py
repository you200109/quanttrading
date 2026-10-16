"""③监控 scripts/gov/monitor.py 单元测试

全部离线：github_api.request / PyPI _pypi_latest 都被替换。
重点验证：告警记忆（alerted_tag 只在告警送达后前进）、去重与防洪、
依赖分类（outdated/held/unpinned/unknown）、预算截断、状态损坏恢复、
报告与度量快照落盘、CLI 退出码。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.gov import config as gconfig  # noqa: E402
from scripts.gov import github_api as gh  # noqa: E402
from scripts.gov import monitor  # noqa: E402
from scripts.gov import schemas  # noqa: E402
from scripts.gov import store  # noqa: E402

GOV_CONFIG = REPO_ROOT / "scripts" / "gov" / "config.yml"
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)

REQ_TEXT = """\
# 注释行
alpha==0.9.0
beta>=2.0,<3.0
gamma==5.0.0
weird
extra[dev]==1.0.0 ; python_version >= "3.8"
-r other.txt
"""

LATEST = {"alpha": "1.0.0", "beta": "2.5.0", "gamma": "5.0.3",
          "weird": "3.0.0", "extra": "1.0.0"}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    base = gconfig.load_config(GOV_CONFIG)
    base["knowledge"]["root"] = "kb"
    base["monitoring"] = {
        "self_repo": "me/self",
        "max_requests_per_run": 20,
        "watched": [{"repo": "acme/tool", "kind": "release"}],
        "self_requirements": ["requirements.txt"],
        "alerts": {"max_open_alerts": 5, "ci_success_floor": 0.9, "coverage_floor": 40},
    }
    (tmp_path / "requirements.txt").write_text(REQ_TEXT, encoding="utf-8")
    monkeypatch.setattr(store, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(store, "REPORTS_DIR", tmp_path / "reports")
    return base


def _fake_fetch(latest=None):
    table = dict(LATEST if latest is None else latest)

    def fetch(name):
        return table.get(name, "9.9.9")

    return fetch


def _release(tag, *, published="2026-10-15T00:00:00Z", url="https://example/rel"):
    return {"tag_name": tag, "published_at": published, "html_url": url}


def _runs(n_success=5, n_total=5, minutes=10):
    out = []
    for i in range(n_total):
        out.append({
            "conclusion": "success" if i < n_success else "failure",
            "run_started_at": "2026-10-15T00:00:00Z",
            "updated_at": f"2026-10-15T00:{minutes:02d}:00Z",
        })
    return {"workflow_runs": out}


def _default_handler(*, release_map=None, tags_map=None, runs=None, open_issues=None):
    release_map = release_map or {}
    tags_map = tags_map or {}

    def handler(path, params, *, method="GET", body=None):
        if method == "POST":
            if path.endswith("/labels"):
                return {}, {"status": 201}
            if path.endswith("/issues"):
                return {"number": 101}, {"status": 201}
            if "/comments" in path:
                return {"id": 1}, {"status": 201}
            raise AssertionError(f"unexpected POST {path}")
        if path.endswith("/releases/latest"):
            repo = path.split("/repos/", 1)[1].split("/releases/", 1)[0]
            if repo in release_map:
                payload = release_map[repo]
                if isinstance(payload, Exception):
                    raise payload
                return payload, {"status": 200}
            raise gh.GitHubError(404, "Not Found", path)
        if path.endswith("/tags"):
            repo = path.split("/repos/", 1)[1].split("/tags", 1)[0]
            return tags_map.get(repo, []), {"status": 200}
        if path.endswith("/actions/runs"):
            return (runs if runs is not None else _runs()), {"status": 200}
        if path.endswith("/issues"):
            return (open_issues if open_issues is not None else []), {"status": 200}
        raise AssertionError(f"unexpected GET {path}")

    return handler


def _install_fake_gh(monkeypatch, handler):
    calls = []

    def fake(path, params=None, *, method="GET", body=None, token=None, **kwargs):
        calls.append({"path": path, "params": params or {}, "method": method, "body": body})
        return handler(path, params or {}, method=method, body=body)

    monkeypatch.setattr(gh, "request", fake)
    return calls


def _write_state(cfg, payload):
    kb = store.knowledge_root(cfg)
    kb.mkdir(parents=True, exist_ok=True)
    (kb / monitor.STATE_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_state(cfg):
    return json.loads((store.knowledge_root(cfg) / monitor.STATE_FILENAME)
                      .read_text(encoding="utf-8"))


def _seed_alerted(cfg, tag="v1.0.0", repo="acme/tool"):
    _write_state(cfg, {"version": 1,
                       "watched": {repo: {"last_seen_tag": tag, "alerted_tag": tag}},
                       "ci": {}, "deps": {}})


# ---------------------------------------------------------------- 解析与版本

def test_parse_requirements_skips_comments_options_markers():
    reqs = monitor.parse_requirements(
        "--hash=sha256:abc\n# 注释  \n\nA_pkg>=1.0\nb.pkg[extra] ==2.0\r\n!broken\n")
    by_name = {r["name"]: r for r in reqs if r["name"]}
    assert by_name["A_pkg"]["spec"] == ">=1.0"
    assert by_name["b.pkg"]["spec"] == "==2.0"       # 环境标记/花括号被剥掉
    assert sum(1 for r in reqs if r.get("unparsed")) == 1


def test_ver_tuple_and_bump_kind():
    assert monitor._ver_tuple("v2.3.4") == (2, 3, 4)
    assert monitor._ver_tuple("0.4.71b0") == (0, 4, 71)   # 预发布后缀归一到数字核
    assert monitor._ver_tuple("1.2") == (1, 2, 0)
    assert monitor._ver_tuple("nightly") is None
    assert monitor._bump_kind("1.0.0", "1.0.1") == "patch"
    assert monitor._bump_kind("1.0.0", "1.1.0") == "minor"
    assert monitor._bump_kind("1.0.0", "2.0.0") == "major"
    assert monitor._bump_kind("1.0.0", "1.0.0") == "same"
    assert monitor._bump_kind("1.0.0", "nightly") == "unknown"


def test_classify_pin_matrix():
    assert monitor._classify_pin("==1.0.0", "1.0.0")[0] == "ok"
    assert monitor._classify_pin("==0.9.0", "1.0.5") == ("outdated", "major")
    assert monitor._classify_pin("==1.0.0", "1.0.2") == ("outdated", "patch")
    assert monitor._classify_pin(">=2.3.3,<3.0", "2.9.0")[0] == "ok"
    status, reason = monitor._classify_pin(">=2.3.3,<3.0", "3.1.0")
    assert status == "held" and "上界" in reason
    assert monitor._classify_pin(">=2.0,<3.0", "1.9.0")[0] == "ahead"
    assert monitor._classify_pin(">=1.0", "not.a.version")[0] == "unknown"
    assert monitor._classify_pin("~=banana", "1.0")[0] == "unknown"


# ---------------------------------------------------------------- 依赖检查

def test_check_deps_buckets(cfg):
    deps = monitor.check_deps(cfg, fetch_latest=_fake_fetch())
    assert [d["name"] for d in deps["outdated"]] == ["alpha", "gamma"]
    assert {d["bump"] for d in deps["outdated"]} == {"major", "patch"}
    assert [d["name"] for d in deps["unpinned"]] == ["weird"]
    assert deps["up_to_date"] == 2          # beta、extra
    assert deps["resolved"] == 5 and deps["attempted"] == 5
    assert deps["errors"] == []


def test_check_deps_isolates_package_errors_and_missing_file(cfg):
    def fetch(name):
        if name == "alpha":
            raise ValueError("network down")
        return LATEST.get(name)

    deps = monitor.check_deps(cfg, fetch_latest=fetch)
    assert any("alpha" in e and "network down" in e for e in deps["errors"])
    assert deps["resolved"] == 4 and len(deps["outdated"]) == 1

    cfg["monitoring"]["self_requirements"] = ["requirements.txt", "nope.txt"]
    deps = monitor.check_deps(cfg, fetch_latest=_fake_fetch())
    assert [f["status"] for f in deps["files"]] == ["ok", "missing"]
    assert any("nope.txt" in e for e in deps["errors"])


def test_pypi_latest_kwarg_timeout_and_no_auth_header(monkeypatch):
    """回归：urlopen 第二位是 data 不是 timeout（真实冒烟抓到的 bug）；
    另固定安全性质：PyPI 请求绝不携带 Authorization 头（令牌不带去第三方域名）"""
    seen = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"info": {"version": "1.2.3"}}'

    def fake_urlopen(req, **kwargs):
        seen["req"] = req
        seen.update(kwargs)
        return FakeResp()

    monkeypatch.setattr(monitor, "_urlopen", fake_urlopen)
    assert monitor._pypi_latest("pkg") == "1.2.3"
    assert seen["timeout"] == monitor.PYPI_TIMEOUT
    assert "pypi.org/pypi/pkg/json" in seen["req"].full_url
    assert seen["req"].get_header("Authorization") is None


def test_secret_hygiene_scan(cfg, tmp_path):
    # 干净仓库 → ok
    res = monitor.check_secret_hygiene()
    assert res["status"] == "ok" and res["hits"] == []

    # 工作流里埋伪造令牌 → error，且命中说明带文件名
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "evil.yml").write_text('env:\n  TOKEN: "ghp_' + "A" * 36 + '"\n', encoding="utf-8")
    res = monitor.check_secret_hygiene()
    assert res["status"] == "error"
    assert any("evil.yml" in h and "ghp_***" in h for h in res["hits"])

    # .git/config 内嵌令牌同样命中（remote URL 里带凭据）
    gc = tmp_path / ".git" / "config"
    gc.parent.mkdir(parents=True, exist_ok=True)
    gc.write_text('[remote "origin"]\n\turl = https://ghp_' + "B" * 36
                  + "@github.com/x/y.git\n", encoding="utf-8")
    res = monitor.check_secret_hygiene()
    assert any(".git" in h for h in res["hits"])
    assert res["scanned"] == 2


# ---------------------------------------------------------------- watched 检查

def test_check_watched_baseline_and_change_detection(cfg, monkeypatch):
    items = [{"repo": "acme/tool", "kind": "release", "source": "config"}]
    _install_fake_gh(monkeypatch, _default_handler(release_map={"acme/tool": _release("v1.0.0")}))
    watched = monitor.check_watched(items, token="t", budget=monitor._Budget(5),
                                    state={}, now=NOW)
    assert watched[0]["status"] == "ok" and watched[0]["changed"] is False
    assert watched[0]["prev_tag"] == "" and watched[0]["alerted_tag"] == ""

    state = {"watched": {"acme/tool": {"last_seen_tag": "v1.0.0", "alerted_tag": "v0.9.0"}}}
    _install_fake_gh(monkeypatch, _default_handler(release_map={"acme/tool": _release("v1.1.0")}))
    watched = monitor.check_watched(items, token="t", budget=monitor._Budget(5),
                                    state=state, now=NOW)
    assert watched[0]["changed"] is True
    assert watched[0]["prev_tag"] == "v1.0.0" and watched[0]["alerted_tag"] == "v0.9.0"


def test_check_watched_404_tag_kind_and_budget(cfg, monkeypatch):
    items = [{"repo": "acme/gone", "kind": "release", "source": "config"}]
    _install_fake_gh(monkeypatch, _default_handler())
    watched = monitor.check_watched(items, token="t", budget=monitor._Budget(5),
                                    state={}, now=NOW)
    assert watched[0]["status"] == "no_release"

    tag_items = [{"repo": "acme/only-tags", "kind": "tag", "source": "config"}]
    _install_fake_gh(monkeypatch, _default_handler(tags_map={"acme/only-tags": [{"name": "v9"}]}))
    watched = monitor.check_watched(tag_items, token="t", budget=monitor._Budget(5),
                                    state={}, now=NOW)
    assert watched[0]["status"] == "ok" and watched[0]["tag"] == "v9"

    two = [{"repo": "a/one", "kind": "release", "source": "config"},
           {"repo": "a/two", "kind": "release", "source": "config"}]
    _install_fake_gh(monkeypatch, _default_handler(release_map={"a/one": _release("v1")}))
    watched = monitor.check_watched(two, token="t", budget=monitor._Budget(1),
                                    state={}, now=NOW)
    assert [w["status"] for w in watched] == ["ok", "skipped_budget"]


# ---------------------------------------------------------------- 告警构建

def _ok_entry(**over):
    base = {"repo": "acme/tool", "status": "ok", "tag": "v2.0.0",
            "alerted_tag": "v1.0.0", "prev_tag": "v1.0.0",
            "source": "config", "html_url": "u", "published_at": NOW.isoformat()}
    base.update(over)
    return base


def test_build_alerts_release_rules():
    alerts, notes = monitor.build_alerts([_ok_entry()], {"status": "skipped"}, state={})
    assert [a["title"] for a in alerts] == ["[gov-alert] acme/tool 新版本 v2.0.0"]
    assert alerts[0]["kind"] == "release" and "由 `scripts/gov/monitor.py`" in alerts[0]["body"]

    alerts, _ = monitor.build_alerts([_ok_entry(alerted_tag="")], {"status": "skipped"}, state={})
    assert alerts == []                       # 无记忆 → 只记基线，不告警

    alerts, notes = monitor.build_alerts([_ok_entry(tag="v0.9.0")], {"status": "skipped"}, state={})
    assert alerts == [] and any("版本回退" in n for n in notes)

    alerts, _ = monitor.build_alerts([_ok_entry(tag="v1.0.0")], {"status": "skipped"}, state={})
    assert alerts == []                       # 与已告警一致


def test_build_alerts_ci_transition():
    ci = {"status": "ok", "repo": "me/self", "runs": 10, "success": 8,
          "success_rate": 0.8, "avg_duration_min": 5.0, "floor": 0.9, "below_floor": True}
    alerts, _ = monitor.build_alerts([], ci, state={})
    assert alerts[0]["kind"] == "ci" and alerts[0]["title"] == "[gov-alert] CI 成功率低于下限"

    alerts, _ = monitor.build_alerts([], ci, state={"ci": {"last_rate": 0.85}})
    assert alerts == []                       # 持续低于不重复告警

    alerts, _ = monitor.build_alerts([], ci, state={"ci": {"last_rate": 0.95}})
    assert len(alerts) == 1                   # 从达标跌下来 → 告警

    alerts, _ = monitor.build_alerts([], {**ci, "below_floor": False}, state={})
    assert alerts == []


# ---------------------------------------------------------------- 告警落地

ALERT1 = {"kind": "release", "repo": "acme/tool", "fingerprint": "acme/tool:v2.0.0",
          "title": "[gov-alert] acme/tool 新版本 v2.0.0", "body": "b"}


def test_apply_alerts_create_duplicate_floodgate(monkeypatch):
    calls = _install_fake_gh(monkeypatch, _default_handler())
    budget = monitor._Budget(30)

    out = monitor.apply_alerts([ALERT1], self_repo="me/self", open_issues=[],
                               max_open=5, token="t", budget=budget)
    assert out[0]["outcome"] == "created" and out[0]["issue"] == 101

    before = len(calls)
    out = monitor.apply_alerts([ALERT1], self_repo="me/self",
                               open_issues=[{"number": 7, "title": ALERT1["title"],
                                             "created_at": "2026-01-01T00:00:00Z"}],
                               max_open=5, token="t", budget=budget)
    assert out[0]["outcome"] == "duplicate_open"
    assert calls[before:] == []               # 重复告警不产生任何请求

    open_list = [{"number": 7, "title": "[gov-alert] other 新版本 v1",
                  "created_at": "2026-01-01T00:00:00Z"}]
    before = len(calls)
    out = monitor.apply_alerts([ALERT1], self_repo="me/self", open_issues=open_list,
                               max_open=1, token="t", budget=budget)
    assert out[0]["outcome"] == "appended" and out[0]["issue"] == 7
    new_calls = calls[before:]
    assert any(c["path"].endswith("/issues/7/comments") for c in new_calls)
    assert not any(c["path"].endswith("/issues") and c["method"] == "POST"
                   for c in new_calls)        # 防洪：追加而非新建


def test_apply_alerts_error_is_recorded(monkeypatch):
    def handler(path, params, *, method="GET", body=None):
        raise gh.GitHubError(403, "forbidden", path)

    _install_fake_gh(monkeypatch, handler)
    out = monitor.apply_alerts([ALERT1], self_repo="me/self", open_issues=[],
                               max_open=5, token="t", budget=monitor._Budget(10))
    assert out[0]["outcome"] == "error" and "403" in out[0]["error"]


# ---------------------------------------------------------------- 状态提交

def test_update_state_commit_semantics():
    state = {}
    entry = _ok_entry(tag="v1.0.0", alerted_tag="", prev_tag="")
    notes = monitor.update_state(state, watched=[entry], self_ci={"status": "skipped"},
                                 outcomes=[], deps_issue=False, now=NOW)
    assert state["watched"]["acme/tool"]["alerted_tag"] == "v1.0.0"
    assert any("建立版本基线" in n for n in notes)

    entry2 = _ok_entry(tag="v2.0.0", alerted_tag="v1.0.0", prev_tag="v1.0.0")
    monitor.update_state(state, watched=[entry2], self_ci={"status": "skipped"},
                         outcomes=[{"kind": "release", "repo": "acme/tool",
                                    "outcome": "disabled"}],
                         deps_issue=False, now=NOW)
    assert state["watched"]["acme/tool"]["alerted_tag"] == "v1.0.0"   # 未送达不前进
    assert state["watched"]["acme/tool"]["last_seen_tag"] == "v2.0.0"

    monitor.update_state(state, watched=[entry2], self_ci={"status": "skipped"},
                         outcomes=[{"kind": "release", "repo": "acme/tool",
                                    "outcome": "created"}],
                         deps_issue=False, now=NOW)
    assert state["watched"]["acme/tool"]["alerted_tag"] == "v2.0.0"   # 送达后前进

    ci_bad = {"status": "ok", "success_rate": 0.5, "below_floor": True}
    monitor.update_state(state, watched=[], self_ci=ci_bad,
                         outcomes=[{"kind": "ci", "repo": "me/self",
                                    "outcome": "duplicate_open"}],
                         deps_issue=False, now=NOW)
    assert state["ci"]["last_rate"] == 0.5

    state2 = {"ci": {"last_rate": 0.95}}
    monitor.update_state(state2, watched=[], self_ci=ci_bad,
                         outcomes=[{"kind": "ci", "outcome": "disabled"}],
                         deps_issue=False, now=NOW)
    assert state2["ci"]["last_rate"] == 0.95                          # 未送达不前进
    monitor.update_state(state2, watched=[],
                         self_ci={"status": "ok", "success_rate": 0.99, "below_floor": False},
                         outcomes=[], deps_issue=False, now=NOW)
    assert state2["ci"]["last_rate"] == 0.99                          # 达标照常刷新


def test_load_state_corrupt_recovers_with_note(cfg):
    kb = store.knowledge_root(cfg)
    kb.mkdir(parents=True, exist_ok=True)
    (kb / monitor.STATE_FILENAME).write_text("{not json", encoding="utf-8")
    notes = []
    state = monitor._load_state(cfg, notes)
    assert state["watched"] == {} and any("损坏" in n for n in notes)


# ---------------------------------------------------------------- run() 端到端

def test_run_full_creates_alert_persists_report_and_state(cfg, monkeypatch, tmp_path):
    _seed_alerted(cfg)
    calls = _install_fake_gh(
        monkeypatch, _default_handler(release_map={"acme/tool": _release("v2.0.0")}))
    report = monitor.run(cfg, token="t", now=NOW, create_issues=True,
                         fetch_latest=_fake_fetch())

    assert report["status"] == "ok"
    assert report["watched"][0]["changed"] is True
    rel = [a for a in report["alerts"] if a["kind"] == "release"]
    assert rel and rel[0]["outcome"] == "created" and rel[0]["issue"] == 101

    saved = json.loads((tmp_path / "reports" / "2026-10-16" / "monitor.json")
                       .read_text(encoding="utf-8"))
    assert saved["status"] == "ok" and saved["metric_record"]["deps_outdated"] == 2
    snap = json.loads((tmp_path / "reports" / "metrics" / "2026-10-16.json")
                      .read_text(encoding="utf-8"))
    assert schemas.problems("metric_record", snap) == []
    assert snap["ci_success_rate"] == 1.0 and snap["avg_duration"] == 10.0

    st = _read_state(cfg)
    assert st["watched"]["acme/tool"]["alerted_tag"] == "v2.0.0"
    assert any(c["method"] == "POST" and c["path"].endswith("/issues") for c in calls)


def test_run_disabled_does_not_advance_and_no_mutations(cfg, monkeypatch, tmp_path):
    _seed_alerted(cfg)
    calls = _install_fake_gh(
        monkeypatch, _default_handler(release_map={"acme/tool": _release("v2.0.0")}))
    report = monitor.run(cfg, token="t", now=NOW, fetch_latest=_fake_fetch())

    assert [a["outcome"] for a in report["alerts"]] == ["disabled"]
    st = _read_state(cfg)
    assert st["watched"]["acme/tool"]["alerted_tag"] == "v1.0.0"     # 留待下轮重试
    assert st["watched"]["acme/tool"]["last_seen_tag"] == "v2.0.0"
    assert all(c["method"] == "GET" for c in calls)                   # 零变更


def test_run_issue_list_failure_skips_mutations(cfg, monkeypatch, tmp_path):
    _seed_alerted(cfg)

    def handler(path, params, *, method="GET", body=None):
        if path.endswith("/releases/latest"):
            return _release("v2.0.0"), {"status": 200}
        if path.endswith("/actions/runs"):
            return _runs(), {"status": 200}
        if path.endswith("/issues") and method == "GET":
            raise gh.GitHubError(403, "no access", path)
        raise AssertionError(f"不应被调用: {method} {path}")

    _install_fake_gh(monkeypatch, handler)
    report = monitor.run(cfg, token="t", now=NOW, create_issues=True,
                         fetch_latest=_fake_fetch())
    assert [a["outcome"] for a in report["alerts"]] == ["error"]
    assert any("issue-list" in e for e in report["errors"])
    st = _read_state(cfg)
    assert st["watched"]["acme/tool"]["alerted_tag"] == "v1.0.0"


def test_run_no_credentials_partial_but_deps_ok(cfg, monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise gh.NoCredentials("缺少 GITHUB_TOKEN / GH_TOKEN")

    monkeypatch.setattr(gh, "token_from_env", boom)
    calls = _install_fake_gh(monkeypatch, _default_handler())
    report = monitor.run(cfg, now=NOW, fetch_latest=_fake_fetch())

    assert report["status"] == "partial"
    assert report["watched"][0]["status"] == "skipped_no_credentials"
    assert any("credentials" in e for e in report["errors"])
    assert report["deps"]["resolved"] == 5
    assert calls == []                        # 完全没发 GitHub 请求


def test_run_dry_run_writes_nothing(cfg, monkeypatch, tmp_path):
    _install_fake_gh(monkeypatch, _default_handler(release_map={"acme/tool": _release("v1")}))
    report = monitor.run(cfg, token="t", now=NOW, write=False, fetch_latest=_fake_fetch())
    assert report["status"] == "ok"
    assert not (tmp_path / "reports").exists()
    assert not (tmp_path / "kb").exists()


def test_run_budget_truncation(cfg, monkeypatch):
    cfg["monitoring"]["watched"] = [{"repo": "a/one", "kind": "release"},
                                    {"repo": "a/two", "kind": "release"}]
    _install_fake_gh(monkeypatch, _default_handler(release_map={"a/one": _release("v1")}))
    report = monitor.run(cfg, token="t", now=NOW, max_requests=1, fetch_latest=_fake_fetch())
    assert report["truncated"] is True
    assert [w["status"] for w in report["watched"]] == ["ok", "skipped_budget"]
    assert report["self_ci"]["status"] == "skipped_budget"


def test_run_deps_issue_monthly_dedup(cfg, monkeypatch):
    _install_fake_gh(monkeypatch, _default_handler(release_map={"acme/tool": _release("v1.0.0")}))
    report = monitor.run(cfg, token="t", now=NOW, create_issues=True, deps_issue=True,
                         fetch_latest=_fake_fetch())
    deps_alert = [a for a in report["alerts"] if a["kind"] == "deps"]
    assert deps_alert and deps_alert[0]["outcome"] == "created"
    assert deps_alert[0]["title"] == "[gov-deps] 依赖健康报告 2026-10"
    assert "建议升级顺序" in deps_alert[0]["body"]
    assert _read_state(cfg)["deps"]["last_issue_month"] == "2026-10"

    report2 = monitor.run(cfg, token="t", now=NOW, create_issues=True, deps_issue=True,
                          fetch_latest=_fake_fetch())
    assert not [a for a in report2["alerts"] if a["kind"] == "deps"]
    assert any("已发布过" in n for n in report2["notes"])


def test_run_monitors_cards_and_updates_card(cfg, monkeypatch):
    store.save_project_card(schemas.new_record(
        "project_card", name="acme/lib", url="u", domain="quant",
        status="analyzed", version_watched="v1.0.0"), cfg)
    cfg["monitoring"]["watched"] = []
    _install_fake_gh(monkeypatch, _default_handler(release_map={"acme/lib": _release("v2.0.0")}))
    report = monitor.run(cfg, token="t", now=NOW, fetch_latest=_fake_fetch())

    w = report["watched"][0]
    assert w["source"] == "card" and w["status"] == "ok" and w["changed"] is True
    assert report["alerts"] == []             # 无告警记忆 → 静默基线
    card = store.load_project_card("acme/lib", cfg)
    assert card["version_watched"] == "v2.0.0"
    assert card["last_checked"] == NOW.isoformat()
    assert card["quality"]["release"]["latest_tag"] == "v2.0.0"
    assert _read_state(cfg)["watched"]["acme/lib"]["alerted_tag"] == "v2.0.0"
    assert any("建立版本基线" in n for n in report["notes"])


# ---------------------------------------------------------------- CLI

def _write_cfg_file(cfg, tmp_path):
    path = tmp_path / "gov.yml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def test_cli_dry_run_prints_and_writes_nothing(cfg, monkeypatch, capsys, tmp_path):
    _install_fake_gh(monkeypatch, _default_handler(release_map={"acme/tool": _release("v1.0.0")}))
    monkeypatch.setattr(monitor, "_pypi_latest", lambda name, **kw: LATEST.get(name, "1.0.0"))
    rc = monitor.main(["--config", str(_write_cfg_file(cfg, tmp_path)), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "=== Gov Monitor ===" in out and "deps" in out and "watched" in out
    assert not (tmp_path / "reports").exists()
    assert not (tmp_path / "kb").exists()


def test_cli_config_error_returns_2(tmp_path):
    rc = monitor.main(["--config", str(tmp_path / "missing.yml"), "--dry-run"])
    assert rc == 2
