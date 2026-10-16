"""②筛选 scripts/gov/score.py 单元测试

全部离线（本模块设计上不发任何 API 请求）。重点：
七维公式边界值、权重归一、A/B/C 分档线、白/黑名单、star 趋势历史差分、
"数据不足记中性并留痕"的诚实性、产物落盘、CLI 三退出码。
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
from scripts.gov import schemas  # noqa: E402
from scripts.gov import score  # noqa: E402
from scripts.gov import store  # noqa: E402

GOV_CONFIG = REPO_ROOT / "scripts" / "gov" / "config.yml"
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)


def _cand(name="owner/repo", stars=1000, *, pushed="2026-10-15T00:00:00Z", open_issues=5,
          language="Python", license_id="MIT", forks=50, archived=False, topics=("quant",)):
    return schemas.new_record(
        "candidate",
        full_name=name,
        url=f"https://github.com/{name}",
        domain="quant",
        keyword="quantitative trading",
        stars=stars,
        forks=forks,
        open_issues=open_issues,
        language=language,
        license=license_id,
        topics=list(topics),
        pushed_at=pushed,
        archived=archived,
        discovered_at=NOW.isoformat(),
    )


def _strong(name="good/strong"):
    return _cand(name, stars=10000, pushed="2026-10-15T00:00:00Z", open_issues=1, forks=500)


def _mid(name="ok/mid"):
    return _cand(name, stars=1200, pushed="2026-08-17T00:00:00Z", open_issues=30,
                 language="TypeScript", license_id="Apache-2.0", forks=50)


def _weak(name="weak/low"):
    return _cand(name, stars=210, pushed="2025-12-20T00:00:00Z", open_issues=100,
                 language="Go", license_id="", forks=10)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    base = gconfig.load_config(GOV_CONFIG)
    base["knowledge"]["root"] = "kb"
    base["scoring"]["blacklist"] = []
    base["scoring"]["whitelist"] = []
    monkeypatch.setattr(store, "REPORTS_DIR", tmp_path / "reports")
    return base


# ---------------------------------------------------------------- 基础工具

def test_days_since_handles_formats_and_bad_input():
    assert score._days_since("2026-10-15T00:00:00Z", NOW) == pytest.approx(1.125)
    assert score._days_since("2026-10-15T00:00:00", NOW) == pytest.approx(1.125)   # 无时区按 UTC
    assert score._days_since("not-a-date", NOW) is None
    assert score._days_since("", NOW) is None
    assert score._days_since("2026-10-17T00:00:00Z", NOW) == pytest.approx(0.0)  # 未来钳到 0


def test_commit_freshness_boundaries():
    assert score._score_commit_freshness(0) == 100.0
    assert score._score_commit_freshness(7) == 100.0
    assert score._score_commit_freshness(186) == pytest.approx(50.0)
    assert score._score_commit_freshness(364) == pytest.approx(100 * 1 / 358, abs=0.01)
    assert score._score_commit_freshness(365) == 0.0
    assert score._score_commit_freshness(999) == 0.0


# ---------------------------------------------------------------- 七维公式

def test_star_trend_log_scale():
    assert score._score_star_trend(100_000)[0] == 100.0
    assert score._score_star_trend(1000)[0] == pytest.approx(33.333, abs=0.01)
    assert score._score_star_trend(200)[0] == pytest.approx(10.034, abs=0.01)
    assert score._score_star_trend(1)[0] == 0.0
    assert score._score_star_trend(0)[0] == 0.0
    assert "冷启动" in score._score_star_trend(1000)[1]


def test_star_trend_with_history_diff():
    pts, note = score._score_star_trend(1000, prev_stars=800)
    assert pts == pytest.approx(53.333, abs=0.01)      # 33.33 + 20（封顶）
    assert "趋势" in note and "800" in note
    down, note2 = score._score_star_trend(1000, prev_stars=2000)
    assert down == pytest.approx(13.333, abs=0.01)     # 33.33 - 20（封顶）
    assert "趋势" in note2
    same = score._score_star_trend(1000, prev_stars=1000)[0]
    assert same == pytest.approx(33.333, abs=0.01)     # 差分 0，不偏倚


def test_issue_response_density_proxy():
    assert score._score_issue_response(0, 1000) == 100.0
    assert score._score_issue_response(1, 10000) == 100.0
    assert score._score_issue_response(10, 1000) == pytest.approx(97.436, abs=0.01)
    assert score._score_issue_response(50, 1000) == pytest.approx(76.923, abs=0.01)
    assert score._score_issue_response(200, 1000) == 0.0   # 密度恰为上限
    assert score._score_issue_response(999, 1000) == 0.0   # 超限钳 0
    assert score._score_issue_response(0, 0) == 100.0      # 无 star 视密度 0（保守不惩罚）


def test_license_tiers():
    assert score._score_license("MIT") == 100.0
    assert score._score_license("Apache-2.0") == 100.0
    assert score._score_license("MPL-2.0") == 70.0
    assert score._score_license("GPL-3.0") == 30.0
    assert score._score_license("AGPL-3.0") == 30.0
    assert score._score_license("") == 20.0
    assert score._score_license("NOASSERTION") == 20.0
    assert score._score_license(None) == 20.0
    assert score._score_license("WTFPL") == 40.0           # 罕见 SPDX：保守未知


def test_language_fit_tiers():
    assert score._score_language_fit("Python") == 100.0
    assert score._score_language_fit("Jupyter Notebook") == 90.0
    assert score._score_language_fit("Rust") == 60.0
    assert score._score_language_fit("TypeScript") == 50.0
    assert score._score_language_fit("HTML") == 40.0
    assert score._score_language_fit("") == 40.0
    assert score._score_language_fit("COBOL") == 30.0


def test_maintenance_signals():
    assert score._score_maintenance(True, 1, 500) == 0.0     # 归档一票否决
    assert score._score_maintenance(False, 1, 0) == 80.0     # 90 天内
    assert score._score_maintenance(False, 1, 100) == 100.0  # 活跃 + 规模
    assert score._score_maintenance(False, 123, 0) == 60.0   # 180 天内
    assert score._score_maintenance(False, 200, 0) == 40.0   # 365 天内
    assert score._score_maintenance(False, 400, 0) == 20.0   # 长尾
    assert score._score_maintenance(False, None, 0) == 20.0  # 无 pushed_at：显式低分
    assert score._score_maintenance(False, 400, 100) == 40.0


# ---------------------------------------------------------------- 组合评分

def test_score_candidate_breakdown_and_notes(cfg):
    entry = score.score_candidate(_strong(), cfg, now=NOW)
    assert entry["tier"] == "A"
    assert entry["score"] > 75
    assert set(entry["score_breakdown"]) == set(score.DIMENSIONS)
    assert entry["score_breakdown"]["dependency_health"] == 50.0
    assert entry["full_name"] == "good/strong"          # candidate 字段完整保留
    assert any("冷启动" in n for n in entry["notes"])    # 诚实留痕
    schemas.validate("candidate", {k: v for k, v in entry.items()
                                   if k in schemas.CANDIDATE})  # 原字段仍合契约


def test_score_candidate_tier_fixtures(cfg):
    assert score.score_candidate(_strong(), cfg, now=NOW)["tier"] == "A"
    assert score.score_candidate(_mid(), cfg, now=NOW)["tier"] == "B"
    assert score.score_candidate(_weak(), cfg, now=NOW)["tier"] == "C"


def test_assign_tier_thresholds():
    tiers = {"A": 75, "B": 55, "C": 0}
    assert score.assign_tier(80, tiers) == "A"
    assert score.assign_tier(75, tiers) == "A"           # 边界含
    assert score.assign_tier(74.99, tiers) == "B"
    assert score.assign_tier(55, tiers) == "B"
    assert score.assign_tier(54.99, tiers) == "C"
    assert score.assign_tier(0, tiers) == "C"


def test_weights_normalization_equal_scores(cfg):
    import copy
    cfg2 = copy.deepcopy(cfg)
    cfg2["scoring"]["weights"] = {k: v * 3 for k, v in cfg["scoring"]["weights"].items()}
    a = score.score_candidate(_mid(), cfg, now=NOW)
    b = score.score_candidate(_mid(), cfg2, now=NOW)
    assert a["score"] == pytest.approx(b["score"])       # 权重按 sum 归一，等比缩放不变


def test_unknown_weight_dimension_raises(cfg):
    cfg["scoring"]["weights"]["bogus"] = 1
    with pytest.raises(ValueError, match="bogus"):
        score.score_candidate(_strong(), cfg, now=NOW)


# ---------------------------------------------------------------- run() 集成

def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_run_whitelist_bypass_and_blacklist_exclusion(cfg):
    cfg["scoring"]["whitelist"] = ["weak/x"]
    cfg["scoring"]["blacklist"] = ["bad/x"]
    report = score.run(
        cfg,
        candidates=[_weak("weak/x"), _cand("bad/x"), _strong("good/x")],
        prev_stars={},
        now=NOW,
        write=False,
    )
    assert report["excluded_blacklist"] == 1
    assert report["whitelisted"] == 1
    names = [e["full_name"] for e in report["entries"]]
    assert names == ["good/x", "weak/x"]                 # A 层内按分数降序，黑名单不出现
    weak = next(e for e in report["entries"] if e["full_name"] == "weak/x")
    assert weak["tier"] == "A"                           # 直通不参与分层
    assert any("whitelist" in n for n in weak["notes"])
    assert report["tier_counts"] == {"A": 2, "B": 0, "C": 0}


def test_run_invalid_candidate_is_partial_not_silent(cfg):
    report = score.run(cfg, candidates=[{"full_name": "x/y"}], prev_stars={}, now=NOW, write=False)
    assert report["status"] == "partial"
    assert report["invalid_candidates"] == 1
    assert report["entries"] == []
    assert report["errors"] and "契约不符" in report["errors"][0]


def test_run_notes_document_proxy_dimensions(cfg):
    report = score.run(cfg, candidates=[_strong()], prev_stars={}, now=NOW, write=False)
    joined = " ".join(report["notes"])
    assert "代理指标" in joined
    assert "中性 50" in joined


def test_run_prev_stars_diff_from_previous_shortlist(cfg):
    _write_json(store.REPORTS_DIR / "2026-10-15" / "shortlist.json",
                {"entries": [{"full_name": "good/strong", "stars": 800}]})
    report = score.run(cfg, candidates=[_cand("good/strong", stars=1000)], now=NOW, write=False)
    entry = report["entries"][0]
    assert entry["score_breakdown"]["star_trend"] == pytest.approx(53.33, abs=0.01)
    assert any("趋势" in n for n in entry["notes"])
    assert any("差分已启用" in n for n in report["notes"])


def test_run_uses_latest_discovery(cfg):
    _write_json(store.REPORTS_DIR / "2026-10-15" / "discovery.json",
                {"candidates": [_weak("weak/low")]})
    _write_json(store.REPORTS_DIR / "2026-10-16" / "discovery.json",
                {"candidates": [_strong("good/strong")]})
    report = score.run(cfg, now=NOW, write=False)
    assert report["source"]["kind"] == "latest"
    assert "2026-10-16" in report["source"]["path"].replace("\\", "/")
    assert [e["full_name"] for e in report["entries"]] == ["good/strong"]


def test_run_persists_shortlist_artifact(cfg):
    score.run(cfg, candidates=[_strong()], prev_stars={}, now=NOW, write=True)
    f = store.REPORTS_DIR / "2026-10-16" / "shortlist.json"
    assert f.exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["status"] == "ok"
    assert data["tier_counts"]["A"] == 1
    assert data["entries"][0]["tier"] == "A"


def test_run_without_any_source_is_failed(cfg):
    report = score.run(cfg, now=NOW, write=False)
    assert report["status"] == "failed"
    assert report["count"] == 0
    assert report["errors"]


def test_run_explicit_missing_input_raises(cfg):
    with pytest.raises(FileNotFoundError, match="不存在"):
        score.run(cfg, input_path=str(store.REPORTS_DIR / "nope" / "discovery.json"))


# ---------------------------------------------------------------- CLI

def test_cli_dry_run_prints_and_writes_nothing(cfg, capsys):
    src = store.REPORTS_DIR / "2026-10-16" / "discovery.json"
    _write_json(src, {"candidates": [_strong("good/strong")]})
    rc = score.main(["--input", str(src), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "=== Gov Shortlist ===" in out
    assert "good/strong" in out
    assert not (store.REPORTS_DIR / "2026-10-16" / "shortlist.json").exists()


def test_cli_missing_input_exit_1(cfg, capsys):
    rc = score.main(["--input", str(store.REPORTS_DIR / "ghost.json")])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_cli_corrupt_input_exit_1(cfg, capsys):
    bad = store.REPORTS_DIR / "2026-10-16" / "discovery.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not json", encoding="utf-8")
    rc = score.main(["--input", str(bad)])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_cli_no_source_exit_1(cfg):
    assert score.main([]) == 1


def test_cli_bad_config_exit_2(tmp_path):
    rc = score.main(["--config", str(tmp_path / "missing.yml"), "--dry-run"])
    assert rc == 2
