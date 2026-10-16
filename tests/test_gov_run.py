"""⑥编排 scripts/gov/run.py 单元测试（全部离线）

覆盖：阶段顺序与参数透传、失败即停、deps 模式、失败 Issue 的去重/防洪/零变更
（拿不到开放列表）、shortlist 快照桥接、sync-memory 网关（restore 失败绝不
persist、kb 不在仓库内拒绝运行）、dry-run 零副作用、摘要落盘、CLI 退出码。
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.gov import config as gconfig  # noqa: E402
from scripts.gov import github_api as gh  # noqa: E402
from scripts.gov import run as grun  # noqa: E402

GOV_CONFIG = REPO_ROOT / "scripts" / "gov" / "config.yml"
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)
DATE = "2026-10-16"


@pytest.fixture()
def cfg(tmp_path):
    data = gconfig.load_config(GOV_CONFIG)
    data["knowledge"]["root"] = str(tmp_path / "kb")
    return data


def _sync_env(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    data = gconfig.load_config(GOV_CONFIG)
    data["knowledge"]["root"] = str(root / "kb")
    return root, data


class FakeExec:
    """假阶段执行器：按模块名决定退出码，记录全部调用"""

    def __init__(self, codes=None):
        self.codes = dict(codes or {})
        self.calls = []

    def __call__(self, cmd, cwd):
        args = [str(item) for item in cmd]
        module = next((a for a in args if a.startswith("scripts.gov.")), "?")
        stage = module.split(".")[-1]
        self.calls.append((stage, args))
        code = int(self.codes.get(stage, 0))
        stdout = f"[{stage}] done\n"
        stderr = "" if code == 0 else f"[{stage}] boom\n"
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


class FakeAPI:
    """假 GitHub API：记录调用并按路由返回"""

    def __init__(self, open_issues=None):
        self.calls = []
        self.open_issues = list(open_issues or [])
        self.post_issue_number = 7
        self.list_error = None

    def __call__(self, path, params=None, *, method="GET", body=None, token=None,
                 **kwargs):
        self.calls.append({"method": method, "path": path, "params": params,
                           "body": body})
        if method == "GET" and path.endswith("/issues"):
            if self.list_error is not None:
                raise self.list_error
            return self.open_issues, {"status": 200}
        if method == "POST" and path.endswith("/labels"):
            raise gh.GitHubError(422, "already exists")
        if method == "POST" and path.endswith("/comments"):
            return {"id": 1}, {"status": 201}
        if method == "POST" and path.endswith("/issues"):
            return {"number": self.post_issue_number}, {"status": 201}
        raise AssertionError(f"unexpected API call: {method} {path}")


def _run(cfg, ex, tmp_path, **kwargs):
    return grun.run(cfg, root=REPO_ROOT, reports_dir=tmp_path / "reports",
                    now=NOW, executor=ex, **kwargs)


# --------------------------------------------------------------------------
# 阶段编排
# --------------------------------------------------------------------------
def test_daily_order_and_flags(cfg, tmp_path):
    ex = FakeExec()
    report = _run(cfg, ex, tmp_path, mode="daily", create_issues=True)
    assert [name for name, _ in ex.calls] == ["discover", "score", "analyze", "monitor"]
    assert "--create-issues" in ex.calls[-1][1]
    assert "--deps-issue" not in ex.calls[-1][1]
    assert "--print" in ex.calls[0][1]
    assert "--config" not in ex.calls[0][1]
    assert report["status"] == "ok"
    assert [s["name"] for s in report["stages"]] == ["discover", "score", "analyze", "monitor"]


def test_stage_args_pass_config_through(cfg, tmp_path):
    ex = FakeExec()
    _run(cfg, ex, tmp_path, mode="daily", config_path="scripts/gov/config.yml")
    for _, args in ex.calls:
        assert "--config" in args


def test_fail_fast_stops_downstream_and_reports(cfg, tmp_path):
    ex = FakeExec(codes={"analyze": 1})
    api = FakeAPI(open_issues=[{"number": 2, "title": f"[gov-run] 编排失败 {DATE}",
                                "created_at": "2026-10-16T00:00:00Z",
                                "pull_request": {}}])  # PR 混入同标题应被过滤
    report = _run(cfg, ex, tmp_path, mode="daily", create_issues=True, request=api)
    assert [name for name, _ in ex.calls] == ["discover", "score", "analyze"]
    assert report["status"] == "failed"
    assert report["stages"][-1]["name"] == "analyze"
    assert "boom" in report["stages"][-1]["output_tail"]
    assert report["failure_issue"] == {"outcome": "created", "issue": 7}
    posted = [c for c in api.calls
              if c["method"] == "POST" and c["path"].endswith("/issues")]
    assert len(posted) == 1
    assert posted[0]["body"]["title"] == f"[gov-run] 编排失败 {DATE}"
    assert "analyze" in posted[0]["body"]["body"]


def test_failure_without_create_issues_touches_no_api(cfg, tmp_path):
    ex = FakeExec(codes={"discover": 1})
    api = FakeAPI()
    report = _run(cfg, ex, tmp_path, mode="daily", create_issues=False, request=api)
    assert report["status"] == "failed"
    assert report["failure_issue"] is None
    assert api.calls == []


def test_same_day_failure_appends_comment(cfg, tmp_path):
    ex = FakeExec(codes={"discover": 1})
    api = FakeAPI(open_issues=[{"number": 11, "title": f"[gov-run] 编排失败 {DATE}",
                                "created_at": "2026-10-16T01:00:00Z"}])
    report = _run(cfg, ex, tmp_path, mode="daily", create_issues=True, request=api)
    assert report["failure_issue"]["outcome"] == "appended"
    assert report["failure_issue"]["issue"] == 11
    assert any(c["path"].endswith("/issues/11/comments") for c in api.calls)
    assert not any(c["method"] == "POST" and c["path"].endswith("/issues")
                   for c in api.calls)


def test_flood_cap_appends_to_latest(cfg, tmp_path):
    issues = [{"number": i, "title": f"[gov-run] 编排失败 2026-10-0{i}",
               "created_at": f"2026-10-0{i}T00:00:00Z"} for i in range(1, 7)]
    api = FakeAPI(open_issues=issues)  # 6 条 ≥ max_open_alerts（config 为 5）
    ex = FakeExec(codes={"discover": 1})
    report = _run(cfg, ex, tmp_path, mode="daily", create_issues=True, request=api)
    assert report["failure_issue"]["outcome"] == "appended"
    assert report["failure_issue"]["issue"] == 6
    assert any(c["path"].endswith("/issues/6/comments") for c in api.calls)
    assert not any(c["method"] == "POST" and c["path"].endswith("/issues")
                   for c in api.calls)


def test_no_open_listing_means_zero_change(cfg, tmp_path):
    api = FakeAPI()
    api.list_error = gh.GitHubError(500, "boom")
    ex = FakeExec(codes={"score": 1})
    report = _run(cfg, ex, tmp_path, mode="daily", create_issues=True, request=api)
    assert report["failure_issue"]["outcome"] == "skipped"
    assert all(c["method"] == "GET" for c in api.calls)


def test_deps_mode_runs_monitor_only(cfg, tmp_path):
    ex = FakeExec()
    report = _run(cfg, ex, tmp_path, mode="deps", create_issues=True)
    assert [name for name, _ in ex.calls] == ["monitor"]
    assert "--deps-issue" in ex.calls[0][1]
    assert "--create-issues" in ex.calls[0][1]
    assert report["bridge"] is None


def test_stage_timeout_reported(cfg, tmp_path):
    def timeout_executor(cmd, cwd):
        raise subprocess.TimeoutExpired(cmd, 1)

    report = _run(cfg, timeout_executor, tmp_path, mode="deps")
    assert report["status"] == "failed"
    assert report["stages"][0]["exit_code"] == 124
    assert "超时" in report["stages"][0]["output_tail"]


def test_dry_run_skips_side_effects(cfg, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(grun.memory_branch, "restore",
                        lambda *a, **k: called.append("restore"))
    monkeypatch.setattr(grun.memory_branch, "persist",
                        lambda *a, **k: called.append("persist"))
    ex = FakeExec(codes={"discover": 1})
    api = FakeAPI()
    report = _run(cfg, ex, tmp_path, mode="daily", create_issues=True,
                  sync_memory=True, dry_run=True, request=api)
    assert called == []
    assert api.calls == []
    assert report["status"] == "failed"
    assert report["failure_issue"] is None
    assert not (tmp_path / "reports").exists()


def test_summary_written_when_not_dry_run(cfg, tmp_path):
    ex = FakeExec()
    report = _run(cfg, ex, tmp_path, mode="daily")
    path = tmp_path / "reports" / DATE / "run.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "ok"
    assert len(data["stages"]) == 4
    assert report["summary_path"] == str(path)


# --------------------------------------------------------------------------
# sync-memory 网关
# --------------------------------------------------------------------------
def test_restore_failure_blocks_stages_and_persist(tmp_path, monkeypatch):
    root, cfg = _sync_env(tmp_path)

    def boom(*args, **kwargs):
        raise grun.memory_branch.GitError("git fetch 失败")

    monkeypatch.setattr(grun.memory_branch, "restore", boom)
    persisted = []
    monkeypatch.setattr(grun.memory_branch, "persist",
                        lambda *a, **k: persisted.append(1) or {"action": "pushed"})
    ex = FakeExec()
    api = FakeAPI()
    report = grun.run(cfg, mode="daily", create_issues=True, sync_memory=True,
                      root=root, reports_dir=tmp_path / "reports", now=NOW,
                      executor=ex, request=api)
    assert ex.calls == []
    assert persisted == []
    assert report["status"] == "failed"
    assert report["memory"]["restore"]["action"] == "error"
    assert report["failure_issue"]["outcome"] == "created"
    body = next(c["body"]["body"] for c in api.calls
                if c["method"] == "POST" and c["path"].endswith("/issues"))
    assert "restore-memory" in body


def test_sync_success_restores_and_persists(tmp_path, monkeypatch):
    root, cfg = _sync_env(tmp_path)
    calls = {}

    def fake_restore(root_, *, kb_rel):
        calls["restore_kb_rel"] = kb_rel
        return {"action": "absent"}

    def fake_persist(root_, *, kb_rel, message):
        calls["persist_kb_rel"] = kb_rel
        calls["message"] = message
        return {"action": "pushed", "commit": "abc123"}

    monkeypatch.setattr(grun.memory_branch, "restore", fake_restore)
    monkeypatch.setattr(grun.memory_branch, "persist", fake_persist)
    ex = FakeExec()
    report = grun.run(cfg, mode="daily", sync_memory=True, root=root,
                      reports_dir=tmp_path / "reports", now=NOW, executor=ex)
    assert calls["restore_kb_rel"] == "kb"
    assert calls["persist_kb_rel"] == "kb"
    assert DATE in calls["message"]
    assert report["memory"]["restore"]["action"] == "absent"
    assert report["memory"]["persist"]["action"] == "pushed"
    assert any("首次运行" in note for note in report["notes"])


def test_persist_failure_marks_run_failed(tmp_path, monkeypatch):
    root, cfg = _sync_env(tmp_path)
    monkeypatch.setattr(grun.memory_branch, "restore",
                        lambda *a, **k: {"action": "restored", "files": 3})

    def boom(*args, **kwargs):
        raise grun.memory_branch.GitError("push 被拒")

    monkeypatch.setattr(grun.memory_branch, "persist", boom)
    ex = FakeExec()
    report = grun.run(cfg, mode="daily", sync_memory=True, root=root,
                      reports_dir=tmp_path / "reports", now=NOW, executor=ex)
    assert report["status"] == "failed"
    assert report["memory"]["persist"]["action"] == "error"
    assert report["failure_issue"] is None


def test_sync_kb_outside_repo_fails_cleanly(cfg, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(grun.memory_branch, "restore",
                        lambda *a, **k: called.append(1))
    ex = FakeExec()
    report = _run(cfg, ex, tmp_path, mode="daily", sync_memory=True)
    assert called == []
    assert ex.calls == []
    assert report["status"] == "failed"
    assert report["memory"]["restore"]["action"] == "error"


# --------------------------------------------------------------------------
# shortlist 快照桥接
# --------------------------------------------------------------------------
def test_install_prev_shortlist_cases(tmp_path):
    kb = tmp_path / "kb"
    reports = tmp_path / "reports"
    snap = kb / "state" / "prev_shortlist.json"
    snap.parent.mkdir(parents=True)

    result = grun.install_prev_shortlist(kb, reports, DATE)
    assert result["action"] == "none"

    snap.write_text("{not json", encoding="utf-8")
    result = grun.install_prev_shortlist(kb, reports, DATE)
    assert result["action"] == "none"
    assert "跳过" in result["reason"]

    snap.write_text(json.dumps({"version": 1, "date": "2026-10-15",
                                "shortlist": {"entries": [{"full_name": "a/b",
                                                           "stars": 5}]}}),
                    encoding="utf-8")
    result = grun.install_prev_shortlist(kb, reports, DATE)
    assert result["action"] == "installed"
    data = json.loads((reports / "2026-10-15" / "shortlist.json")
                      .read_text(encoding="utf-8"))
    assert data["entries"][0]["full_name"] == "a/b"

    result = grun.install_prev_shortlist(kb, reports, DATE)
    assert result["action"] == "present"

    snap.write_text(json.dumps({"version": 1, "date": DATE, "shortlist": {}}),
                    encoding="utf-8")
    result = grun.install_prev_shortlist(kb, reports, DATE)
    assert result["action"] == "none"
    assert "同日" in result["reason"]


def test_save_prev_shortlist_cases(tmp_path):
    kb = tmp_path / "kb"
    reports = tmp_path / "reports"

    result = grun.save_prev_shortlist(kb, reports, DATE)
    assert result["action"] == "none"

    src = reports / DATE
    src.mkdir(parents=True)
    (src / "shortlist.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    result = grun.save_prev_shortlist(kb, reports, DATE)
    assert result["action"] == "saved"
    snap = json.loads((kb / "state" / "prev_shortlist.json").read_text(encoding="utf-8"))
    assert snap["date"] == DATE
    assert snap["shortlist"] == {"entries": []}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def test_main_config_error_returns_2(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("", encoding="utf-8")
    assert grun.main(["--config", str(bad)]) == 2


def test_main_rejects_bad_mode():
    with pytest.raises(SystemExit) as exc:
        grun.main(["--mode", "nope"])
    assert exc.value.code == 2
