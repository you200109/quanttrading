"""治理核心层（config / schemas / store / http）单元测试

四条防线：
1. 配置写错必须**报出字段名**，不能静默取默认值（labeler.yml 的前车之鉴）；
2. 契约写脏数据必须拒绝落盘——脏的记忆会污染之后每一轮演进决策；
3. 知识库读写要能在临时目录里完整往返（不依赖真实仓库状态）；
4. HTTP 层区分"可重试"与"不可重试"，且无凭据时显式抛出而非假装成功。

全部离线：`github_api._urlopen` 被替换为假实现，`_SLEEP` 替换为即时返回。
"""
import io
import json
import sys
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.gov import config as gc  # noqa: E402
from scripts.gov import github_api as gh  # noqa: E402
from scripts.gov import schemas as gs  # noqa: E402
from scripts.gov import store as gstore  # noqa: E402

GOV_CONFIG = REPO_ROOT / "scripts" / "gov" / "config.yml"


# ==========================================================================
# config
# ==========================================================================
def test_default_config_is_valid():
    cfg = gc.load_config(GOV_CONFIG)
    assert gc.validate(cfg) == []
    assert cfg["schema_version"] == 1


def test_missing_file_names_the_path(tmp_path):
    with pytest.raises(gc.ConfigError, match="配置文件不存在"):
        gc.load_config(tmp_path / "nope.yml")


def test_missing_block_names_the_field(tmp_path):
    cfg = gc.load_config(GOV_CONFIG)
    cfg.pop("scoring")
    path = tmp_path / "c.yml"
    _dump_yaml(path, cfg)
    with pytest.raises(gc.ConfigError) as exc:
        gc.load_config(path)
    assert "scoring" in str(exc.value)
    assert "缺失" in str(exc.value)


def test_wrong_type_reports_expected_and_actual(tmp_path):
    cfg = gc.load_config(GOV_CONFIG)
    cfg["discovery"]["filters"]["min_stars"] = "200"
    path = tmp_path / "c.yml"
    _dump_yaml(path, cfg)
    problems = gc.validate(gc.load_config(path, strict=False))
    assert any("discovery.filters.min_stars" in p and "期望 int" in p for p in problems)


def test_bool_is_not_accepted_as_int(tmp_path):
    cfg = gc.load_config(GOV_CONFIG)
    cfg["discovery"]["per_keyword_limit"] = True
    path = tmp_path / "c.yml"
    _dump_yaml(path, cfg)
    problems = gc.validate(gc.load_config(path, strict=False))
    assert any("per_keyword_limit" in p for p in problems)


def test_never_execute_false_is_rejected(tmp_path):
    cfg = gc.load_config(GOV_CONFIG)
    cfg["analysis"]["never_execute"] = False
    path = tmp_path / "c.yml"
    _dump_yaml(path, cfg)
    problems = gc.validate(gc.load_config(path, strict=False))
    assert any("never_execute" in p for p in problems)


def test_unsupported_schema_version(tmp_path):
    cfg = gc.load_config(GOV_CONFIG)
    cfg["schema_version"] = 99
    path = tmp_path / "c.yml"
    _dump_yaml(path, cfg)
    problems = gc.validate(gc.load_config(path, strict=False))
    assert any("schema_version" in p for p in problems)


def test_watched_item_needs_repo_and_kind(tmp_path):
    cfg = gc.load_config(GOV_CONFIG)
    cfg["monitoring"]["watched"] = [{"repo": "o/r", "kind": "nope"}, {"kind": "release"}]
    path = tmp_path / "c.yml"
    _dump_yaml(path, cfg)
    problems = gc.validate(gc.load_config(path, strict=False))
    assert any("kind" in p for p in problems)
    assert any("watched[1]" in p for p in problems)


def test_get_dotted_path_and_default():
    cfg = gc.load_config(GOV_CONFIG)
    assert gc.get(cfg, "monitoring.alerts.coverage_floor") == 40
    assert gc.get(cfg, "monitoring.alerts.nope", "fallback") == "fallback"
    assert gc.get(cfg, "a.b.c") is None


def test_summary_mentions_domains_and_ok():
    cfg = gc.load_config(GOV_CONFIG)
    text = gc.summary(cfg)
    assert "config      : OK" in text
    assert "quant" in text


def test_cli_exit_codes(tmp_path, capsys):
    assert gc.main(["--config", str(GOV_CONFIG)]) == 0
    bad = tmp_path / "bad.yml"
    _dump_yaml(bad, {"schema_version": 1})
    assert gc.main(["--config", str(bad), "--no-strict"]) == 0   # 显式放宽才放行
    assert gc.main(["--config", str(bad)]) == 1
    assert gc.main(["--config", str(tmp_path / "missing.yml")]) == 2


