"""①发现：GitHub Search API → candidates.json

边界与取舍：
- **配额是硬约束**：每次运行按 config.discovery.max_requests_per_run 发请求，
  用完就停并把 truncated=True 写进产物——宁可少发现几个，也不要把 search
  配额（30/分钟）打穿导致后续监控/查_card 全部 403。
- **单查询故障隔离**：某个关键词报错（403 二级限流、网络抖动）只记录到
  report.errors，其余关键词照常跑；全部失败才是 failed。
- **过滤放在客户端**：GitHub 的 `fork:false` 之类限定符行为随版本漂移，
  而返回的 item 里 fork/archived/pushed_at 都是确定的真值，
  宁可多取一点回来在本地判，也不要因为限定符语义变了而误筛。
- **增量去重**：同一 full_name 跨关键词只留 stars 更高的那条；已经在知识库里
  有项目卡的跳过（counted as skipped_known），避免每次运行重复喂下游。

用法（需以 -m 方式运行：脚本 import 了 scripts.gov 包，直接指路径会缺包）
----
    python -m scripts.gov.discover --print          # 采集并落 reports/<date>/discovery.json
    python -m scripts.gov.discover --dry-run --max-requests 5
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from scripts.gov import config as gconfig
from scripts.gov import github_api as gh
from scripts.gov import schemas
from scripts.gov import store

SEARCH_PATH = "/search/repositories"


def _iso_days_ago(days: int, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(days=days)).strftime("%Y-%m-%d")


def build_queries(cfg: dict, now: datetime | None = None) -> list[dict]:
    """把 config 里的 domains 展开成待执行的查询计划

    每条 = {"domain", "kind": keyword|topic, "term", "query"}
    """
    disc = cfg.get("discovery", {})
    since = _iso_days_ago(disc.get("filters", {}).get("pushed_within_days", 365), now)
    min_stars = disc.get("filters", {}).get("min_stars", 0)

    plan: list[dict] = []
    for domain in sorted(disc.get("domains", {})):
        spec = disc["domains"][domain]
        if not spec.get("enabled", False):
            continue
        terms = [(k, t) for k in ("keywords", "topics") for t in spec.get(k, [])]
        for kind, term in terms:
            plan.append({
                "domain": domain,
                "kind": kind,
                "term": term,
                "query": f'{term} stars:>{min_stars} pushed:>{since}',
            })
    return plan


def _item_to_candidate(item: dict, domain: str, term: str, now: datetime) -> dict:
    license_info = item.get("license") or {}
    return schemas.new_record(
        "candidate",
        full_name=item.get("full_name", ""),
        url=item.get("html_url", ""),
        domain=domain,
        keyword=term,
        stars=int(item.get("stargazers_count") or 0),
        forks=int(item.get("forks_count") or 0),
        open_issues=int(item.get("open_issues_count") or 0),
        language=item.get("language") or "",
        license=license_info.get("spdx_id") or license_info.get("key") or "",
        topics=list(item.get("topics") or []),
        pushed_at=item.get("pushed_at") or "",
        description=(item.get("description") or "")[:300],
        archived=bool(item.get("archived")),
        fork=bool(item.get("fork")),
        discovered_at=now.isoformat(),
    )


def _passes_filters(cand: dict, cfg: dict) -> bool:
    filters = cfg.get("discovery", {}).get("filters", {})
    if filters.get("exclude_forks", True) and cand["fork"]:
        return False
    if filters.get("exclude_archived", True) and cand["archived"]:
        return False
    if cand["stars"] < filters.get("min_stars", 0):
        return False
    return True


def run(cfg: dict, *, max_requests: int | None = None, token: str | None = None,
        now: datetime | None = None, write: bool = True) -> dict:
    """执行一次发现

    返回 report dict（同时也是落盘内容）：
        {generated_at, status, plan_total, requests_used, truncated,
         candidates, skipped_known, duplicate_merged, errors}
    """
    now = now or datetime.now(timezone.utc)
    plan = build_queries(cfg, now)
    per_keyword = cfg.get("discovery", {}).get("per_keyword_limit", 10)
    budget = max_requests or cfg.get("discovery", {}).get("max_requests_per_run", 20)
    blacklist = set(cfg.get("scoring", {}).get("blacklist") or [])
    known = set(store.list_project_cards(cfg))

    best: dict[str, dict] = {}
    skipped_known = 0
    duplicates = 0
    errors: list[str] = []
    requests_used = 0

    for item_plan in plan:
        if requests_used >= budget:
            break
        requests_used += 1
        try:
            payload, _meta = gh.request(
                SEARCH_PATH,
                {"q": item_plan["query"], "sort": "stars", "order": "desc",
                 "per_page": per_keyword},
                token=token,
            )
        except gh.NoCredentials as exc:
            errors.append(f"credentials: {exc}")
            break
        except gh.GitHubError as exc:
            # 单条查询失败不影响其余继续跑，但必须留下痕迹
            errors.append(f"{item_plan['domain']}/{item_plan['term']}: {exc}")
            continue

        for item in (payload or {}).get("items", []) or []:
            full_name = item.get("full_name", "")
            if not full_name or full_name in blacklist:
                continue
            if full_name in known:
                skipped_known += 1
                continue
            cand = _item_to_candidate(item, item_plan["domain"], item_plan["term"], now)
            if not _passes_filters(cand, cfg):
                continue
            prev = best.get(full_name)
            if prev is None:
                best[full_name] = cand
            else:
                duplicates += 1
                if cand["stars"] > prev["stars"]:
                    best[full_name] = cand

    candidates = sorted(best.values(), key=lambda c: c["stars"], reverse=True)
    truncated = requests_used >= budget and len(plan) > requests_used

    if not plan:
        status = "failed"
    elif not candidates and errors:
        status = "failed"
    elif errors:
        status = "partial"
    else:
        status = "ok"

    report = {
        "generated_at": now.isoformat(),
        "status": status,
        "plan_total": len(plan),
        "requests_used": requests_used,
        "truncated": truncated,
        "candidates": candidates,
        "count": len(candidates),
        "skipped_known": skipped_known,
        "duplicate_merged": duplicates,
        "errors": errors,
    }
    if write:
        store.write_json(report, "discovery.json", date=now.strftime("%Y-%m-%d"))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="①发现：GitHub 仓库候选扫描")
    parser.add_argument("--config", help="治理配置路径")
    parser.add_argument("--max-requests", type=int, help="覆盖单次运行的请求预算")
    parser.add_argument("--dry-run", action="store_true", help="不落盘，只打印结果")
    parser.add_argument("--print", dest="do_print", action="store_true", help="打印摘要")
    args = parser.parse_args(argv)

    try:
        cfg = gconfig.load_config(args.config)
    except gconfig.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        report = run(cfg, max_requests=args.max_requests, write=not args.dry_run)
    except Exception as exc:  # noqa: BLE001 - CLI 兜底只做如实报告，不做"假装没事"
        print(f"error: discovery failed: {exc}", file=sys.stderr)
        return 1

    if args.do_print or args.dry_run:
        print("=== Gov Discovery ===")
        print(f"status      : {report['status']}")
        print(f"plan/used   : {report['plan_total']}/{report['requests_used']}"
              f" (truncated={report['truncated']})")
        print(f"candidates  : {report['count']}"
              f" (已存在于知识库跳过 {report['skipped_known']}，"
              f"跨关键词去重合并 {report['duplicate_merged']})")
        for cand in report["candidates"][:15]:
            print(f"  {cand['stars']:>7}★ {cand['domain']:<10} {cand['full_name']}")
        for err in report["errors"]:
            print(f"  ! {err}")
    return 0 if report["status"] in ("ok", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
