"""③监控：watched releases 跟踪 + 自身依赖健康 + 阈值告警（Issue 落地）

定位（docs/governance-architecture.md ③）：对 config.monitoring.watched 的上游项目
和知识库里 analyzed/approved/integrated 的项目卡做持续跟踪——新 release、自身
requirements 的 outdated 状况、自身 CI 成功率与时长；发现的告警**真的落地成
GitHub Issue**（这正是旧 mon-* 十份 echo 桩从来没做到的事）。

边界与取舍：
- **跨运行记忆在知识库**（knowledge/monitor_state.json，随仓库版本化）：
  差分依赖上一轮的真值，`reports/` 会被 gitignore，担不起这个职责。
  首次看到只记基线不告警；`alerted_tag` 仅在告警**成功落地**（新建/命中已有/
  追加评论）后前进——创建失败（如缺 issues:write）不会把告警悄悄吞掉，
  下一轮会自动重试；
- **告警去重与防洪**：先按标题里的事件指纹去重（已开的同标题 issue 不重复建），
  开放告警数达 config.monitoring.alerts.max_open_alerts 后不再新建，只把新告警
  作为评论追加到最近一条告警 issue；
- **Issue 归属用标题前缀过滤而不是 label**：label 在仓库里不存在时 GitHub 会
  静默丢弃（issue 建了却没有标签），把防洪的正确性押在 label 上等于把堤坝建
  在流沙上；label 只是给人看的，逻辑上以标题为准；
- **PyPI 请求不走 github_api**：那是 GitHub 令牌的注入点，绝不能把
  Authorization 头带出给第三方域名；此处用裸 urllib（`_urlopen` 可注入，离线测试）；
- **依赖检查的诚实分类**：`==` 锁定与 PyPI 最新不同 → outdated；
  范围约束（如 pandas>=2.3.3,<3.0）且最新版越出上界 → held（按既定策略持有，
  不算 outdated、不催升级）；锁定版本高于 PyPI 最新 → ahead（疑 yanked，人工复核）；
  解析不了的一律 unknown，绝不猜；
- **显式留白的部分**：CVE 扫描未实装（需要 OSV/pip-audit 通道，见 P8 规划）；
  覆盖率无数据源（ci.yml 用 --cov-fail-under 直接拦，未产出可读文件）——
  两者都在产物里给出 status="skipped" 及原因，不假装有数；
- **Secret 卫生纳入监控**：每轮静态扫描 `.git/config` 与 `.github/workflows/*.yml`
  是否出现明文 GitHub 令牌前缀（ghp_/github_pat_/gho_/ghs_）——命中即为 error，
  这是审计 §8.3「工作流明文引用」遗留项在监控层的收口（只读文本、不外发）。

用法（-m 运行：脚本 import 了 scripts.gov 包）：
    python -m scripts.gov.monitor --dry-run --print    # 只算不写、不建 Issue
    python -m scripts.gov.monitor --print              # 落盘报告 + 状态
    python -m scripts.gov.monitor --create-issues      # 另建/追加告警 Issue
    python -m scripts.gov.monitor --deps-issue --create-issues   # 月度依赖健康报告
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scripts.gov import config as gconfig
from scripts.gov import github_api as gh
from scripts.gov import schemas
from scripts.gov import store

STATE_FILENAME = "monitor_state.json"
ALERT_LABEL = "gov-alert"
ALERT_TITLE_PREFIX = "[gov-alert]"
DEPS_TITLE_PREFIX = "[gov-deps]"
METRICS_SUBDIR = "metrics"

# 项目卡进入监控的状态：评分策略注释明确 A/B 进监控；integrated 是已在用，更应跟踪上游
CARD_MONITOR_STATUSES = ("analyzed", "approved", "integrated")

COMMITTED_OUTCOMES = ("created", "duplicate_open", "appended")

PYPI_URL = "https://pypi.org/pypi/{name}/json"
PYPI_TIMEOUT = 15

SELF_CI_SAMPLE = 20
SELF_CI_BRANCH = "main"

_urlopen = urllib.request.urlopen  # PyPI 侧唯一网络出口，测试替换这一个即可离线

_VER_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")
_CLAUSE_RE = re.compile(r"(==|>=|<=|~=|<|>)\s*([0-9A-Za-z.!+_-]+)")
_REQ_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(.*)$")


class _Budget:
    """GitHub API 请求预算：检查阶段受 gate，告警落地阶段只计数不拦"""

    def __init__(self, total: int):
        self.total = max(0, int(total))
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.total:
            return False
        self.used += 1
        return True

    def spend(self) -> None:
        self.used += 1

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.used)


# --------------------------------------------------------------------------
# 版本工具（依赖检查用；纯函数，边界全部可测）
# --------------------------------------------------------------------------
def _ver_tuple(raw: str | None) -> tuple[int, int, int] | None:
    """版本号 → (major, minor, patch)；无法解析返回 None（绝不猜）"""
    m = _VER_RE.match((raw or "").strip().lower())
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())  # type: ignore[return-value]


def _bump_kind(current: str, latest: str) -> str:
    """current → latest 的升级级别：major/minor/patch/same/unknown"""
    a, b = _ver_tuple(current), _ver_tuple(latest)
    if a is None or b is None:
        return "unknown"
    for i, label in enumerate(("major", "minor", "patch")):
        if a[i] != b[i]:
            return label
    return "same"


def _parse_clauses(spec: str) -> list[tuple[str, str]]:
    return [(op, ver) for op, ver in _CLAUSE_RE.findall(spec or "")]


def _clause_holds(latest: str, op: str, ver: str) -> bool | None:
    """latest 是否满足 op ver；None = 版本不可比（调用方按 unknown 处理）"""
    if op == "==":
        return (latest or "").strip().lower().lstrip("v") == ver.strip().lower().lstrip("v")
    a, b = _ver_tuple(latest), _ver_tuple(ver)
    if a is None or b is None:
        return None
    if op in (">=", "~="):
        return a >= b
    if op == "<=":
        return a <= b
    if op == "<":
        return a < b
    if op == ">":
        return a > b
    return None


def _classify_pin(spec: str, latest: str) -> tuple[str, str]:
    """按约束分类：(status, detail)

    ok           全部约束满足
    outdated     floor 类约束不满足（最新已超出下限）→ detail 为升级级别
    held         仅上界（< / <=）不满足 → 按既定策略持有，不进升级清单
    ahead        锁定高于 PyPI 最新（疑似 yanked/预发布）→ 人工复核
    unknown      约束解析失败/版本不可比/上下界同时不满足
    """
    clauses = _parse_clauses(spec)
    if not clauses:
        return "unknown", f"无法解析版本约束 {spec!r}"
    floor_fail: list[tuple[str, str]] = []
    cap_fail: list[tuple[str, str]] = []
    for op, ver in clauses:
        holds = _clause_holds(latest, op, ver)
        if holds is None:
            return "unknown", f"版本不可比（{spec} vs {latest}）"
        if holds:
            continue
        if op in ("<", "<="):
            cap_fail.append((op, ver))
        else:
            floor_fail.append((op, ver))
    if not floor_fail and not cap_fail:
        return "ok", ""
    if cap_fail and not floor_fail:
        ops = "/".join(f"{op}{ver}" for op, ver in cap_fail)
        return "held", f"最新 {latest} 越出上界 {ops}（按既定策略持有）"
    if floor_fail and not cap_fail:
        _op, ver = floor_fail[0]
        lt, base = _ver_tuple(latest), _ver_tuple(ver)
        if lt is not None and base is not None and lt < base:
            return "ahead", f"下限 {ver} 高于 PyPI 最新 {latest}（疑 yanked/预发布/索引滞后），人工复核"
        return "outdated", _bump_kind(ver, latest)
    return "unknown", f"约束矛盾（上下界同时不满足：{spec} vs {latest}）"


def parse_requirements(text: str) -> list[dict]:
    """requirements 文本 → [{name, spec, raw}]；注释/空行/选项行（- 开头）跳过"""
    out: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        if ";" in line:  # 环境标记治理 v1 不评估，剥掉后再解析
            line = line.split(";", 1)[0].strip()
        m = _REQ_RE.match(line)
        if not m:
            out.append({"name": "", "spec": "", "raw": raw.strip(), "unparsed": True})
            continue
        out.append({"name": m.group(1), "spec": m.group(2).strip(), "raw": raw.strip()})
    return out


def _pypi_latest(name: str, *, timeout: int = PYPI_TIMEOUT) -> str:
    """PyPI JSON API 取最新版本号（故意不走 github_api——那里会注入 GitHub 令牌）"""
    req = urllib.request.Request(
        PYPI_URL.format(name=name),
        headers={"User-Agent": gh.USER_AGENT, "Accept": "application/json"},
    )
    with _urlopen(req, timeout=timeout) as resp:  # 必须关键字：urlopen 第二位是 data
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    return ((payload or {}).get("info") or {}).get("version") or ""


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------------
# ① watched：release/version 跟踪
# --------------------------------------------------------------------------
def check_watched(items: list[dict], *, token: str | None, budget: _Budget,
                  state: dict, now: datetime) -> list[dict]:
    """逐项查询最新 release/tag。

    items: [{"repo", "kind", "source", "prev_fallback"}]
    item 产出: {repo, kind, source, status, prev_tag, alerted_tag, checked_at, ...}
    status: ok / no_release(404) / error / skipped_budget
    """
    out: list[dict] = []
    watched_state = state.get("watched") or {}
    for item in items:
        repo = item.get("repo", "")
        kind = item.get("kind", "release")
        base = {
            "repo": repo,
            "kind": kind,
            "source": item.get("source", "config"),
            "checked_at": now.isoformat(),
        }
        if not repo:
            out.append({**base, "status": "error", "error": "repo 为空"})
            continue
        prev = watched_state.get(repo) or {}
        base["prev_tag"] = prev.get("last_seen_tag") or item.get("prev_fallback", "")
        base["alerted_tag"] = prev.get("alerted_tag", "")
        if not budget.take():
            out.append({**base, "status": "skipped_budget"})
            continue
        try:
            if kind == "tag":
                # tags 接口顺序无官方保证，仅作 release 缺失时的兜底
                payload, _meta = gh.request(f"/repos/{repo}/tags", {"per_page": 1}, token=token)
                first = payload[0] if isinstance(payload, list) and payload else {}
                tag = first.get("name", "")
                published_at, html_url = "", ""
            else:  # release / version
                payload, _meta = gh.request(f"/repos/{repo}/releases/latest", token=token)
                payload = payload or {}
                tag = payload.get("tag_name", "")
                published_at = payload.get("published_at", "")
                html_url = payload.get("html_url", "")
        except gh.GitHubError as exc:
            if exc.status == 404:
                out.append({**base, "status": "no_release", "note": "仓库无 release/tag"})
            else:
                out.append({**base, "status": "error", "error": str(exc)})
            continue
        if not tag:
            out.append({**base, "status": "error", "error": "API 未返回版本 tag"})
            continue
        out.append({**base, "status": "ok", "tag": tag, "published_at": published_at,
                    "html_url": html_url,
                    "changed": bool(base["prev_tag"]) and tag != base["prev_tag"]})
    return out


# --------------------------------------------------------------------------
# ② 自身依赖：requirements vs PyPI
# --------------------------------------------------------------------------
def check_deps(cfg: dict, *, fetch_latest=None) -> dict:
    """扫描 self_requirements → 分类 outdated / held / unpinned / up_to_date

    单包失败只记 errors，不影响其余（和 discover 的单查询隔离同理）。
    """
    fetch = fetch_latest or _pypi_latest
    files: list[dict] = []
    outdated: list[dict] = []
    held: list[dict] = []
    unpinned: list[dict] = []
    errors: list[str] = []
    attempted = resolved = ok_count = 0

    for rel in (cfg.get("monitoring") or {}).get("self_requirements") or []:
        path = store.REPO_ROOT / rel
        entry = {"file": rel, "status": "ok", "packages": 0}
        files.append(entry)
        if not path.is_file():
            entry["status"] = "missing"
            errors.append(f"{rel}: 文件不存在")
            continue
        for req in parse_requirements(path.read_text(encoding="utf-8", errors="replace")):
            if req.get("unparsed"):
                errors.append(f"{rel}: 无法解析 {req['raw']!r}")
                continue
            entry["packages"] += 1
            attempted += 1
            try:
                latest = fetch(req["name"])
            except Exception as exc:  # noqa: BLE001 - 单包失败不拖垮整份报告
                errors.append(f"{rel}/{req['name']}: PyPI 查询失败: {exc}")
                continue
            if not latest:
                errors.append(f"{rel}/{req['name']}: PyPI 未返回版本")
                continue
            resolved += 1
            item = {"name": req["name"], "file": rel,
                    "current": req["spec"] or "(未锁定)", "latest": latest}
            if not req["spec"]:
                item["status"] = "unpinned"
                unpinned.append(item)
                continue
            status, detail = _classify_pin(req["spec"], latest)
            if status == "ok":
                ok_count += 1
            elif status == "outdated":
                item["status"] = status
                item["bump"] = detail
                outdated.append(item)
            elif status == "held":
                item["status"] = status
                item["reason"] = detail
                held.append(item)
            else:  # unknown / ahead：如实进 errors，不进升级清单
                errors.append(f"{rel}/{req['name']}: {detail}")

    return {"files": files, "attempted": attempted, "resolved": resolved,
            "up_to_date": ok_count, "outdated": outdated, "held": held,
            "unpinned": unpinned, "errors": errors}


# --------------------------------------------------------------------------
# ③ 自身 CI：成功率 / 时长（阈值口径来自 config.monitoring.alerts）
# --------------------------------------------------------------------------
def check_self_ci(cfg: dict, *, token: str | None, budget: _Budget, now: datetime) -> dict:
    mon = cfg.get("monitoring") or {}
    repo = (mon.get("self_repo") or "").strip()
    floor = (mon.get("alerts") or {}).get("ci_success_floor", 0.9)
    if not repo:
        return {"status": "skipped", "note": "monitoring.self_repo 未配置"}
    if not budget.take():
        return {"status": "skipped_budget"}
    try:
        payload, _meta = gh.request(
            f"/repos/{repo}/actions/runs",
            {"status": "completed", "branch": SELF_CI_BRANCH, "per_page": SELF_CI_SAMPLE},
            token=token)
    except gh.GitHubError as exc:
        return {"status": "error", "error": str(exc), "floor": floor}
    runs = [r for r in ((payload or {}).get("workflow_runs") or []) if r.get("conclusion")]
    if not runs:
        return {"status": "skipped", "note": "无已完成的 workflow run 可用", "floor": floor}
    success = sum(1 for r in runs if r.get("conclusion") == "success")
    rate = round(success / len(runs), 4)
    durations: list[float] = []
    for r in runs:
        started = _parse_dt(r.get("run_started_at"))
        updated = _parse_dt(r.get("updated_at"))
        if started and updated and updated >= started:
            durations.append((updated - started).total_seconds() / 60.0)
    avg = round(sum(durations) / len(durations), 2) if durations else 0.0
    return {"status": "ok", "repo": repo, "runs": len(runs), "success": success,
            "success_rate": rate, "avg_duration_min": avg, "floor": floor,
            "below_floor": rate < floor}


def check_coverage(cfg: dict) -> dict:
    """覆盖率：显式 skipped——CI 未产出可读数据文件，不假装有数"""
    floor = ((cfg.get("monitoring") or {}).get("alerts") or {}).get("coverage_floor")
    return {"status": "skipped", "floor": floor,
            "note": "无数据源：ci.yml 用 --cov-fail-under 直接拦截，未产出报告文件"}


# 只认 GitHub 令牌前缀（其余"像密钥的"字符串误报率高，不猜）；
# OKX 密钥在 .env（已 gitignore），不属于本扫描的对象。
_SECRET_PATTERNS = tuple(re.compile(p) for p in (
    r"ghp_[A-Za-z0-9]{36,}",          # classic PAT
    r"github_pat_[A-Za-z0-9_]{20,}",  # fine-grained PAT
    r"gho_[A-Za-z0-9]{36,}",          # OAuth
    r"ghs_[A-Za-z0-9]{36,}",          # GitHub App
))


def check_secret_hygiene() -> dict:
    """静态扫描 .git/config 与 .github/workflows/*.yml 的明文令牌（审计 §8.3 收口）

    只读文本、不外发；worktree 布局（.git 是文件）下没有 .git/config 可扫，
    scanned 计数如实反映实际扫到的文件数。
    """
    targets: list[Path] = []
    git_config = store.REPO_ROOT / ".git" / "config"
    if git_config.is_file():
        targets.append(git_config)
    workflows = store.REPO_ROOT / ".github" / "workflows"
    if workflows.is_dir():
        targets.extend(sorted(p for p in workflows.glob("*.y*ml") if p.is_file()))
    hits: list[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in _SECRET_PATTERNS:
            for _match in pattern.finditer(text):
                rel = path.relative_to(store.REPO_ROOT)
                hits.append(f"{rel}: 明文令牌（{pattern.pattern.split('_')[0]}_***）")
    return {"status": "ok" if not hits else "error",
            "scanned": len(targets), "hits": hits}


# --------------------------------------------------------------------------
# ④ 告警构建与落地
# --------------------------------------------------------------------------
def _release_body(w: dict) -> str:
    src = "config.monitoring.watched" if w.get("source") == "config" else "项目卡（analyzed/approved/integrated）"
    published = (w.get("published_at") or "")[:10]
    lines = [
        "上游项目发布了新版本。",
        "",
        f"- 仓库：`{w.get('repo', '')}`",
        f"- 新版本：`{w.get('tag', '')}`" + (f"（发布于 {published}）" if published else ""),
        f"- 上一版本：`{w.get('prev_tag', '') or '（基线）'}`",
        f"- 发布页：{w.get('html_url') or '（无）'}",
        f"- 来源：{src}",
        "",
        "由 `scripts/gov/monitor.py` 自动创建；处理完请关闭本 Issue。",
    ]
    return "\n".join(lines)


def build_alerts(watched: list[dict], self_ci: dict, *, state: dict) -> tuple[list[dict], list[str]]:
    """返回 (alerts, notes)。触发条件全部基于跨运行记忆（alerted_tag / ci.last_rate）：

    - release：tag 与 alerted_tag 不同 → 告警；**无 alerted_tag 记忆**（首次运行或
      状态丢失）→ 不告警，由 update_state 记录为新基线——宁缺毋滥，重建记忆时
      不制造无法验证的"新版本"；版本数字回退（可能上游撤回）不告警、留 note；
    - ci：成功率跌破 floor 且上一轮还在 floor 之上（或从未记录）→ 告警，
      持续低于 floor 不重复告警（去重在状态侧，标题不含动态数字）。
    """
    alerts: list[dict] = []
    notes: list[str] = []
    for w in watched:
        if w.get("status") != "ok" or not w.get("tag"):
            continue
        tag = w.get("tag", "")
        alerted = w.get("alerted_tag", "")
        if not alerted or tag == alerted:
            continue
        lt, at = _ver_tuple(tag), _ver_tuple(alerted)
        if lt is not None and at is not None and lt < at:
            notes.append(f"watched {w.get('repo', '')}: 版本回退 {alerted} → {tag}"
                         "（可能上游撤回），不告警")
            continue
        alerts.append({
            "kind": "release",
            "repo": w.get("repo", ""),
            "fingerprint": f"{w.get('repo', '')}:{tag}",
            "title": f"{ALERT_TITLE_PREFIX} {w.get('repo', '')} 新版本 {tag}",
            "body": _release_body(w),
        })
    if self_ci.get("status") == "ok" and self_ci.get("below_floor"):
        prev_rate = (state.get("ci") or {}).get("last_rate")
        floor = self_ci.get("floor", 0.9)
        if prev_rate is None or prev_rate >= floor:
            rate = self_ci.get("success_rate", 0.0)
            alerts.append({
                "kind": "ci",
                "repo": self_ci.get("repo", ""),
                "fingerprint": "self:ci",
                "title": f"{ALERT_TITLE_PREFIX} CI 成功率低于下限",
                "body": "\n".join([
                    "自身仓库 CI 成功率跌破配置下限（monitoring.alerts.ci_success_floor）。",
                    "",
                    f"- 最近样本：{self_ci.get('success', 0)}/{self_ci.get('runs', 0)}"
                    f" success（{rate:.1%}）",
                    f"- 下限：{floor:.0%}",
                    f"- 分支：`{SELF_CI_BRANCH}`",
                    "",
                    "由 `scripts/gov/monitor.py` 自动创建；恢复后请关闭本 Issue。",
                ]),
            })
    return alerts, notes


def build_deps_issue(deps: dict, now: datetime) -> dict:
    """月度依赖健康报告 Issue：outdated 全量 + 低风险优先的升级顺序"""
    month = now.strftime("%Y-%m")
    outdated = deps.get("outdated") or []
    order = sorted(outdated,
                   key=lambda d: {"patch": 0, "minor": 1, "major": 2}.get(d.get("bump", ""), 3))
    lines = [
        f"## 依赖健康报告 {month}",
        "",
        f"扫描文件：{'、'.join(f.get('file', '') for f in deps.get('files') or [])}",
        "",
        "| 包 | 文件 | 当前 | 最新 | 升级类型 |",
        "|---|---|---|---|---|",
    ]
    for d in order:
        lines.append(f"| `{d['name']}` | {d['file']} | `{d['current']}` | `{d['latest']}` | {d['bump']} |")
    lines += ["", "### 建议升级顺序（低风险优先）", ""]
    for i, d in enumerate(order, 1):
        lines.append(f"{i}. `{d['name']}`（{d.get('bump', 'unknown')}）")
    lines += [
        "",
        f"另有 held（按既定策略持有上界）：{len(deps.get('held') or [])} 个；"
        f"up-to-date：{deps.get('up_to_date', 0)} 个；"
        f"errors：{len(deps.get('errors') or [])} 条（见当次 monitor 报告）。",
        "",
        "升级一律走 Dependabot PR / 人工评估（大版本），合并前须跑通 CI。",
        "由 `scripts/gov/monitor.py` 月度生成。",
    ]
    return {"kind": "deps", "repo": "(self)", "fingerprint": f"deps:{month}",
            "title": f"{DEPS_TITLE_PREFIX} 依赖健康报告 {month}",
            "body": "\n".join(lines)}


def _open_alert_issues(self_repo: str, *, token: str | None, budget: _Budget) -> list[dict]:
    budget.spend()
    payload, _meta = gh.request(
        f"/repos/{self_repo}/issues", {"state": "open", "per_page": 100}, token=token)
    out: list[dict] = []
    for item in payload or []:
        if "pull_request" in item:  # issues 接口混入 PR，剔除
            continue
        title = item.get("title", "")
        if title.startswith((ALERT_TITLE_PREFIX, DEPS_TITLE_PREFIX)):
            out.append({"number": item.get("number"), "title": title,
                        "created_at": item.get("created_at", "")})
    return out


def ensure_alert_label(self_repo: str, *, token: str | None, budget: _Budget) -> str | None:
    """尽力保证告警 label 存在（422=已存在）。失败不致命——逻辑不依赖 label"""
    budget.spend()
    try:
        gh.request(f"/repos/{self_repo}/labels", method="POST",
                   body={"name": ALERT_LABEL, "color": "d93f0b",
                         "description": "治理系统（scripts/gov/monitor.py）自动告警"},
                   token=token)
        return None
    except gh.GitHubError as exc:
        if exc.status == 422:
            return None
        return str(exc)


def apply_alerts(alerts: list[dict], *, self_repo: str, open_issues: list[dict],
                 max_open: int, token: str | None, budget: _Budget) -> list[dict]:
    """执行告警落地。outcome: created / duplicate_open / appended / error"""
    results: list[dict] = []
    open_alert = [i for i in open_issues if i["title"].startswith(ALERT_TITLE_PREFIX)]
    for alert in alerts:
        if any(i["title"] == alert["title"] for i in open_issues):
            results.append({**alert, "outcome": "duplicate_open"})
            continue
        try:
            if len(open_alert) >= max_open:
                target = sorted(open_alert, key=lambda i: i.get("created_at", ""))[-1]
                budget.spend()
                gh.request(f"/repos/{self_repo}/issues/{target['number']}/comments",
                           method="POST",
                           body={"body": f"**新告警（追加）**\n\n{alert['body']}"},
                           token=token)
                results.append({**alert, "outcome": "appended",
                                "issue": target["number"]})
            else:
                budget.spend()
                payload, _meta = gh.request(
                    f"/repos/{self_repo}/issues", method="POST",
                    body={"title": alert["title"], "body": alert["body"],
                          "labels": [ALERT_LABEL]},
                    token=token)
                number = (payload or {}).get("number")
                issue = {"number": number, "title": alert["title"],
                         "created_at": store.utc_now_iso()}
                open_alert.append(issue)
                open_issues.append(issue)
                results.append({**alert, "outcome": "created", "issue": number})
        except gh.GitHubError as exc:
            results.append({**alert, "outcome": "error", "error": str(exc)})
    return results


# --------------------------------------------------------------------------
# 状态（跨运行记忆）
# --------------------------------------------------------------------------
def _state_path(cfg: dict):
    return store.knowledge_root(cfg) / STATE_FILENAME


def _load_state(cfg: dict, notes: list[str]) -> dict:
    path = _state_path(cfg)
    fresh = {"version": 1, "watched": {}, "ci": {}, "deps": {}}
    if not path.exists():
        return fresh
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state 根应为 dict")
    except (OSError, ValueError) as exc:
        notes.append(f"监控状态文件损坏，本轮按空状态处理（会重新记基线）: {exc}")
        return fresh
    data.setdefault("version", 1)
    data.setdefault("watched", {})
    data.setdefault("ci", {})
    data.setdefault("deps", {})
    return data


def _save_state(state: dict, cfg: dict) -> None:
    root = store.ensure_knowledge(cfg)
    state["updated_at"] = store.utc_now_iso()
    (root / STATE_FILENAME).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_state(state: dict, *, watched: list[dict], self_ci: dict,
                 outcomes: list[dict], deps_issue: bool, now: datetime) -> list[str]:
    """把本轮结果合并进跨运行状态；返回需要记进报告的 notes。

    核心规则：
    - `last_seen_tag` 每轮如实前进（观测值，不做承诺）；
    - `alerted_tag` 只在"告警已成功落地"或"建立基线"时前进——告警未送达
      （disabled/error）时保持旧值，下一轮自动重试：没送达的告警不算已送达；
    - 无 alerted_tag 记忆（首次/状态丢失）→ 记基线并发 note，本轮不告警。
    """
    notes: list[str] = []
    ws = state.setdefault("watched", {})
    outcome_by_repo = {a.get("repo", ""): a.get("outcome", "")
                       for a in outcomes if a.get("kind") == "release"}
    for w in watched:
        if w.get("status") != "ok":
            continue
        repo = w.get("repo", "")
        tag = w.get("tag", "")
        st = ws.setdefault(repo, {})
        st["last_seen_tag"] = tag
        st["checked_at"] = w.get("checked_at") or store.utc_now_iso()
        alerted = st.get("alerted_tag", "")
        if not alerted:
            st["alerted_tag"] = tag  # 基线（含状态丢失后的重建）
            notes.append(f"watched {repo}: 建立版本基线 {tag}（无告警记忆，本轮不告警）")
        elif tag != alerted and outcome_by_repo.get(repo) in COMMITTED_OUTCOMES:
            st["alerted_tag"] = tag
    ci = state.setdefault("ci", {})
    if self_ci.get("status") == "ok":
        if self_ci.get("below_floor"):
            ci_outcome = next((a.get("outcome") for a in outcomes
                               if a.get("kind") == "ci"), None)
            if ci_outcome in COMMITTED_OUTCOMES:
                ci["last_rate"] = self_ci.get("success_rate")
        else:
            ci["last_rate"] = self_ci.get("success_rate")
    if deps_issue and any(a.get("kind") == "deps" and a.get("outcome") in COMMITTED_OUTCOMES
                          for a in outcomes):
        state.setdefault("deps", {})["last_issue_month"] = now.strftime("%Y-%m")
    return notes


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run(cfg: dict, *, token: str | None = None, now: datetime | None = None,
        write: bool = True, create_issues: bool = False, deps_issue: bool = False,
        max_requests: int | None = None, fetch_latest=None) -> dict:
    """执行一次监控。返回 report dict（write=True 时同时落盘）：
    {generated_at, status, requests_used, budget_total, truncated, watched,
     deps, self_ci, coverage, alerts, metric_record, errors, notes}
    """
    now = now or datetime.now(timezone.utc)
    date = now.strftime("%Y-%m-%d")
    mon = cfg.get("monitoring") or {}
    alerts_cfg = mon.get("alerts") or {}
    self_repo = (mon.get("self_repo") or "").strip()
    budget = _Budget(max_requests or mon.get("max_requests_per_run", 20))
    errors: list[str] = []
    notes: list[str] = []
    state = _load_state(cfg, notes)

    # 凭据一次性解析：失败则跳过全部 GitHub 检查（依赖检查不受影响）
    gh_token, gh_available = token, True
    if gh_token is None:
        try:
            gh_token = gh.token_from_env()
        except gh.NoCredentials as exc:
            gh_available = False
            errors.append(f"credentials: {exc}")
            notes.append("GitHub 检查全部跳过（无凭据）；依赖检查仍在本地完成")

    # ---- ① watched：config 名单 + 项目卡 ----
    card_cards = [c for c in store.list_project_cards(cfg).values()
                  if c.get("status") in CARD_MONITOR_STATUSES]
    items = [{"repo": w.get("repo", ""), "kind": w.get("kind", "release"),
              "source": "config", "prev_fallback": ""} for w in mon.get("watched") or []]
    items += [{"repo": c.get("name", ""), "kind": "release", "source": "card",
               "prev_fallback": c.get("version_watched", "")} for c in card_cards]

    watched: list[dict] = []
    if gh_available and items:
        try:
            watched = check_watched(items, token=gh_token, budget=budget, state=state, now=now)
        except gh.GitHubError as exc:  # 内部已逐项隔离，这是兜底
            errors.append(f"watched: {exc}")
    elif items:
        watched = [{"repo": it["repo"], "kind": it["kind"], "source": it["source"],
                    "status": "skipped_no_credentials"} for it in items]
    for w in watched:
        if w.get("status") == "error":
            errors.append(f"watched {w['repo']}: {w.get('error', '')}")
        elif w.get("status") == "skipped_budget":
            notes.append(f"watched {w['repo']}: 预算用尽跳过")

    # 项目卡回写（仅真实运行；dry-run 只预览）
    if write and card_cards:
        by_name = {c["name"]: c for c in card_cards}
        for w in watched:
            if w.get("source") != "card" or w.get("status") != "ok":
                continue
            card = by_name.get(w["repo"])
            if not card:
                continue
            card["version_watched"] = w.get("tag", "")
            card["last_checked"] = now.isoformat()
            quality = card.setdefault("quality", {})
            quality["release"] = {"latest_tag": w.get("tag", ""),
                                  "published_at": w.get("published_at", ""),
                                  "checked_at": now.isoformat()}
            try:
                store.save_project_card(card, cfg)
                notes.append(f"项目卡已更新: {w['repo']} → {w.get('tag', '')}")
            except schemas.SchemaError as exc:
                errors.append(f"项目卡回写失败 {w['repo']}: {exc}")

    # ---- ② 自身依赖 ----
    deps = check_deps(cfg, fetch_latest=fetch_latest)
    errors.extend(deps.get("errors") or [])

    # ---- ③ 自身 CI + 覆盖率 ----
    if gh_available:
        self_ci = check_self_ci(cfg, token=gh_token, budget=budget, now=now)
        if self_ci.get("status") == "error":
            errors.append(f"self_ci: {self_ci.get('error', '')}")
    else:
        self_ci = {"status": "skipped_no_credentials"}
    coverage = check_coverage(cfg)
    secret_hygiene = check_secret_hygiene()
    for hit in secret_hygiene.get("hits") or []:
        errors.append(f"secret-hygiene: {hit}")

    # ---- ④ 告警构建 → 落地 ----
    alerts_built, alert_notes = build_alerts(watched, self_ci, state=state)
    notes.extend(alert_notes)
    if deps_issue:
        month = now.strftime("%Y-%m")
        last_month = (state.get("deps") or {}).get("last_issue_month", "")
        if last_month == month:
            notes.append(f"依赖健康报告本月（{month}）已发布过，跳过")
        elif deps.get("outdated"):
            alerts_built.append(build_deps_issue(deps, now))
        else:
            notes.append("依赖无 outdated，本月无需健康报告 Issue")

    outcomes: list[dict] = []
    open_count = 0
    if alerts_built and create_issues and gh_available:
        if not self_repo:
            errors.append("monitoring.self_repo 未配置，无法创建 Issue")
            outcomes = [{**a, "outcome": "error", "error": "self_repo 未配置"}
                        for a in alerts_built]
        else:
            open_issues: list[dict] | None = []
            try:
                open_issues = _open_alert_issues(self_repo, token=gh_token, budget=budget)
                open_count = len([i for i in open_issues
                                  if i["title"].startswith(ALERT_TITLE_PREFIX)])
            except gh.GitHubError as exc:
                errors.append(f"issue-list: {exc}")
                open_issues = None
            if open_issues is None:
                # 拿不到开放列表就不做任何变更：宁可晚一轮，也不能重复洪泛
                outcomes = [{**a, "outcome": "error",
                             "error": "无法拉取开放 Issue 列表，本轮不创建（防重复洪泛）"}
                            for a in alerts_built]
            else:
                label_err = ensure_alert_label(self_repo, token=gh_token, budget=budget)
                if label_err:
                    notes.append(f"告警 label 保障失败（仅影响样式）: {label_err}")
                outcomes = apply_alerts(alerts_built, self_repo=self_repo,
                                        open_issues=open_issues,
                                        max_open=alerts_cfg.get("max_open_alerts", 5),
                                        token=gh_token, budget=budget)
    else:
        outcomes = [{**a, "outcome": "disabled"} for a in alerts_built]

    # ---- ⑤ 状态提交（仅真实运行） ----
    if write:
        notes.extend(update_state(state, watched=watched, self_ci=self_ci,
                                  outcomes=outcomes, deps_issue=deps_issue, now=now))

    # ---- 汇总 ----
    skipped_budget = sum(1 for w in watched if w.get("status") == "skipped_budget")
    if self_ci.get("status") == "skipped_budget":
        skipped_budget += 1
    success_units = sum(1 for w in watched if w.get("status") == "ok")
    success_units += deps.get("resolved", 0)
    if self_ci.get("status") == "ok":
        success_units += 1
    if secret_hygiene.get("status") == "ok":
        success_units += 1
    if not errors:
        status = "ok"
    elif success_units == 0:
        status = "failed"
    else:
        status = "partial"

    snapshot_notes: list[str] = []
    if self_ci.get("status") == "ok":
        snapshot_notes.append(f"ci: {self_ci['success']}/{self_ci['runs']} success,"
                              f" avg {self_ci['avg_duration_min']} min")
    else:
        snapshot_notes.append(f"ci: {self_ci.get('status')}")
    snapshot_notes.append("coverage: 未采集（ci.yml 门禁直接拦截）")
    if not open_count:
        snapshot_notes.append("alerts_open: 未查询或为 0")

    snapshot = schemas.new_record(
        "metric_record",
        date=date,
        ci_success_rate=float(self_ci.get("success_rate") or 0.0),
        avg_duration=float(self_ci.get("avg_duration_min") or 0.0),
        coverage=0.0,
        alerts_open=open_count,
        deps_outdated=len(deps.get("outdated") or []),
        quota_used=budget.used,
        notes=snapshot_notes,
    )
    report = {
        "generated_at": now.isoformat(),
        "status": status,
        "requests_used": budget.used,
        "budget_total": budget.total,
        "truncated": skipped_budget > 0,
        "watched": watched,
        "deps": deps,
        "self_ci": self_ci,
        "coverage": coverage,
        "secret_hygiene": secret_hygiene,
        "alerts": outcomes,
        "metric_record": snapshot,
        "errors": errors,
        "notes": notes,
    }
    if write:
        store.write_json(report, "monitor.json", date=date)
        _write_snapshot(snapshot, date)
        _save_state(state, cfg)
    return report


def _write_snapshot(snapshot: dict, date: str):
    """度量快照落 reports/metrics/<date>.json（时间序列，供 P8 可观测性读取）"""
    path = store.REPORTS_DIR / METRICS_SUBDIR / f"{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _print_summary(report: dict) -> None:
    print("=== Gov Monitor ===")
    print(f"status      : {report['status']}")
    print(f"requests    : {report['requests_used']}/{report['budget_total']}")
    print("watched:")
    for w in report["watched"]:
        if w.get("status") == "ok":
            flag = "!" if w.get("changed") else " "
            print(f"  {flag} {w['repo']:<40} {w.get('tag', '')}"
                  f"  {(w.get('published_at') or '')[:10]}")
        else:
            print(f"    {w['repo']:<40} [{w.get('status')}]"
                  f" {w.get('error', w.get('note', ''))}")
    deps = report["deps"]
    print(f"deps        : outdated={len(deps['outdated'])} held={len(deps['held'])}"
          f" unpinned={len(deps['unpinned'])} up_to_date={deps['up_to_date']}")
    for d in deps["outdated"]:
        print(f"  ^ {d['name']:<30} {d['current']} -> {d['latest']} ({d['bump']})")
    ci = report["self_ci"]
    if ci.get("status") == "ok":
        print(f"self_ci     : {ci['success']}/{ci['runs']} success"
              f" ({ci['success_rate']:.0%}) avg {ci['avg_duration_min']} min"
              f" floor {ci['floor']:.0%}")
    else:
        print(f"self_ci     : {ci.get('status')} {ci.get('note', ci.get('error', ''))}")
    sh = report["secret_hygiene"]
    print(f"secrets     : {sh['status']} (scanned {sh['scanned']} files)")
    for a in report["alerts"]:
        print(f"  ALERT[{a.get('kind')}] {a.get('title')} -> {a.get('outcome')}")
    for err in report["errors"]:
        print(f"  ! {err}")
    for note in report["notes"]:
        print(f"  - {note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="③监控：上游 release 跟踪 + 依赖健康 + 阈值告警")
    parser.add_argument("--config", help="治理配置路径")
    parser.add_argument("--max-requests", type=int, help="覆盖单次运行的 GitHub 请求预算")
    parser.add_argument("--dry-run", action="store_true", help="不落盘、不建 Issue，只打印")
    parser.add_argument("--print", dest="do_print", action="store_true", help="打印摘要")
    parser.add_argument("--create-issues", action="store_true", help="告警真的落地为 GitHub Issue")
    parser.add_argument("--deps-issue", action="store_true",
                        help="额外生成月度依赖健康报告（需配合 --create-issues 才真正落地）")
    args = parser.parse_args(argv)

    try:
        cfg = gconfig.load_config(args.config)
    except gconfig.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        report = run(cfg, max_requests=args.max_requests, write=not args.dry_run,
                     create_issues=args.create_issues and not args.dry_run,
                     deps_issue=args.deps_issue)
    except Exception as exc:  # noqa: BLE001 - CLI 兜底只如实报告，不假装没事
        print(f"error: monitor failed: {exc}", file=sys.stderr)
        return 1

    if args.do_print or args.dry_run:
        _print_summary(report)
    return 0 if report["status"] in ("ok", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