# ==========================================================================
# schemas
# ==========================================================================
def test_new_record_fills_defaults_and_isolates_mutables():
    a = gs.new_record("candidate", full_name="o/r", url="https://x", domain="quant",
                      keyword="k", stars=1)
    b = gs.new_record("candidate", full_name="o/r2", url="https://y", domain="quant",
                      keyword="k", stars=2)
    assert a["topics"] == [] and a["forks"] == 0
    a["topics"].append("mutated")
    assert b["topics"] == []           # 共享可变默认值会把两张卡串起来
    card = gs.new_record("project_card", name="o/r", url="https://x", domain="quant",
                         status="discovered")
    assert card["quality"] == {}       # dict 工厂必须产出实例而不是 dict 这个类
    card["deps"].append("pandas")
    card2 = gs.new_record("project_card", name="o/r2", url="https://y", domain="quant",
                          status="discovered")
    assert card2["deps"] == []


def test_missing_required_fields_reported_all_at_once():
    problems = gs.problems("project_card", {"name": "o/r"})
    joined = " ".join(problems)
    for field in ("url", "domain", "status"):
        assert field in joined


def test_unknown_field_reported():
    # 未知字段要能被 problems() 报出来（new_record 会直接抛，故这里手工构造）
    record = gs.new_record("candidate", full_name="o/r", url="u", domain="d", keyword="k",
                           stars=1)
    record["surprise"] = 1
    problems = gs.problems("candidate", record)
    assert gs.KINDS                     # 四类契约齐备
    assert any("未知字段" in p and "surprise" in p for p in problems)
    with pytest.raises(gs.SchemaError, match="未知字段"):
        gs.new_record("candidate", full_name="o/r", url="u", domain="d", keyword="k",
                      stars=1, surprise=1)


def test_enum_violation():
    problems = gs.problems("project_card", {"name": "o/r", "url": "u", "domain": "d",
                                            "status": "maybe"})
    assert any("status" in p and "允许取值" in p for p in problems)


def test_full_name_pattern_enforced():
    problems = gs.problems("candidate", {"full_name": "noslash", "url": "u", "domain": "d",
                                         "keyword": "k", "stars": 1})
    assert any("full_name" in p for p in problems)


def test_float_field_rejects_bool_but_accepts_int():
    rec = gs.new_record("metric_record", date="2026-01-01", coverage=40)
    assert rec["coverage"] == 40
    problems = gs.problems("metric_record", {"date": "d", "coverage": True})
    assert any("coverage" in p for p in problems)


def test_validate_raises_schema_error():
    with pytest.raises(gs.SchemaError, match="契约校验失败"):
        gs.validate("decision_record", {})


def test_is_version_recognizes_common_tags():
    assert gs.is_version("v1.2.3") and gs.is_version("1.2") and gs.is_version("20260101")
    assert not gs.is_version("release-candidate")


# ==========================================================================
# store
# ==========================================================================
@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """把 reports/ 与知识库根都重定向到 tmp_path"""
    monkeypatch.setattr(gstore, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gstore, "REPORTS_DIR", tmp_path / "reports")
    cfg = {"knowledge": {"root": "kb", "decisions_file": "decisions.jsonl"}}
    return tmp_path, cfg


def test_write_json_creates_dated_path(tmp_repo):
    tmp, _ = tmp_repo
    path = gstore.write_json({"a": 1}, "sub", "x.json", date="2026-01-02")
    assert path == tmp / "reports" / "2026-01-02" / "sub" / "x.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


def test_write_json_refuses_dirty_record(tmp_repo):
    tmp, _ = tmp_repo
    with pytest.raises(gs.SchemaError):
        gstore.write_json({"name": "o/r"}, "bad.json", date="2026-01-02",
                          validate_as="project_card")
    assert not (tmp / "reports" / "2026-01-02" / "bad.json").exists()


def test_knowledge_card_roundtrip(tmp_repo):
    _tmp, cfg = tmp_repo
    card = gs.new_record("project_card", name="acme/tool", url="https://x", domain="quant",
                         status="discovered", score=81.5, tier="A")
    gstore.save_project_card(card, cfg)
    assert gstore.load_project_card("acme/tool", cfg)["tier"] == "A"
    assert set(gstore.list_project_cards(cfg)) == {"acme/tool"}


def test_knowledge_rejects_invalid_card(tmp_repo):
    _tmp, cfg = tmp_repo
    with pytest.raises(gs.SchemaError):
        gstore.save_project_card({"name": "acme/tool"}, cfg)


def test_list_skips_corrupt_card_but_keeps_good(tmp_repo):
    _tmp, cfg = tmp_repo
    good = gs.new_record("project_card", name="o/good", url="u", domain="d", status="analyzed")
    gstore.save_project_card(good, cfg)
    (gstore.projects_dir(cfg) / "o__broken.json").write_text("{not json", encoding="utf-8")
    cards = gstore.list_project_cards(cfg)
    assert set(cards) == {"o/good"}


def test_decisions_are_append_only_and_limitable(tmp_repo):
    _tmp, cfg = tmp_repo
    for i in range(3):
        gstore.append_decision(gs.new_record(
            "decision_record", ts=f"2026-01-0{i + 1}T00:00:00", proposal=f"p{i}",
            evidence=["e"], action="open-pr"), cfg)
    rows = gstore.read_decisions(cfg, limit=2)
    assert [r["proposal"] for r in rows] == ["p1", "p2"]
    # 单行损坏不影响其余历史可读
    with gstore.decisions_path(cfg).open("a", encoding="utf-8") as fh:
        fh.write("{broken\n")
    assert len(gstore.read_decisions(cfg)) == 3


