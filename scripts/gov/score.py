"""②筛选：candidates → shortlist.json（7 维评分 → A/B/C 分层）

定位与取舍：
- **离线纯函数**：本模块不发起任何 GitHub API 请求——搜索返回的字段
  （stars / forks / open_issues / license / language / pushed_at / archived）足以支撑
  首轮筛选；需要联网的深挖（release 跟踪、依赖清单）属于 ③监控 / ⑤学习。
  不联网 = 不耗配额、可离线重放、CI 可全量测试。
- **策略只在 config.scoring**（权重 / 分档线 / 黑白名单），本文件只有公式与结构；
  改策略不改代码。
- **数据不足不许假装**（P3b"假度量清零"同款立场）：
  · issue_response 是**代理指标**——未关闭 issue 密度（Search API 没有响应时长字段）；
  · dependency_health 在 ⑤学习 产出依赖清单前记**中性 50**，report.notes 明说；
  · star_trend 冷启动用对数规模近似；上一份 shortlist 存在时改用真实差分（次日生效）。
- **黑白名单双保险**：discover 已过滤一轮，这里对黑名单再过一次（score 允许被单独
  调用，不默认上游干净）；白名单直通不参与分层——那是人工认可的观察对象。

用法（必须 -m 运行，脚本内 import scripts.gov 包）：
    python -m scripts.gov.score --print                    # 读最新一份 discovery.json
    python -m scripts.gov.score --input <path> --dry-run   # 指定输入，不落盘

退出码：0 成功（ok/partial）· 1 运行失败（无输入可评分）· 2 配置错误。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.gov import config as gconfig
from scripts.gov import schemas, store

DIMENSIONS = (
    "star_trend",
    "commit_freshness",
    "issue_response",
    "dependency_health",
    "license",
    "language_fit",
    "maintenance",
)

_NEUTRAL = 50.0  # 数据不足时的中性分：显式使用、显式标注，禁止拿它冒充真实数据
_FRESH_BEST_DAYS = 7.0
_FRESH_WORST_DAYS = 365.0

_STAR_LOG_MIN = 2.0  # 100★ 为规模下限参考点
_STAR_LOG_MAX = 5.0  # 100k★ 封顶
_STAR_DELTA_CAP = 20.0  # 单期趋势差分最多 ±20 分

_ISSUE_DENSITY_BEST = 0.005  # open_issues / stars，越低越健康
_ISSUE_DENSITY_WORST = 0.2

_LICENSE_PERMISSIVE = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "Unlicense", "Zlib",
}
_LICENSE_WEAK = {"MPL-2.0", "LGPL-2.1", "LGPL-3.0"}
_LICENSE_STRONG = {"GPL-2.0", "GPL-3.0", "AGPL-3.0", "CC-BY-SA-4.0"}

_LANGUAGE_FIT = {
    "Python": 100.0,
    "Jupyter Notebook": 90.0,
    "C++": 60.0,
    "C": 60.0,
    "Rust": 60.0,
    "Go": 60.0,
    "Java": 50.0,
    "TypeScript": 50.0,
    "JavaScript": 50.0,
    "HTML": 40.0,
}

_MAINTENANCE_TIERS = ((90.0, 80.0), (180.0, 60.0), (365.0, 40.0))
_MAINTENANCE_STALE = 20.0
_MAINTENANCE_FORK_MIN = 100  # 被 fork ≥100 视为有真实使用规模
_MAINTENANCE_FORK_BONUS = 20.0


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _days_since(iso: str, now: datetime) -> float | None:
    """ISO8601 → 距 now 的天数；缺失 / 不可解析返回 None（由调用方显式降级）。"""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max((now - dt).total_seconds() / 86400.0, 0.0)


def _score_commit_freshness(days: float) -> float:
    """提交新鲜度：≤7 天满分，≥365 天零分，中间线性。"""
    if days <= _FRESH_BEST_DAYS:
        return 100.0
    if days >= _FRESH_WORST_DAYS:
        return 0.0
    return 100.0 * (_FRESH_WORST_DAYS - days) / (_FRESH_WORST_DAYS - _FRESH_BEST_DAYS)


def _score_star_trend(stars: int, prev_stars: int | None = None) -> tuple[float, str | None]:
    """star 趋势：冷启动为对数规模近似；有上期数据时叠加真实差分（±20 封顶）。"""
    base = _clamp((math.log10(max(stars, 1)) - _STAR_LOG_MIN) / (_STAR_LOG_MAX - _STAR_LOG_MIN) * 100.0)
    if prev_stars and prev_stars > 0:
        delta_pct = (stars - prev_stars) / prev_stars * 100.0
        adj = _clamp(delta_pct, -_STAR_DELTA_CAP, _STAR_DELTA_CAP)
        note = f"star 趋势：上期 {prev_stars} → 本期 {stars}（{delta_pct:+.1f}%，差分计入 {adj:+.1f}）"
        return _clamp(base + adj), note
    return base, "star 趋势：冷启动对数规模近似（无上期 shortlist，次日启用真实差分）"


def _score_issue_response(open_issues: int, stars: int) -> float:
    """issue 响应的代理指标：未关闭 issue 密度越低越健康（如实标注于 report.notes）。"""
    density = open_issues / max(stars, 1)
    if density <= _ISSUE_DENSITY_BEST:
        return 100.0
    if density >= _ISSUE_DENSITY_WORST:
        return 0.0
    return 100.0 * (_ISSUE_DENSITY_WORST - density) / (_ISSUE_DENSITY_WORST - _ISSUE_DENSITY_BEST)


def _score_license(license_id: str) -> float:
    """许可证适配（以"可被整合进本仓库"为视角，不是法律意见）。"""
    lid = (license_id or "").strip()
    if lid in _LICENSE_PERMISSIVE:
        return 100.0
    if lid in _LICENSE_WEAK:
        return 70.0
    if lid in _LICENSE_STRONG:
        return 30.0
    if lid in ("", "NOASSERTION"):
        return 20.0
    return 40.0  # 罕见的其它 SPDX：未知即保守，notes 不展开（分档本身已表达立场）


def _score_language_fit(language: str) -> float:
    """语言适配：以本仓库 Python 技术栈为中心的分档。"""
    lang = (language or "").strip()
    if lang in _LANGUAGE_FIT:
        return _LANGUAGE_FIT[lang]
    return 40.0 if not lang else 30.0


def _score_maintenance(archived: bool, days: float | None, forks: int) -> float:
    """维护状态：归档归零；否则按活跃档位 + 使用规模（forks）加成。

    与 commit_freshness 部分同源（都以 pushed_at 为输入），这是有意的双权重：
    freshness 衡量"最近一次动作"，maintenance 衡量"持续维护的能力与规模"。
    """
    if archived:
        return 0.0
    if days is None:
        return _MAINTENANCE_STALE
    base = _MAINTENANCE_STALE
    for limit, score in _MAINTENANCE_TIERS:
        if days <= limit:
            base = score
            break
    if forks >= _MAINTENANCE_FORK_MIN:
        base += _MAINTENANCE_FORK_BONUS
    return _clamp(base)


def assign_tier(total: float, tiers: dict) -> str:
    """按 config.scoring.tiers 阈值降序取第一个满足的档位（A/B/C…）。"""
    for name, threshold in sorted(tiers.items(), key=lambda kv: kv[1], reverse=True):
        if total >= threshold:
            return name
    return "C"


def score_candidate(
    cand: dict,
    cfg: dict,
    prev_stars: int | None = None,
    now: datetime | None = None,
) -> dict:
    """单个候选 → 带分值 / 档位 / 分项拆解 / notes 的 shortlist 条目（candidate 全部字段保留）。"""
    now = now or datetime.now(timezone.utc)
    scoring = cfg.get("scoring") or {}
    weights = dict(scoring.get("weights") or {})
    unknown = sorted(set(weights) - set(DIMENSIONS))
    if unknown:
        raise ValueError(f"scoring.weights 含未知维度 {unknown}（可用维度：{list(DIMENSIONS)}）")
    if not weights:
        raise ValueError("scoring.weights 为空——config 校验应已拦截，此处双保险")

    days = _days_since(cand.get("pushed_at") or "", now)
    notes: list[str] = []

    star_pts, star_note = _score_star_trend(cand["stars"], prev_stars)
    if star_note:
        notes.append(star_note)
    if days is None:
        notes.append("pushed_at 缺失或不可解析：commit_freshness 显式记 0（不猜）")
        fresh_pts = 0.0
    else:
        fresh_pts = _score_commit_freshness(days)

    parts = {
        "star_trend": star_pts,
        "commit_freshness": fresh_pts,
        "issue_response": _score_issue_response(cand.get("open_issues", 0), cand["stars"]),
        "dependency_health": _NEUTRAL,
        "license": _score_license(cand.get("license") or ""),
        "language_fit": _score_language_fit(cand.get("language") or ""),
        "maintenance": _score_maintenance(bool(cand.get("archived")), days, int(cand.get("forks") or 0)),
    }

    total = sum(weights[dim] * parts[dim] for dim in weights) / sum(weights.values())
    entry = dict(cand)
    entry["score"] = round(total, 2)
    entry["tier"] = assign_tier(total, scoring.get("tiers") or {})
    entry["score_breakdown"] = {dim: round(parts[dim], 2) for dim in weights}
    entry["notes"] = notes
    return entry


def _date_dirs(reports_dir: Path | None = None) -> list[Path]:
    base = Path(reports_dir) if reports_dir else store.REPORTS_DIR
    if not base.is_dir():
        return []
    return sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)


def _latest_discovery(reports_dir: Path | None = None) -> Path | None:
    for d in _date_dirs(reports_dir):
        f = d / "discovery.json"
        if f.exists():
            return f
    return None


def _load_prev_stars(exclude_date: str, reports_dir: Path | None = None) -> dict[str, int]:
    """上一份 shortlist（日期≠今天）的 {full_name: stars}，用于真实趋势差分；无则 {}。"""
    for d in _date_dirs(reports_dir):
        if d.name == exclude_date:
            continue
        f = d / "shortlist.json"
        if not f.exists():
            continue
        try:
            data = store.read_json(f)
        except (OSError, json.JSONDecodeError):
            continue
        out: dict[str, int] = {}
        for e in data.get("entries") or []:
            name, stars = e.get("full_name"), e.get("stars")
            if isinstance(name, str) and isinstance(stars, int) and not isinstance(stars, bool):
                out[name] = stars
        return out
    return {}


def run(
    cfg: dict,
    *,
    candidates: list[dict] | None = None,
    input_path: str | Path | None = None,
    prev_stars: dict[str, int] | None = None,
    now: datetime | None = None,
    write: bool = True,
) -> dict:
    """执行一轮筛选。candidates 优先；否则读 input_path；否则取最新一份 discovery.json。"""
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    errors: list[str] = []

    if candidates is None:
        path = Path(input_path) if input_path else _latest_discovery()
        if input_path and (path is None or not path.exists()):
            raise FileNotFoundError(f"discovery 输入不存在：{path}")
        if path is None:
            report = {
                "generated_at": now.isoformat(),
                "status": "failed",
                "source": {"kind": "none", "path": None},
                "count": 0,
                "tier_counts": {"A": 0, "B": 0, "C": 0},
                "whitelisted": 0,
                "excluded_blacklist": 0,
                "invalid_candidates": 0,
                "entries": [],
                "notes": [],
                "errors": ["未找到 discovery 输入：reports/<date>/discovery.json 均不存在，也未显式传入 candidates"],
            }
            if write:
                store.write_json(report, "shortlist.json", date=today)
            return report
        data = store.read_json(path)
        candidates = list(data.get("candidates") or [])
        source = {"kind": "file" if input_path else "latest", "path": str(path)}
    else:
        source = {"kind": "argument", "path": None}

    if prev_stars is None:
        prev_stars = _load_prev_stars(today)

    blacklist = {str(x) for x in (cfg.get("scoring", {}).get("blacklist") or [])}
    whitelist = {str(x) for x in (cfg.get("scoring", {}).get("whitelist") or [])}

    entries: list[dict] = []
    excluded = 0
    invalid = 0
    whitelisted = 0
    for cand in candidates:
        name = cand.get("full_name")
        if name in blacklist:
            excluded += 1
            continue
        problems = schemas.problems("candidate", cand)
        if problems:
            invalid += 1
            errors.append(f"{name or '<无名称>'}: candidate 契约不符 {problems[:2]}，已跳过")
            continue
        entry = score_candidate(cand, cfg, prev_stars=prev_stars.get(name), now=now)
        if name in whitelist:
            whitelisted += 1
            entry["tier"] = "A"
            entry["notes"].append("whitelist 直通：人工已认可的观察对象，不参与分层")
        entries.append(entry)

    order = {"A": 0, "B": 1, "C": 2}
    entries.sort(key=lambda e: (order.get(e["tier"], 9), -e["score"], e["full_name"]))

    tier_counts = {"A": 0, "B": 0, "C": 0}
    for e in entries:
        tier_counts[e["tier"]] = tier_counts.get(e["tier"], 0) + 1

    notes = [
        "issue_response 为代理指标：未关闭 issue 密度（GitHub Search API 无响应时长字段）",
        "dependency_health 记中性 50：依赖清单待 ⑤学习（analyze）采集后启用真实评分",
    ]
    if prev_stars:
        notes.append(f"star 趋势差分已启用：上期 shortlist 覆盖 {len(prev_stars)} 个项目")

    report = {
        "generated_at": now.isoformat(),
        "status": "partial" if (invalid or errors) else "ok",
        "source": source,
        "count": len(entries),
        "tier_counts": tier_counts,
        "whitelisted": whitelisted,
        "excluded_blacklist": excluded,
        "invalid_candidates": invalid,
        "entries": entries,
        "notes": notes,
        "errors": errors,
    }
    if write:
        store.write_json(report, "shortlist.json", date=today)
    return report


def _print_report(report: dict) -> None:
    tc = report["tier_counts"]
    print("=== Gov Shortlist ===")
    print(f"status      : {report['status']}")
    if report["source"]["path"]:
        print(f"source      : {report['source']['path']}")
    print(
        f"scored      : {report['count']} (A {tc['A']} / B {tc['B']} / C {tc['C']})"
        f"  whitelist {report['whitelisted']} / blacklist 排除 {report['excluded_blacklist']}"
        f" / 无效 {report['invalid_candidates']}"
    )
    for e in report["entries"][:15]:
        print(f"  {e['tier']} {e['score']:>6.2f}  {e['full_name']}  (★{e['stars']})")
    for err in report["errors"]:
        print(f"  ! {err}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gov ②筛选：candidates → shortlist（7 维评分 A/B/C）")
    parser.add_argument("--config", default=str(gconfig.DEFAULT_CONFIG), help="治理配置路径")
    parser.add_argument("--input", default=None, help="discovery.json 路径（缺省取最新一份）")
    parser.add_argument("--dry-run", action="store_true", help="不落盘")
    parser.add_argument("--print", dest="do_print", action="store_true", help="打印摘要")
    args = parser.parse_args(argv)

    try:
        cfg = gconfig.load_config(args.config)
    except gconfig.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        report = run(cfg, input_path=args.input, write=not args.dry_run)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.do_print or args.dry_run:
        _print_report(report)
    return 0 if report["status"] in ("ok", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
