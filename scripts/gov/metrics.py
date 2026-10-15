"""治理度量采集器（P5 合并产物 + P6 scripts/gov 雏形）

背景
----
仓库原有 mon-*(10) + q-*(10) 共 20 个工作流承担"度量"职责，但存在两个硬伤：
1. 大量是 echo 纯桩——mon-health 只输出三行 "✅ xxx is operational"；
2. 少数装了真工具（radon/pylint/linkchecker/codespell/yamllint/pytest-cov），
   但全部以 `|| echo '...'` 兜底，度量结果只进日志、**永不持久化**（原样 EOF），
   且每个工作流各自一份环境变量与依赖安装，重复消耗 Actions 分钟数。

本模块把这批职责收敛为一次采集：
- 每个度量函数返回 MetricResult，独立 try/except——**任一失败不影响其他度量**；
- 外部工具缺失时返回 status="skipped"（并注明原因），而非报错；
- 结果统一序列化为 reports/metrics-<date>.json，由 gov-metrics.yml 以 artifact
  持久化（原 20 个工作流的输出散落在日志里，次日即不可查）。

有意未收编的能力：
- pytest 覆盖率：ci.yml 的 --cov-fail-under 是更严的真门禁，此处不重复跑；
- linkchecker：依赖外网且噪声高，保留为 opts 开关，默认不跑。

用法
----
    python scripts/gov/metrics.py                      # 采集 + 写 reports/
    python scripts/gov/metrics.py --print              # 同时终端输出摘要
    python scripts/gov/metrics.py --out path.json      # 指定输出
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

GOV_DIR = Path(__file__).resolve().parent
REPO_ROOT = GOV_DIR.parent.parent
REPORTS_DIR = REPO_ROOT / "reports"

SOURCE_DIRS = ("backend", "scripts", "tests", "vigilant-couscous")
SKIP_PARTS = ("__pycache__", ".git", "node_modules", ".venv", "venv")

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


@dataclass
class MetricResult:
    """单个度量的采集结果

    status: ok(真数据) / skipped(工具或输入缺失) / failed(采集中抛异常)
    data:   结构化真数据，只放可 JSON 序列化的值
    note:   失败或跳过的原因说明
    """

    name: str
    status: str
    data: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _iter_files(root: Path, pattern: str = "*.py", dirs: tuple = SOURCE_DIRS) -> Iterator[Path]:
    for d in dirs:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob(pattern)):
            if any(part in SKIP_PARTS for part in p.parts):
                continue
            yield p


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# --------------------------------------------------------------------------
# 纯 Python 度量（无外部依赖，任何环境都能跑出真数据）
# --------------------------------------------------------------------------
def m_code_stats(root: Path = REPO_ROOT) -> MetricResult:
    """代码规模：Python 文件数、有效行数（去空行与纯注释行）、测试文件数"""
    files = list(_iter_files(root))
    lines = 0
    for p in files:
        for line in _read(p).splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                lines += 1
    tests = [p for p in files if p.name.startswith("test_")]
    return MetricResult(
        "code_stats", STATUS_OK,
        {"python_files": len(files), "python_lines": lines, "test_files": len(tests)},
    )


def m_todo_scan(root: Path = REPO_ROOT) -> MetricResult:
    """TODO/FIXME/HACK 债务扫描，返回总数与热点文件 Top 5"""
    pattern = re.compile(r"\b(TODO|FIXME|HACK)\b")
    total = 0
    hot: dict[str, int] = {}
    for p in _iter_files(root):
        hits = len(pattern.findall(_read(p)))
        if hits:
            total += hits
            hot[str(p.relative_to(root))] = hits
    top = sorted(hot.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return MetricResult("todo_scan", STATUS_OK, {"total": total, "hot_files": top})


def m_header_check(root: Path = REPO_ROOT) -> MetricResult:
    """缺失模块级 docstring 的 Python 文件列表（上限 20，按路径排序）"""
    missing: list[str] = []
    checked = 0
    for p in _iter_files(root):
        text = _read(p)
        if not text.strip():
            continue
        checked += 1
        try:
            if ast.get_docstring(ast.parse(text)) is None:
                missing.append(str(p.relative_to(root)))
        except SyntaxError:
            missing.append(str(p.relative_to(root)) + " (syntax-error)")
    return MetricResult(
        "header_check", STATUS_OK,
        {"checked": checked, "missing_docstring": missing[:20], "count": len(missing)},
    )


def m_docs_existence(root: Path = REPO_ROOT) -> MetricResult:
    """关键文档是否齐备（承继 q-docs.yml 的职责，但给出逐项真值）"""
    expected = ["README.md", "CONTRIBUTING.md", "LICENSE", "SECURITY.md", "docs"]
    present = {name: (root / name).exists() for name in expected}
    return MetricResult(
        "docs_existence", STATUS_OK,
        {"present": present, "all_present": all(present.values())},
    )


def m_repo_size(root: Path = REPO_ROOT) -> MetricResult:
    """仓库体积（MB），排除 .git / __pycache__ / node_modules"""
    total = 0
    files = 0
    for p in root.rglob("*"):
        if any(part in SKIP_PARTS for part in p.parts) or not p.is_file():
            continue
        total += p.stat().st_size
        files += 1
    return MetricResult("repo_size", STATUS_OK,
                        {"bytes": total, "mb": round(total / 1_048_576, 2), "files": files})


def m_yaml_lint(root: Path = REPO_ROOT) -> MetricResult:
    """.github 下 YAML 配置语法校验（纯 PyYAML，替代需额外装 yamllint 的方式）"""
    try:
        import yaml  # 采集器内部延迟导入，避免无 PyYAML 时整个模块 import 失败
    except ImportError:
        return MetricResult("yaml_lint", STATUS_SKIPPED, {}, "PyYAML 未安装")

    targets = sorted((root / ".github").rglob("*.yml"))
    invalid: list[str] = []
    for p in targets:
        try:
            yaml.safe_load(_read(p))
        except Exception as exc:  # noqa: BLE001  # 采集器需宽容：记录而非抛出
            invalid.append(f"{p.relative_to(root)}: {exc.__class__.__name__}")
    return MetricResult(
        "yaml_lint", STATUS_OK,
        {"checked": len(targets), "invalid": invalid, "count": len(invalid)},
    )


# --------------------------------------------------------------------------
# 依赖外部工具的度量（缺失则返回 skipped，不影响整体采集）
# --------------------------------------------------------------------------
def _tool_available(tool: str) -> bool:
    return shutil.which(tool) is not None


def m_complexity(root: Path = REPO_ROOT) -> MetricResult:
    """圈复杂度均值（radon）；工具缺失时跳过"""
    if not _tool_available("radon"):
        return MetricResult("complexity", STATUS_SKIPPED, {}, "radon 未安装")

    blocks = 0
    averages: list[float] = []
    for d in SOURCE_DIRS:
        if not (root / d).is_dir():
            continue
        proc = subprocess.run(  # noqa: S603  # 输入为仓库内固定目录
            ["radon", "cc", "-a", "-s", d],
            cwd=str(root), capture_output=True, text=True, timeout=300,
        )
        out = proc.stdout or ""
        m = re.search(r"Average complexity:\s*\w+\s*\(([\d.]+)\)", out)
        if m:
            averages.append(float(m.group(1)))
        n = re.search(r"(\d+)\s+blocks?\s+\(classes, functions, methods\)", out)
        if n:
            blocks += int(n.group(1))
    if not averages:
        return MetricResult("complexity", STATUS_SKIPPED, {}, "radon 无输出（无可分析代码块）")
    return MetricResult(
        "complexity", STATUS_OK,
        {"blocks": blocks, "average_complexity": round(sum(averages) / len(averages), 3)},
    )


def m_spellcheck(root: Path = REPO_ROOT) -> MetricResult:
    """拼写检查（codespell）；工具缺失时跳过"""
    if not _tool_available("codespell"):
        return MetricResult("spellcheck", STATUS_SKIPPED, {}, "codespell 未安装")
    proc = subprocess.run(  # noqa: S603
        ["codespell", "--quiet-level=2", *[d for d in SOURCE_DIRS if (root / d).is_dir()],
         "README.md", "docs"],
        cwd=str(root), capture_output=True, text=True, timeout=300,
    )
    findings = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    # codespell 有发现时返回码非 0，此处视为采集成功
    return MetricResult("spellcheck", STATUS_OK, {"findings": len(findings),
                                                  "samples": findings[:10]})


# --------------------------------------------------------------------------
# 依赖 GitHub API 的度量（无 token 或断网时跳过）
# --------------------------------------------------------------------------
def m_github_api(root: Path = REPO_ROOT) -> MetricResult:
    """仓库运营指标：stars / open issues / 失败率（承继 mon-stats、mon-workflows）

    需要环境变量 GITHUB_TOKEN 与 GITHUB_REPOSITORY；任一缺失或网络异常则跳过。
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return MetricResult("github_api", STATUS_SKIPPED, {}, "缺少 GITHUB_TOKEN/REPOSITORY")

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "User-Agent": "gov-metrics"}
    try:
        with urllib.request.urlopen(  # noqa: S310  # 固定 https API 域名
                urllib.request.Request(f"https://api.github.com/repos/{repo}", headers=headers),
                timeout=15) as resp:
            repo_data = json.load(resp)
        with urllib.request.urlopen(  # noqa: S310
                urllib.request.Request(
                    f"https://api.github.com/repos/{repo}/actions/runs?per_page=50",
                    headers=headers), timeout=15) as resp:
            runs = json.load(resp).get("workflow_runs", [])
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return MetricResult("github_api", STATUS_SKIPPED, {}, f"API 不可达: {exc}")

    finished = [r for r in runs if r.get("status") == "completed"]
    failed = [r for r in finished if r.get("conclusion") == "failure"]
    return MetricResult("github_api", STATUS_OK, {
        "stars": repo_data.get("stargazers_count"),
        "open_issues": repo_data.get("open_issues_count"),
        "size_kb": repo_data.get("size"),
        "recent_runs": len(runs),
        "failure_rate": round(len(failed) / len(finished), 3) if finished else 0.0,
    })


