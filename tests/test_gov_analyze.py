"""⑤学习 scripts/gov/analyze.py 单元测试

全部离线：克隆被替换为注入的 fake_clone（在 tmp 里造一棵仓库树），
不发网络请求、不依赖本机 git。重点验证：依赖/API 面/质量信号提取、
never_execute 安全边界（候选源码绝不执行）、A/B 增量与单轮封顶、
克隆失败隔离、dry-run 零落盘、报告与项目卡落盘、CLI 退出码。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.gov import analyze  # noqa: E402
from scripts.gov import config as gconfig  # noqa: E402
from scripts.gov import schemas  # noqa: E402
from scripts.gov import store  # noqa: E402

GOV_CONFIG = REPO_ROOT / "scripts" / "gov" / "config.yml"
NOW = datetime(2026, 10, 16, 3, 30, tzinfo=timezone.utc)
TODAY = "2026-10-16"

REPO_FILES = {
    "README.md": "# demo\n" * 5,
    "LICENSE": "MIT License\n",
    "requirements.txt": "alpha==1.0.0\nbeta>=2.0,<3.0\nweird\n-r other.txt\n# 注释\n",
    "pyproject.toml": '[project]\nname = "demo"\ndependencies = ["gamma==5.0.0"]\n',
    "pkg/__init__.py": '__all__ = ["Api"]\n\n\ndef build():\n    return 1\n',
    "pkg/core.py": ("def run(a):\n    return a\n\n\nclass Engine:\n    pass\n\n\n"
                    "def _hidden():\n    return 2\n"),
    "tests/test_basic.py": "def test_ok():\n    assert True\n",
    ".github/workflows/ci.yml": "on: push\n",
    "docs/index.md": "# docs\n",
}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    base = gconfig.load_config(GOV_CONFIG)
    base["knowledge"]["root"] = "kb"
    monkeypatch.setattr(store, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(store, "REPORTS_DIR", tmp_path / "reports")
    return base


def _entry(name="acme/tool", tier="A", score=80.0, **over):
    e = {
        "full_name": name, "url": f"https://github.com/{name}", "domain": "quant",
        "keyword": "kw", "stars": 120, "language": "Python", "license": "MIT",
        "tier": tier, "score": score,
        "discovered_at": "2026-10-15T00:00:00+00:00",
    }
    e.update(over)
    return e


def _shortlist(tmp_path, entries, date=TODAY):
    path = tmp_path / "reports" / date / "shortlist.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    return path


def _fake_clone(files=None, marker=None, fail=None):
    """返回 clone_fn：在 dest 造一棵仓库树；url 命中 fail 时抛错；marker 触发时写入即得证。"""
    tree = dict(REPO_FILES if files is None else files)

    def clone(url, dest, *, depth, timeout):
        if fail and fail in url:
            raise RuntimeError("模拟克隆失败")
        dest.mkdir(parents=True, exist_ok=True)
        for rel, text in tree.items():
            p = dest / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        if marker is not None:
            (dest / "boom.py").write_text(
                f'open(r"{marker}", "w").write("pwned")\n', encoding="utf-8")

    return clone


def _build_tree(tmp_path, files=None, marker=None):
    root = tmp_path / "repo"
    _fake_clone(files=files, marker=marker)(None, root, depth=1, timeout=1)
    return root


# --------------------------------------------------------------------------
# analyze_tree：提取信号
# --------------------------------------------------------------------------
def test_analyze_tree_extracts_signals(tmp_path):
    root = _build_tree(tmp_path)
    (root / ".git").mkdir(exist_ok=True)  # 克隆机制产物：不应出现在 structure 信号里
    signals = analyze.analyze_tree(root, include_extensions=(".py",), max_files=400)
    q = signals["quality"]
    assert q["analyzer"] == analyze.ANALYZER_ID
    assert q["tests"] is True and q["ci"] is True and q["docs_dir"] is True
    assert q["readme"] == "README.md" and q["readme_chars"] > 0
    assert q["license_file"] == "LICENSE"
    assert "requirements.txt" in q["manifests"] and "pyproject.toml" in q["manifests"]
    assert q["loc"] > 0 and q["code_files"] == 3
    assert "pkg/" in q["structure"] and ".github/" in q["structure"]
    assert ".git/" not in q["structure"]

    deps = signals["deps"]
    assert "alpha==1.0.0" in deps and "beta>=2.0,<3.0" in deps
    assert "weird" in deps and "gamma==5.0.0" in deps
    assert not any(d.startswith("-r") for d in deps)
    assert set(q["deps_from"]) == {"pyproject.toml", "requirements.txt"}

    surface = signals["api_surface"]
    assert any(s.startswith("pkg/core.py: ") and "run" in s and "Engine" in s
               for s in surface)
    assert any(s.startswith("pkg/__init__.py: ") and "Api" in s and "build" in s
               for s in surface)
    assert all("_hidden" not in s for s in surface)
    assert all(not s.startswith("tests/") for s in surface)  # 测试不是公共 API 面


def test_source_is_never_executed(tmp_path, cfg):
    """性质测试：源码里的模块级副作用（open/write）在整条流水线里绝不触发。"""
    marker = tmp_path / "PWNED"
    _shortlist(tmp_path, [_entry()])
    analyze.run(cfg, now=NOW, clone_fn=_fake_clone(marker=marker))
    assert not marker.exists()


def test_syntax_error_recorded_not_fatal(tmp_path):
    files = dict(REPO_FILES)
    files["pkg/broken.py"] = "def broken(:\n"
    signals = analyze.analyze_tree(_build_tree(tmp_path, files=files),
                                   include_extensions=(".py",), max_files=400)
    q = signals["quality"]
    assert q["api"]["syntax_errors"] == ["pkg/broken.py"]
    assert any("AST 解析失败" in c for c in q["caveats"])
    assert any(s.startswith("pkg/core.py: ") for s in signals["api_surface"])


def test_poetry_layout_caveat(tmp_path):
    files = dict(REPO_FILES)
    files["pyproject.toml"] = '[tool.poetry]\nname = "demo"\n'
    signals = analyze.analyze_tree(_build_tree(tmp_path, files=files),
                                   include_extensions=(".py",), max_files=400)
    assert any("poetry" in c for c in signals["quality"]["caveats"])
    assert "alpha==1.0.0" in signals["deps"]  # requirements 照常解析


def test_unparsed_requirements_line_skipped(tmp_path):
    files = dict(REPO_FILES)
    files["requirements.txt"] = "alpha==1.0.0\n!!badline\n"
    signals = analyze.analyze_tree(_build_tree(tmp_path, files=files),
                                   include_extensions=(".py",), max_files=400)
    assert "alpha==1.0.0" in signals["deps"]
    assert not any("badline" in d for d in signals["deps"])
    assert any("无法解析" in c for c in signals["quality"]["caveats"])


def test_scan_truncation_flag(tmp_path):
    files = {f"m{i}.py": "x = 1\n" for i in range(6)}
    signals = analyze.analyze_tree(_build_tree(tmp_path, files=files),
                                   include_extensions=(".py",), max_files=2)
    q = signals["quality"]
    assert q["truncated"] is True and q["code_files"] == 2
    assert any("截断" in c for c in q["caveats"])


def test_api_surface_cap(tmp_path):
    files = {f"m{i:02d}.py": "def f():\n    pass\n" for i in range(45)}
    signals = analyze.analyze_tree(_build_tree(tmp_path, files=files),
                                   include_extensions=(".py",), max_files=400)
    assert len(signals["api_surface"]) == analyze.API_ENTRIES_CAP
    assert any("上限" in c for c in signals["quality"]["caveats"])


def test_structure_cap(tmp_path):
    files = {f"f{i:02d}.md": "x\n" for i in range(25)}
    signals = analyze.analyze_tree(_build_tree(tmp_path, files=files),
                                   include_extensions=(".py",), max_files=400)
    structure = signals["quality"]["structure"]
    assert len(structure) == analyze.STRUCTURE_CAP + 1
    assert structure[-1].startswith("…")


# --------------------------------------------------------------------------
# run：增量、封顶、失败隔离、落盘
# --------------------------------------------------------------------------
def test_run_creates_cards_for_ab_only(tmp_path, cfg):
    _shortlist(tmp_path, [_entry(), _entry("acme/two", tier="B", score=60.0,
                                           discovered_at=""),
                          _entry("acme/three", tier="C", score=40.0)])
    report = analyze.run(cfg, now=NOW, clone_fn=_fake_clone())
    assert report["status"] == "ok"
    assert report["count_ab"] == 2 and report["analyzed"] == 2
    assert report["source"]["date"] == TODAY
    assert report["source"]["path"].endswith("shortlist.json")
    assert any("C 级 1 个" in n for n in report["notes"])

    card = store.load_project_card("acme/tool", cfg)
    assert card is not None
    assert card["status"] == "analyzed" and card["tier"] == "A"
    assert card["version_watched"] == ""  # 版本跟踪归 ③monitor
    assert card["first_seen"] == "2026-10-15T00:00:00+00:00"
    assert card["last_checked"] == NOW.isoformat()
    assert "gamma==5.0.0" in card["deps"] and card["api_surface"]
    assert card["quality"]["note"].startswith("Python 项目")
    assert "⑤学习完成" in card["reason"]

    card2 = store.load_project_card("acme/two", cfg)
    assert card2["tier"] == "B"
    assert card2["first_seen"] == NOW.isoformat()  # discovered_at 缺失回退 now
    assert store.load_project_card("acme/three", cfg) is None

    for e in report["entries"]:
        if e["status"] == "ok":
            assert e["summary"].startswith("files=")
            assert e["quality"]["analyzer"] == analyze.ANALYZER_ID


def test_existing_card_skipped_incremental(tmp_path, cfg):
    _shortlist(tmp_path, [_entry(), _entry("acme/two", tier="B")])
    store.save_project_card(schemas.new_record(
        "project_card", name="acme/tool", url="https://github.com/acme/tool",
        domain="quant", status="rejected"), cfg)
    inner = _fake_clone()
    calls = []

    def tracking(url, dest, *, depth, timeout):
        calls.append(url)
        inner(url, dest, depth=depth, timeout=timeout)

    report = analyze.run(cfg, now=NOW, clone_fn=tracking)
    assert report["skipped_existing"] == 1 and report["analyzed"] == 1
    assert calls == ["https://github.com/acme/two.git"]
    statuses = {e["name"]: e["status"] for e in report["entries"]}
    assert statuses["acme/tool"] == "skipped_existing"
    assert statuses["acme/two"] == "ok"


def test_limit_argument_caps_analysis(tmp_path, cfg):
    _shortlist(tmp_path, [_entry(f"acme/r{i}") for i in range(4)])
    inner = _fake_clone()
    calls = []

    def tracking(url, dest, *, depth, timeout):
        calls.append(url)
        inner(url, dest, depth=depth, timeout=timeout)

    report = analyze.run(cfg, now=NOW, clone_fn=tracking, limit=2)
    assert report["analyzed"] == 2 and report["skipped_limit"] == 2
    assert len(calls) == 2
    assert report["limit"] == 2


def test_config_limit_used_by_default(tmp_path, cfg):
    cfg["analysis"]["max_projects_per_run"] = 1
    _shortlist(tmp_path, [_entry(), _entry("acme/two", tier="B")])
    report = analyze.run(cfg, now=NOW, clone_fn=_fake_clone())
    assert report["limit"] == 1
    assert report["analyzed"] == 1 and report["skipped_limit"] == 1


def test_clone_failure_isolated_partial(tmp_path, cfg):
    _shortlist(tmp_path, [_entry(), _entry("acme/two", tier="B")])
    report = analyze.run(cfg, now=NOW, clone_fn=_fake_clone(fail="two"))
    assert report["status"] == "partial"
    assert report["analyzed"] == 1 and len(report["errors"]) == 1
    assert "two" in report["errors"][0]
    assert store.load_project_card("acme/tool", cfg) is not None
    assert store.load_project_card("acme/two", cfg) is None


def test_all_failures_status_failed(tmp_path, cfg):
    _shortlist(tmp_path, [_entry()])
    report = analyze.run(cfg, now=NOW, clone_fn=_fake_clone(fail="tool"))
    assert report["status"] == "failed" and report["analyzed"] == 0


def test_git_missing_marks_errors(tmp_path, cfg, monkeypatch):
    _shortlist(tmp_path, [_entry()])
    monkeypatch.setattr(analyze, "_find_git", lambda: None)
    report = analyze.run(cfg, now=NOW)  # clone_fn=None → 走 git 探测
    assert report["status"] == "failed"
    assert "git" in report["errors"][0]
    assert store.load_project_card("acme/tool", cfg) is None


def test_dry_run_writes_nothing(tmp_path, cfg):
    _shortlist(tmp_path, [_entry()])
    report = analyze.run(cfg, now=NOW, write=False, clone_fn=_fake_clone())
    assert report["analyzed"] == 1
    assert not (tmp_path / "kb").exists()
    assert not (tmp_path / "reports" / TODAY / "analysis.json").exists()


def test_report_written(tmp_path, cfg):
    _shortlist(tmp_path, [_entry()])
    analyze.run(cfg, now=NOW, clone_fn=_fake_clone())
    data = store.read_json(tmp_path / "reports" / TODAY / "analysis.json")
    assert data["status"] == "ok"
    assert data["source"]["date"] == TODAY
    entry = next(e for e in data["entries"] if e["status"] == "ok")
    assert entry["card"].endswith("acme__tool.json")
    assert entry["note"]


def test_stale_shortlist_note(tmp_path, cfg):
    _shortlist(tmp_path, [_entry()], date="2026-10-10")
    report = analyze.run(cfg, now=NOW, clone_fn=_fake_clone())
    assert report["source"]["date"] == "2026-10-10"
    assert any("2026-10-10" in n for n in report["notes"])


def test_missing_shortlist_is_skipped_not_error(tmp_path, cfg):
    report = analyze.run(cfg, now=NOW, clone_fn=_fake_clone())
    assert report["status"] == "skipped" and report["analyzed"] == 0
    assert any("shortlist" in n for n in report["notes"])
    assert (tmp_path / "reports" / TODAY / "analysis.json").exists()


def test_run_refuses_without_never_execute(tmp_path, cfg):
    cfg["analysis"]["never_execute"] = False
    _shortlist(tmp_path, [_entry()])
    with pytest.raises(gconfig.ConfigError):
        analyze.run(cfg, now=NOW, clone_fn=_fake_clone())


# --------------------------------------------------------------------------
# CLI 退出码
# --------------------------------------------------------------------------
def test_main_rc_skipped_without_shortlist(tmp_path, cfg):
    assert analyze.main(["--config", str(GOV_CONFIG)]) == 0


def test_main_rc_failed_on_clone_error(tmp_path, cfg, monkeypatch, capsys):
    _shortlist(tmp_path, [_entry()])

    def boom(url, dest, *, depth=1, timeout=1, git_exe=None):
        raise RuntimeError("模拟不可克隆")

    monkeypatch.setattr(analyze, "_clone_repo", boom)
    rc = analyze.main(["--config", str(GOV_CONFIG), "--print"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "Gov Analyze" in out and "模拟不可克隆" in out


def test_main_rc1_on_missing_explicit_shortlist(tmp_path, cfg):
    rc = analyze.main(["--config", str(GOV_CONFIG),
                       "--shortlist", str(tmp_path / "nope.json")])
    assert rc == 1


def test_main_rc2_bad_config_and_bad_limit(tmp_path):
    assert analyze.main(["--config", str(tmp_path / "nope.yml")]) == 2
    assert analyze.main(["--config", str(GOV_CONFIG), "--limit", "0"]) == 2
