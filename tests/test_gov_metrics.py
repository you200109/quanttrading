"""scripts/gov/metrics.py 单元测试

覆盖三类保证：
1. 纯 Python 度量在合成仓库上产出正确真数据（不依赖真实仓库状态）；
2. 外部工具/凭据缺失时降级为 skipped 而非 failed（这是它能 20 合 1 的前提）；
3. 单度量抛异常被隔离，不影响其余度量采集，且可被 --fail-on-failed 检出。
"""
import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.gov import metrics as gm  # noqa: E402


@pytest.fixture
def fake_repo(tmp_path):
    """最小合成仓库：backend 两个模块 + .github 一个 YAML + 一份文档"""
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "ok.py").write_text(
        '"""有文档字符串的模块"""\n\nx = 1\n', encoding="utf-8")
    (tmp_path / "backend" / "bad.py").write_text(
        'import os\n# TODO: 待补文档字符串\nprint(os.name)\n', encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "ci.yml").write_text("name: CI\non: push\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# t\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text('"""t"""\n' * 1, encoding="utf-8")
    return tmp_path


def _find(report, name):
    return next(m for m in report["metrics"] if m["name"] == name)


# ---------------- 纯 Python 度量：真数据正确性 ----------------
def test_code_stats_counts_real_files(fake_repo):
    res = gm.m_code_stats(fake_repo)
    assert res.status == "ok"
    # backend 2 个 + tests 1 个 = 3
    assert res.data["python_files"] == 3
    assert res.data["test_files"] == 1
    # 有效行：ok.py 2 行 + bad.py 2 行（TODO 注释不计）+ test_x.py 1 行
    assert res.data["python_lines"] == 5


def test_todo_scan_finds_markers(fake_repo):
    res = gm.m_todo_scan(fake_repo)
    assert res.status == "ok"
    assert res.data["total"] == 1
    assert any("bad.py" in f for f, _ in res.data["hot_files"])


def test_header_check_flags_missing_docstring(fake_repo):
    res = gm.m_header_check(fake_repo)
    assert res.status == "ok"
    assert res.data["count"] == 1
    assert any("bad.py" in p for p in res.data["missing_docstring"])
    assert not any("ok.py" in p for p in res.data["missing_docstring"])


def test_docs_existence_reflects_missing(fake_repo):
    res = gm.m_docs_existence(fake_repo)
    assert res.data["present"]["README.md"] is True
    assert res.data["present"]["LICENSE"] is False  # 未创建 -> 应为 False
    assert res.data["all_present"] is False


def test_repo_size_is_positive(fake_repo):
    res = gm.m_repo_size(fake_repo)
    assert res.status == "ok"
    assert res.data["files"] >= 4
    assert res.data["bytes"] > 0


def test_yaml_lint_detects_broken(fake_repo):
    # PyYAML 属治理工具链可选依赖（requirements-gov.txt）：本机没装就明确 skip，
    # 而不是把"缺失降级"误报成失败。CI 会在 test job 显式安装该工具链，
    # 因此这条用例在 CI 上真实执行（见 ci.yml: Install governance toolchain）。
    pytest.importorskip("yaml")
    (fake_repo / ".github" / "bad.yml").write_text("a: [1,\n  b: :\n", encoding="utf-8")
    res = gm.m_yaml_lint(fake_repo)
    assert res.status == "ok"
    assert res.data["count"] == 1
    assert "bad.yml" in res.data["invalid"][0]


def test_yaml_lint_skipped_without_pyyaml(fake_repo, monkeypatch):
    """PyYAML 不在环境里时降级为 skipped 而非 failed（与 m_complexity 同规则）"""
    monkeypatch.setitem(sys.modules, "yaml", None)  # import yaml 将抛 ImportError
    res = gm.m_yaml_lint(fake_repo)
    assert res.status == "skipped"
    assert "PyYAML" in res.note


# ---------------- 外部依赖缺失 -> skipped（不是 failed） ----------------
def test_complexity_skipped_without_radon(fake_repo, monkeypatch):
    monkeypatch.setattr(gm.shutil, "which", lambda _: None)
    res = gm.m_complexity(fake_repo)
    assert res.status == "skipped"
    assert "radon" in res.note


def test_spellcheck_skipped_without_codespell(fake_repo, monkeypatch):
    monkeypatch.setattr(gm.shutil, "which", lambda _: None)
    res = gm.m_spellcheck(fake_repo)
    assert res.status == "skipped"
    assert "codespell" in res.note


def test_github_api_skipped_without_token(fake_repo, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    res = gm.m_github_api(fake_repo)
    assert res.status == "skipped"


# ---------------- 隔离性与整体行为 ----------------
def test_collect_all_isolates_failure(fake_repo, monkeypatch):
    """单度量抛异常 -> 该度量为 failed，其余照常采集，整体不中断"""

    def boom(root):
        raise RuntimeError("模拟采集中炸了")

    # METRICS 是模块级元组（装入的是函数直接引用），因此要整体替换元组，
    # 单独 monkeypatch gm.m_x 不会影响 collect_all 的实际调用目标
    boom.__name__ = "boom_metric"
    monkeypatch.setattr(gm, "METRICS", tuple(gm.METRICS) + (boom,))
    report = gm.collect_all(fake_repo)
    assert _find(report, "boom_metric")["status"] == "failed"
    assert "RuntimeError" in _find(report, "boom_metric")["note"]
    # 其余度量仍产出
    assert _find(report, "code_stats")["status"] == "ok"
    assert report["summary"]["failed"] == 1
    assert report["summary"]["total"] == len(gm.METRICS)


def test_collect_all_shape(fake_repo):
    report = gm.collect_all(fake_repo)
    assert report["schema_version"] == 1
    assert set(report["summary"]) >= {"total", "ok", "skipped", "failed"}
    for m in report["metrics"]:
        assert set(m) == {"name", "status", "data", "note"}
        assert m["status"] in {"ok", "skipped", "failed"}


def test_write_report_produces_valid_json(fake_repo):
    path = gm.write_report(gm.collect_all(fake_repo), fake_repo)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert path.name.startswith("metrics-") and path.suffix == ".json"


def test_cli_main_returns_zero(fake_repo, capsys):
    out = fake_repo / "out.json"
    rc = gm.main(["--root", str(fake_repo), "--out", str(out), "--print"])
    assert rc == 0
    assert out.exists()
    captured = capsys.readouterr()
    assert "=== Gov Metrics ===" in captured.out


def test_cli_fail_on_failed_flag(fake_repo, monkeypatch):
    def boom(root):
        raise RuntimeError("x")

    boom.__name__ = "boom_metric"
    monkeypatch.setattr(gm, "METRICS", (boom,))
    with contextlib.redirect_stderr(io.StringIO()):
        rc = gm.main(["--root", str(fake_repo), "--out", str(fake_repo / "o.json"),
                      "--fail-on-failed"])
    assert rc == 1