METRICS = (
    m_code_stats, m_todo_scan, m_header_check, m_docs_existence, m_repo_size,
    m_yaml_lint, m_complexity, m_spellcheck, m_github_api,
)


def collect_all(root: Path = REPO_ROOT) -> dict:
    """串行执行所有度量；单个度量抛异常时降级为 failed 并继续"""
    results: list[MetricResult] = []
    for fn in METRICS:
        try:
            results.append(fn(root))
        except Exception as exc:  # noqa: BLE001  # 采集器不得因单点异常中断
            results.append(MetricResult(getattr(fn, "__name__", "?"), STATUS_FAILED, {},
                                        f"{exc.__class__.__name__}: {exc}"))
    counts = {
        STATUS_OK: sum(1 for r in results if r.status == STATUS_OK),
        STATUS_SKIPPED: sum(1 for r in results if r.status == STATUS_SKIPPED),
        STATUS_FAILED: sum(1 for r in results if r.status == STATUS_FAILED),
    }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root),
        "summary": {"total": len(results), **counts},
        "metrics": [r.to_dict() for r in results],
    }


def _dump(report: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_report(report: dict, root: Path = REPO_ROOT) -> Path:
    """按日期落到 <root>/reports/metrics-<date>.json（该目录已被 .gitignore 忽略）"""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _dump(report, root / "reports" / f"metrics-{date}.json")


def _print_summary(report: dict) -> None:
    print("=== Gov Metrics ===")
    print(f"generated_at: {report['generated_at']}")
    print(f"summary:      {report['summary']}")
    for m in report["metrics"]:
        flag = {"ok": "[OK]", "skipped": "[--]", "failed": "[!!]"}[m["status"]]
        extra = m["note"] or str(m["data"])[:90]
        print(f"  {flag} {m['name']:16s} {extra}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="治理度量采集器")
    parser.add_argument("--out", help="输出 JSON 路径（默认 reports/metrics-<date>.json）")
    parser.add_argument("--print", dest="do_print", action="store_true", help="终端输出摘要")
    parser.add_argument("--root", default=str(REPO_ROOT), help="采集目标仓库根（测试用）")
    parser.add_argument("--fail-on-failed", action="store_true",
                        help="任一度量自身抛异常时返回非 0")
    args = parser.parse_args(argv)

    report = collect_all(Path(args.root))
    if args.out:
        out = _dump(report, Path(args.out))
    else:
        out = write_report(report, Path(args.root))
    print(f"report written: {out}")

    if args.do_print:
        _print_summary(report)

    if args.fail_on_failed and report["summary"].get(STATUS_FAILED, 0) > 0:
        print("error: 存在 failed 度量", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