def test_read_decisions_missing_file_is_empty(tmp_repo):
    _tmp, cfg = tmp_repo
    assert gstore.read_decisions(cfg) == []


def test_card_filename_guard():
    assert gstore.card_filename("acme/tool") == "acme__tool.json"
    for bad in ("noslash", "a/", "/b"):
        with pytest.raises(ValueError):
            gstore.card_filename(bad)


# ==========================================================================
# http
# ==========================================================================
class _FakeResponse:
    def __init__(self, payload, headers=None, status=200):
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code, headers=None, body=b'{"message":"boom"}'):
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = str(v)
    return urllib.error.HTTPError("https://api.github.com/x", code, "err", msg,
                                  io.BytesIO(body))


@pytest.fixture
def no_sleep(monkeypatch):
    calls = []
    monkeypatch.setattr(gh, "_SLEEP", lambda seconds: calls.append(seconds))
    return calls


def test_token_missing_raises():
    with pytest.raises(gh.NoCredentials):
        gh.token_from_env({})


def test_token_prefers_github_token_and_strips():
    assert gh.token_from_env({"GITHUB_TOKEN": "  abc  ", "GH_TOKEN": "def"}) == "abc"
    assert gh.token_from_env({"GH_TOKEN": "def"}) == "def"


def test_request_returns_payload_and_quota_meta(monkeypatch):
    seen = {}

    def fake(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return _FakeResponse({"items": [1]}, {"x-ratelimit-remaining": "41",
                                              "x-ratelimit-reset": "1700000000"})

    monkeypatch.setattr(gh, "_urlopen", fake)
    payload, meta = gh.request("/search/repositories", {"q": "quant"}, token="t")
    assert payload == {"items": [1]}
    assert meta["status"] == 200
    assert meta["rate_remaining"] == 41
    assert meta["rate_reset"] == 1700000000
    assert seen["url"].endswith("/search/repositories?q=quant")
    assert seen["auth"] == "Bearer t"


def test_retry_on_500_then_success(monkeypatch, no_sleep):
    state = {"n": 0}

    def fake(req, timeout):
        state["n"] += 1
        if state["n"] == 1:
            raise _http_error(500)
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(gh, "_urlopen", fake)
    payload, meta = gh.request("/x", token="t", retries=2)
    assert payload == {"ok": True} and meta["status"] == 200
    assert state["n"] == 2 and no_sleep  # 确实退避过，而不是立刻重试


def test_429_honors_retry_after(monkeypatch, no_sleep):
    state = {"n": 0}

    def fake(req, timeout):
        state["n"] += 1
        if state["n"] == 1:
            raise _http_error(429, {"retry-after": "3"})
        return _FakeResponse({"ok": 1})

    monkeypatch.setattr(gh, "_urlopen", fake)
    gh.request("/x", token="t", retries=2)
    assert 3 in no_sleep


def test_404_is_not_retried(monkeypatch, no_sleep):
    calls = []

    def fake(req, timeout):
        calls.append(1)
        raise _http_error(404, body=b'{"message":"Not Found"}')

    monkeypatch.setattr(gh, "_urlopen", fake)
    with pytest.raises(gh.GitHubError) as exc:
        gh.request("/x", token="t", retries=3)
    assert exc.value.status == 404
    assert len(calls) == 1          # 4xx 不该浪费配额重试
    assert not no_sleep


def test_403_rate_limit_message_has_reset_hint(monkeypatch):
    def fake(req, timeout):
        raise _http_error(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"})

    monkeypatch.setattr(gh, "_urlopen", fake)
    with pytest.raises(gh.GitHubError) as exc:
        gh.request("/x", token="t", retries=1)
    assert exc.value.status == 403
    assert "配额耗尽" in str(exc.value) and "1700000000" in str(exc.value)


def test_network_error_exhausts_retries_then_raises(monkeypatch):
    calls = []

    def fake(req, timeout):
        calls.append(1)
        raise TimeoutError("boom")

    monkeypatch.setattr(gh, "_urlopen", fake)
    with pytest.raises(gh.GitHubError, match="网络请求失败"):
        gh.request("/x", token="t", retries=2)
    assert len(calls) == 3          # 首试 + 2 次重试


def test_rate_limit_parses_buckets(monkeypatch):
    payload = {"resources": {
        "core": {"limit": 5000, "remaining": 4990, "reset": 1},
        "search": {"limit": 30, "remaining": 12, "reset": 2},
    }}
    monkeypatch.setattr(gh, "_urlopen", lambda req, timeout: _FakeResponse(payload))
    out = gh.rate_limit(token="t")
    assert out["search"]["remaining"] == 12
    assert out["core"]["limit"] == 5000


# --------------------------------------------------------------------------
def _dump_yaml(path: Path, obj: dict) -> None:
    pytest.importorskip("yaml")
    import yaml
    path.write_text(yaml.safe_dump(obj, allow_unicode=True), encoding="utf-8")
