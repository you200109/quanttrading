"""P6f 编排器：把 ①发现 → ②筛选 → ⑤学习 → ③监控 串成一轮治理运行

用法：
    python -m scripts.gov.run --mode daily --create-issues --sync-memory --print   # CI 每日
    python -m scripts.gov.run --mode deps  --create-issues --sync-memory           # CI 月度
    python -m scripts.gov.run --mode daily --dry-run --print                       # 本地演练

职责与边界：
- 只做编排与桥接，不复制任何模块逻辑：每个阶段以子进程调用既有 CLI
  （退出码语义沿用各模块：0 ok/partial/skipped、1 failed、2 config 错）；
- 失败即停（fail-fast），并把失败显式落成 GitHub Issue——去重按标题事件指纹、
  开放数达 monitoring.alerts.max_open_alerts 后只追加评论、拿不到开放 Issue
  列表则本轮零变更（与 monitor 同一套纪律）；
- --sync-memory（CI 专用）：知识库经不受保护的 gov-memory 分支往返（main 有
  分支保护，GITHUB_TOKEN 直推会被拒；见 scripts/gov/memory_branch.py）。
  restore 失败时**放弃 persist**，绝不把未恢复的工作区覆盖回分支；
- 星标趋势桥接：score 的差分历史读 reports/（CI 里 reports/ 不跨运行留存），
  运行前把知识库里上一期 shortlist 装回 reports/、score 之后再写回知识库快照，
  让 ② 的 star_trend 在 CI 里也走真实差分而不是永远冷启动；
- 本模块的 --dry-run 只关掉编排器自身副作用（不动分支/不建 Issue/不写
  run.json）；各阶段行为不变——想看阶段级干跑，请另配 --config 指向临时知识库
  （冒烟做法），不要污染仓库默认知识库。

知识库主权归 CI（gov-memory 分支）：本地真实运行要么先同步该分支——
    git fetch origin gov-memory && git checkout FETCH_HEAD -- vigilant-couscous/memory/knowledge
——要么用临时知识库做演练；两者的口径都记在 docs/governance-architecture.md。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.gov import config as gconfig
from scripts.gov import github_api as gh
from scripts.gov import memory_branch
from scripts.gov import store

RUN_TITLE_PREFIX = "[gov-run]"
RUN_LABEL = "gov-run"
RUN_LABEL_COLOR = "b60205"
FAILURE_TAIL_CHARS = 3000      # 失败 Issue 里保留的输出尾部
STAGE_TIMEOUT_SECONDS = 1200   # 单阶段上限（各模块内部还有自己的超时）
SNAPSHOT_SUBPATH = ("state", "prev_shortlist.json")


# --------------------------------------------------------------------------
# 阶段编排
# --------------------------------------------------------------------------
def _stage_specs(mode: str, *, create_issues: bool,
                 config_path: str | None) -> list[tuple[str, list[str]]]:
    base = (["--config", str(config_path)] if config_path else []) + ["--print"]
    specs: list[tuple[str, list[str]]] = []
    if mode == "daily":
        specs.append(("discover", ["-m", "scripts.gov.discover", *base]))
        specs.append(("score", ["-m", "scripts.gov.score", *base]))
        specs.append(("analyze", ["-m", "scripts.gov.analyze", *base]))
    monitor_args = ["-m", "scripts.gov.monitor", *base]
    if create_issues:
        monitor_args.append("--create-issues")
    if mode == "deps":
        monitor_args.append("--deps-issue")
    specs.append(("monitor", monitor_args))
    return specs


def _default_executor(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=STAGE_TIMEOUT_SECONDS, env=env)


def _run_stage(name: str, args: list[str], *, root: Path, executor) -> dict:
    cmd = [sys.executable, *args]
    print(f"\n== gov-run · {name} ==")
    started = time.monotonic()
    try:
        cp = executor(cmd, cwd=root)
    except subprocess.TimeoutExpired:
        return {"name": name, "exit_code": 124,
                "seconds": round(time.monotonic() - started, 1),
                "output_tail": f"阶段超时（>{STAGE_TIMEOUT_SECONDS}s）被终止"}
    seconds = round(time.monotonic() - started, 1)
    out, err = cp.stdout or "", cp.stderr or ""
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print(err, file=sys.stderr, end="" if err.endswith("\n") else "\n")
    return {"name": name, "exit_code": int(cp.returncode), "seconds": seconds,
            "output_tail": (out + err)[-FAILURE_TAIL_CHARS:]}


# --------------------------------------------------------------------------
# shortlist 快照桥接（跨运行 star 趋势差分）
# --------------------------------------------------------------------------
def _snapshot_path(kb_root: Path) -> Path:
    return kb_root.joinpath(*SNAPSHOT_SUBPATH)


def install_prev_shortlist(kb_root: Path, reports_dir: Path, date: str) -> dict:
    """把知识库里的上一期 shortlist 快照装回 reports/<date>/shortlist.json。

    score 的差分读取只看 reports/——快照不可用/坏数据一律跳过（不猜、不崩）。
    """
    snap = _snapshot_path(kb_root)
    if not snap.exists():
        return {"action": "none", "reason": "知识库无上期快照（首次运行）"}
    try:
        data = json.loads(snap.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("shortlist"), dict):
            raise ValueError("快照结构非法")
        snap_date = str(data.get("date") or "")
        if not snap_date:
            raise ValueError("快照缺 date")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"action": "none", "reason": f"快照不可用，跳过安装: {exc}"}
    if snap_date == date:
        return {"action": "none", "reason": "快照即今日（同日重跑不重复安装）"}
    target = reports_dir / snap_date / "shortlist.json"
    if target.exists():
        return {"action": "present", "date": snap_date}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data["shortlist"], ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return {"action": "installed", "date": snap_date, "path": str(target)}


def save_prev_shortlist(kb_root: Path, reports_dir: Path, date: str) -> dict:
    """把本期 shortlist 存成知识库快照（供下一个运行日差分）。"""
    src = reports_dir / date / "shortlist.json"
    if not src.exists():
        return {"action": "none", "reason": "本期 shortlist 不存在（score 未产出）"}
    try:
        obj = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"action": "none", "reason": f"本期 shortlist 不可读，跳过快照: {exc}"}
    snap = _snapshot_path(kb_root)
    snap.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "date": date, "shortlist": obj}
    snap.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return {"action": "saved", "date": date, "path": str(snap)}


# --------------------------------------------------------------------------
# 失败上报（Issue 去重 + 防洪；拿不到开放列表则零变更）
# --------------------------------------------------------------------------
def _actions_run_url() -> str | None:
    server = (os.environ.get("GITHUB_SERVER_URL") or "").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY") or ""
    run_id = os.environ.get("GITHUB_RUN_ID") or ""
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


def _failure_title(date: str) -> str:
    return f"{RUN_TITLE_PREFIX} 编排失败 {date}"


def _failure_body(failure: dict, *, mode: str, date: str) -> str:
    lines = [
        "## gov-run 编排失败",
        "",
        f"- 模式：`{mode}`",
        f"- 失败阶段：`{failure.get('stage', '?')}`（{failure.get('detail', '无详情')}）",
        f"- 时间（UTC）：{store.utc_now_iso()}",
    ]
    url = _actions_run_url()
    if url:
        lines.append(f"- Actions 运行：{url}")
    tail = (failure.get("output_tail") or "").strip()
    if tail:
        lines += ["", "### 输出尾部（截断）", "", "```", tail, "```"]
    lines += ["", "_由 scripts/gov/run.py 自动上报；修复后下一轮运行会自行恢复常态。_"]
    return "\n".join(lines)


def _ensure_label(self_repo: str, *, token: str | None, request) -> None:
    """尽力保证 label 存在（422=已存在）。失败不致命——逻辑不依赖 label"""
    try:
        request(f"/repos/{self_repo}/labels", method="POST",
                body={"name": RUN_LABEL, "color": RUN_LABEL_COLOR,
                      "description": "gov-run 编排器（scripts/gov/run.py）失败上报"},
                token=token)
    except gh.GitHubError:
        pass


def report_failure(failure: dict, *, cfg: dict, mode: str, date: str,
                   token: str | None = None, request=gh.request) -> dict:
    """把失败落成 Issue。outcome: created / appended / skipped / error"""
    mon = cfg.get("monitoring") or {}
    self_repo = (mon.get("self_repo") or "").strip()
    if not self_repo:
        return {"outcome": "skipped", "detail": "config 未配置 monitoring.self_repo"}
    max_open = int((mon.get("alerts") or {}).get("max_open_alerts", 5))
    title = _failure_title(date)
    try:
        payload, _meta = request(f"/repos/{self_repo}/issues",
                                 {"state": "open", "per_page": 100}, token=token)
    except gh.GitHubError as exc:
        return {"outcome": "skipped",
                "detail": f"拿不到开放 Issue 列表（{exc}），本轮零变更（宁可晚一轮）"}
    open_issues: list[dict] = []
    for item in payload or []:
        if "pull_request" in item:
            continue
        if str(item.get("title", "")).startswith(RUN_TITLE_PREFIX):
            open_issues.append({"number": item.get("number"),
                                "title": item.get("title", ""),
                                "created_at": item.get("created_at", "")})
    body = _failure_body(failure, mode=mode, date=date)
    same = next((i for i in open_issues if i["title"] == title), None)
    try:
        if same is not None:
            request(f"/repos/{self_repo}/issues/{same['number']}/comments", method="POST",
                    body={"body": f"**同日再次失败**\n\n{body}"}, token=token)
            return {"outcome": "appended", "issue": same["number"],
                    "detail": "同日重复失败，追加评论"}
        if len(open_issues) >= max_open:
            target = sorted(open_issues, key=lambda i: i.get("created_at", ""))[-1]
            request(f"/repos/{self_repo}/issues/{target['number']}/comments", method="POST",
                    body={"body": f"**新一轮失败（追加，开放上报已达上限）**\n\n{body}"},
                    token=token)
            return {"outcome": "appended", "issue": target["number"]}
        _ensure_label(self_repo, token=token, request=request)
        payload, _meta = request(f"/repos/{self_repo}/issues", method="POST",
                                 body={"title": title, "body": body,
                                       "labels": [RUN_LABEL]},
                                 token=token)
        return {"outcome": "created", "issue": (payload or {}).get("number")}
    except gh.GitHubError as exc:
        return {"outcome": "error", "detail": str(exc)}


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run(cfg: dict, *, mode: str = "daily", create_issues: bool = False,
        sync_memory: bool = False, dry_run: bool = False,
        config_path: str | None = None, root: Path | None = None,
        reports_dir: Path | None = None, now: datetime | None = None,
        executor=None, request=gh.request) -> dict:
    """执行一轮治理运行（各步骤显式记录，任何失败不外抛、只如实落报告）。"""
    root = Path(root or store.REPO_ROOT)
    reports_dir = Path(reports_dir or store.REPORTS_DIR)
    now = now or datetime.now(timezone.utc)
    date = now.strftime("%Y-%m-%d")
    executor = executor or _default_executor
    kb_root = store.knowledge_root(cfg)
    side_effects = not dry_run

    report: dict = {"version": 1, "mode": mode, "generated_at": store.utc_now_iso(),
                    "date": date, "status": "ok", "stages": [], "notes": [],
                    "memory": None, "bridge": None, "failure_issue": None}
    failure: dict | None = None
    memory: dict = {}
    bridge: dict = {}

    # 0) 知识库恢复（CI）：失败即中止——绝不能在未恢复的工作区上继续，否则
    #    运行完的 persist 会把分支上的记忆覆盖成空
    restore_ok = True
    kb_rel: str | None = None
    if sync_memory and side_effects:
        try:
            kb_rel = kb_root.relative_to(root).as_posix()
        except ValueError:
            restore_ok = False
            failure = {"stage": "restore-memory",
                       "detail": f"知识库根 {kb_root} 不在仓库 {root} 内"
                                 "（--sync-memory 仅用于 CI 默认配置）"}
            memory["restore"] = {"action": "error", "detail": failure["detail"]}
        if restore_ok:
            try:
                memory["restore"] = memory_branch.restore(root, kb_rel=kb_rel)
                action = memory["restore"]["action"]
                if action == "absent":
                    report["notes"].append("gov-memory 分支不存在——首次运行，本轮结束后创建")
                elif action == "no-kb":
                    report["notes"].append("gov-memory 分支还没有知识库目录——按首次运行处理")
                else:
                    report["notes"].append(
                        f"知识库已从 gov-memory 恢复（{memory['restore']['files']} 个文件）")
            except (memory_branch.GitError, OSError) as exc:
                restore_ok = False
                failure = {"stage": "restore-memory", "detail": str(exc)}
                memory["restore"] = {"action": "error", "detail": str(exc)}

    # 1) 星标趋势桥接：安装上一期 shortlist（增强性步骤，失败只记注不阻断）
    if restore_ok and mode == "daily" and side_effects:
        try:
            bridge["install"] = install_prev_shortlist(kb_root, reports_dir, date)
        except OSError as exc:
            bridge["install"] = {"action": "error", "detail": str(exc)}
            report["notes"].append(f"上期 shortlist 安装失败（继续运行）: {exc}")

    # 2) 阶段串行（fail-fast）
    if restore_ok:
        for name, args in _stage_specs(mode, create_issues=create_issues,
                                       config_path=config_path):
            result = _run_stage(name, args, root=root, executor=executor)
            report["stages"].append(result)
            if result["exit_code"] != 0:
                failure = {"stage": name, "detail": f"退出码 {result['exit_code']}",
                           "output_tail": result["output_tail"]}
                break

    # 3) 桥接保存：本期 shortlist → 知识库快照（analyze 失败也不影响这步的价值）
    if restore_ok and mode == "daily" and side_effects:
        try:
            bridge["save"] = save_prev_shortlist(kb_root, reports_dir, date)
        except OSError as exc:
            bridge["save"] = {"action": "error", "detail": str(exc)}
            report["notes"].append(f"本期 shortlist 快照失败（继续运行）: {exc}")

    # 4) 知识库回写（CI）：restore 失败时绝不执行（防覆盖）；阶段失败也照常回写
    #    已完成阶段的记忆
    if sync_memory and restore_ok and side_effects:
        try:
            memory["persist"] = memory_branch.persist(
                root, kb_rel=kb_rel, message=f"chore(gov): knowledge snapshot {date}")
            if memory["persist"]["action"] == "unchanged":
                report["notes"].append("知识库与分支一致，未产生空提交")
        except (memory_branch.GitError, OSError) as exc:
            memory["persist"] = {"action": "error", "detail": str(exc)}
            if failure is None:
                failure = {"stage": "persist-memory", "detail": str(exc)}
            else:
                report["notes"].append(f"persist-memory 另行失败：{exc}")

    report["memory"] = memory or None
    report["bridge"] = bridge or None

    # 5) 失败上报 + 落盘
    if failure is not None:
        report["status"] = "failed"
        if create_issues and side_effects:
            report["failure_issue"] = report_failure(
                failure, cfg=cfg, mode=mode, date=date, request=request)
    if side_effects:
        report["finished_at"] = store.utc_now_iso()
        out = reports_dir / date / "run.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        report["summary_path"] = str(out)
    return report


def _print_report(report: dict) -> None:
    print("\n=== Gov Run ===")
    print(f"mode        : {report['mode']}")
    print(f"status      : {report['status']}")
    stages = " / ".join(
        f"{s['name']} {s['exit_code']} ({s['seconds']}s)" for s in report["stages"])
    print(f"stages      : {stages or '—'}")
    for section in ("memory", "bridge"):
        data = report.get(section)
        if data:
            for key, val in data.items():
                note = val.get("reason") or val.get("detail") or ""
                print(f"{section + '·' + key:<12}: {val.get('action', '?')} {note}")
    if report.get("failure_issue"):
        fi = report["failure_issue"]
        extra = fi.get("issue") or fi.get("detail") or ""
        print(f"failure     : {fi.get('outcome')} {extra}")
    for note in report.get("notes", []):
        print(f"  - {note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gov 编排：①发现 → ②筛选 → ⑤学习 → ③监控（失败即停 + 失败 Issue）")
    parser.add_argument("--mode", choices=["daily", "deps"], default="daily",
                        help="daily=全链路；deps=仅月度依赖健康报告")
    parser.add_argument("--config", help="治理配置路径（缺省 scripts/gov/config.yml）")
    parser.add_argument("--create-issues", action="store_true",
                        help="允许告警/失败真正落地为 GitHub Issue")
    parser.add_argument("--sync-memory", action="store_true",
                        help="知识库经 gov-memory 分支往返（CI 专用）")
    parser.add_argument("--dry-run", action="store_true",
                        help="不动分支/不建 Issue/不写 run.json（阶段照常执行）")
    parser.add_argument("--print", dest="do_print", action="store_true",
                        help="打印摘要")
    args = parser.parse_args(argv)

    try:
        cfg = gconfig.load_config(args.config)
    except gconfig.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        report = run(cfg, mode=args.mode, create_issues=args.create_issues,
                     sync_memory=args.sync_memory, dry_run=args.dry_run,
                     config_path=args.config)
    except Exception as exc:  # noqa: BLE001 - CLI 兜底只做如实报告，不做"假装没事"
        print(f"error: gov-run failed: {exc}", file=sys.stderr)
        return 1

    if args.do_print or args.dry_run:
        _print_report(report)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
