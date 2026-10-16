"""⑤学习：shortlist A/B 级项目 → 浅克隆只读静态分析 → 项目卡（长期记忆）

数据流（对应 docs/governance-architecture.md §5）：

    reports/<date>/shortlist.json（②筛选产出，只取 A/B 级增量）
        └─ 浅克隆（depth=config.analysis.clone_depth）→ 只读静态分析
             ├─ 依赖清单（requirements*.txt 复用 ③monitor 的解析器 / pyproject PEP 621）
             ├─ 公共 API 面（ast 语法树，不 import、不 exec）
             ├─ 架构信号（测试/CI/文档/打包/顶层结构）
             ├─ 质量摘要（文件数/非空行数/AST 计数）与学习笔记
             └─ 许可证文件
        → vigilant-couscous/memory/knowledge/projects/<owner>__<repo>.json（项目卡）
        → reports/<date>/analysis.json（本轮运行报告，可重放）

四条硬约束
----------
1. **绝不执行候选代码**（config `analysis.never_execute`，run() 启动时复核）：
   全程只有两类动作——文件读取与 ast.parse。ast 只构造语法树、不求值；
   不 import 克隆里的任何模块、不装依赖、不跑 setup.py。测试里专门放了一个
   "模块级 open() 写文件"的源码文件，验证它不会被触发。
2. **增量**：知识库里已有项目卡的仓库直接跳过（无论卡为何种状态）——
   ⑤是"认识新朋友"，不是每天重新认识所有人。
3. **浅克隆要克制**：--depth=1 --single-branch --no-tags，禁用凭据助手
   （`credential.helper=` 置空：不弹 GCM、更不可能把令牌带进克隆），
   低速保护（<1KB/s 持续 60s 即放弃）防慢网拖死；克隆在临时目录完成并整目录清理，
   超时 300s 记 error 进报告——单项失败隔离，不拖垮整轮。
4. **单轮封顶**（config `analysis.max_projects_per_run`）：克隆是重操作，
   每轮只分析前 N 个新项目，其余显式记 `skipped_limit` 留给下一轮。

局限（v1 显式留白，写进卡片的 `quality.caveats`，不假装完整）
-------------------------------------------------------------
- 依赖只解析根级 `requirements*.txt`（与 ③monitor 同一解析口径）与
  `pyproject.toml` 的 PEP 621 `[project].dependencies`；poetry 布局、setup.py、
  `requirements/` 子目录不解析（命中时会在 caveats 里点名）。
- 许可证只记录文件名（"是什么证"交给 ②score 的 license 维度，搜索 API 已带）；
- `version_watched` 留空——版本跟踪是 ③monitor 的职责，首轮监控会建立基线。

用法
----
    python -m scripts.gov.analyze [--shortlist PATH] [--limit N] [--dry-run] [--print]

（必须 `python -m` 运行：脚本 import 了 scripts.gov 包，直接指路径会缺包。）
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from scripts.gov import config as gconfig
from scripts.gov import monitor
from scripts.gov import schemas
from scripts.gov import store

ANALYZER_ID = "gov-analyze/1"     # 分析口径版本戳：字段演进时下游可据此分辨
CLONE_TIMEOUT = 300               # 秒；超时按项目记 error
DEPS_CAP = 80
API_ENTRIES_CAP = 40
API_NAMES_PER_MODULE = 10
STRUCTURE_CAP = 20
SYNTAX_ERRORS_CAP = 3
READ_FAILURES_CAP = 5

# 依赖/生成物目录：扫了只会污染统计（.github 不在其中——CI 信号要看它）
VCS_DIRS = {".git", ".hg", ".svn"}
PRUNE_DIRS = VCS_DIRS | {
    "node_modules", ".venv", "venv", "__pycache__",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".eggs", ".idea", ".vs", "site-packages",
}

CloneFn = Callable[..., None]


# --------------------------------------------------------------------------
# 克隆（唯一的网络动作；可注入替换，测试全部离线）
# --------------------------------------------------------------------------
def _find_git() -> str | None:
    return shutil.which("git")


def _clone_repo(url: str, dest: Path, *, depth: int = 1,
                timeout: int = CLONE_TIMEOUT, git_exe: str | None = None) -> None:
    """浅克隆到 dest；失败抛 RuntimeError（由调用方记入报告，不静默跳过）。"""
    exe = git_exe or _find_git()
    if not exe:
        raise RuntimeError("未找到 git 可执行文件")
    cmd = [
        exe,
        "-c", "credential.helper=",       # 禁用凭据助手：不弹 GCM，不含任何令牌
        "-c", "http.lowSpeedLimit=1000",  # 低速保护：<1KB/s 持续 60s 即放弃
        "-c", "http.lowSpeedTime=60",
        "clone", "--quiet", f"--depth={int(depth)}", "--single-branch", "--no-tags",
        url, str(dest),
    ]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"克隆超时（{timeout}s）") from exc
    except subprocess.CalledProcessError as exc:
        tail = " ".join((exc.stderr or "").split())[-300:]
        raise RuntimeError(f"git clone 失败（rc={exc.returncode}）：{tail or url}") from exc


def _repo_url(entry: dict) -> str:
    url = str(entry.get("url") or "").strip()
    if not url:
        url = f"https://github.com/{entry.get('full_name', '')}"
    return url if url.endswith(".git") else url + ".git"


# --------------------------------------------------------------------------
# 只读静态分析（纯函数：目录进，信号出；可单独测试）
# --------------------------------------------------------------------------
def _inventory(root: Path) -> list[str]:
    """仓库全量文件清单（rel posix 路径）。只列目录树，不读内容。"""
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in PRUNE_DIRS and not d.endswith(".egg-info"))
        rel_dir = Path(dirpath).relative_to(root)
        for name in sorted(filenames):
            rel = name if str(rel_dir) == "." else f"{rel_dir.as_posix()}/{name}"
            files.append(rel)
    return files


def _suffix(rel: str) -> str:
    return Path(rel).suffix.lower()


def _is_manifest(low: str) -> bool:
    if low in ("pyproject.toml", "setup.py", "setup.cfg", "pipfile"):
        return True
    return low.startswith("requirements") and low.endswith(".txt")


def _is_test_file(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in ("tests", "test") for p in parts[:-1]):
        return True
    name = parts[-1]
    return name == "conftest.py" or (name.startswith("test_") and name.endswith(".py")) \
        or name.endswith("_test.py")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _top_structure(root: Path) -> list[str]:
    try:
        names = [n for n in sorted(os.listdir(root)) if n not in VCS_DIRS]
    except OSError:
        return []
    items = [f"{n}/" if (root / n).is_dir() else n for n in names]
    if len(items) > STRUCTURE_CAP:
        extra = len(items) - STRUCTURE_CAP
        items = items[:STRUCTURE_CAP] + [f"…(+{extra})"]
    return items


def _api_surface(texts: dict[str, str]) -> dict:
    """公共 API 面：ast 只解析不求值。只统计顶层公共 def/class 与 __all__ 字面量；
    测试文件不算公共 API（它们是自证材料，不是可整合面）。"""
    entries: list[str] = []
    modules: list[tuple[str, set[str]]] = []
    syntax_errors: list[str] = []
    classes = functions = parsed = 0
    for rel in sorted((f for f in texts if f.endswith(".py") and not _is_test_file(f)),
                      key=lambda f: (f.count("/"), f)):
        try:
            tree = ast.parse(texts[rel])
        except (SyntaxError, ValueError):
            syntax_errors.append(rel)
            continue
        parsed += 1
        names: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    names.add(node.name)
                    functions += 1
            elif isinstance(node, ast.ClassDef):
                if not node.name.startswith("_"):
                    names.add(node.name)
                    classes += 1
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "__all__":
                        try:
                            val = ast.literal_eval(node.value)
                        except (ValueError, SyntaxError, TypeError):
                            val = None
                        if isinstance(val, (list, tuple)):
                            names.update(x for x in val if isinstance(x, str))
        if names:
            modules.append((rel, names))

    for rel, names in modules[:API_ENTRIES_CAP]:
        shown = sorted(names)[:API_NAMES_PER_MODULE]
        tail = "…" if len(names) > API_NAMES_PER_MODULE else ""
        entries.append(f"{rel}: {', '.join(shown)}{tail}")

    return {
        "surface": entries,
        "files_parsed": parsed,
        "classes": classes,
        "functions": functions,
        "syntax_errors": syntax_errors[:SYNTAX_ERRORS_CAP],
        "truncated": len(modules) > API_ENTRIES_CAP,
    }


def _parse_deps(texts: dict[str, str], caveats: list[str]) -> tuple[list[str], list[str]]:
    """依赖清单 → (deps 规格串列表, 解析来源文件名列表)。口径与 ③monitor 一致。"""
    deps: list[str] = []
    deps_from: list[str] = []

    pyproject = texts.get("pyproject.toml")
    if pyproject is not None:
        data = None
        try:
            data = tomllib.loads(pyproject)
        except tomllib.TOMLDecodeError:
            caveats.append("pyproject.toml 不是合法 TOML：依赖未采集")
        if isinstance(data, dict):
            project = data.get("project") if isinstance(data.get("project"), dict) else {}
            reqs = project.get("dependencies") or []
            if reqs:
                deps += [str(x).strip() for x in reqs if str(x).strip()]
                deps_from.append("pyproject.toml")
            elif "poetry" in (data.get("tool") or {}):
                caveats.append("pyproject 为 poetry 布局：v1 只认 PEP 621 与 "
                               "requirements*.txt，依赖未采集")
            else:
                caveats.append("pyproject 无 [project].dependencies：依赖未采集")

    for rel in sorted(f for f in texts
                      if f.lower().startswith("requirements") and f.lower().endswith(".txt")):
        parsed = monitor.parse_requirements(texts[rel])  # 复用 ③ 的解析口径，不写第二个解析器
        got: list[str] = []
        unparsed = 0
        for row in parsed:
            if row.get("unparsed"):
                unparsed += 1
                continue
            spec = f"{row['name']}{row['spec']}".strip()
            if spec:
                got.append(spec)
        if got:
            deps += got
            deps_from.append(rel)
        if unparsed:
            caveats.append(f"{rel}: {unparsed} 行无法解析（如 URL/path 依赖），已跳过")

    deps = list(dict.fromkeys(deps))  # 去重保序
    if len(deps) > DEPS_CAP:
        caveats.append(f"依赖超过上限 {DEPS_CAP} 条，仅保留前 {DEPS_CAP}")
        deps = deps[:DEPS_CAP]
    return deps, deps_from


def analyze_tree(root: Path, *, include_extensions: tuple[str, ...] = (".py",),
                 max_files: int = 400, now: datetime | None = None) -> dict:
    """对克隆目录做只读静态分析，返回 {deps, api_surface, quality}。

    只读保证：本函数只有 read_text / ast.parse / os.walk / os.listdir，
    没有任何 import 子进程或执行候选代码的路径。
    """
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    exts = {e.lower() for e in include_extensions}
    caveats: list[str] = []

    files = _inventory(root)
    root_files = [f for f in files if "/" not in f]

    # ---- 根级特殊文件（清单/README/许可证）：永远读，不占代码扫描预算 ----
    specials: dict[str, str] = {}
    readme = license_file = ""
    manifests: list[str] = []
    for rel in root_files:
        low = rel.lower()
        if low.startswith("readme"):
            readme = readme or rel
            specials[rel] = "doc"
        elif low.startswith(("license", "copying")):
            license_file = license_file or rel
            specials[rel] = "doc"
        elif _is_manifest(low):
            manifests.append(rel)
            specials[rel] = "manifest"
    if (root / "requirements").is_dir():
        caveats.append("requirements/ 子目录清单未解析（v1 只读根级 requirements*.txt）")

    # ---- 代码文件：按（深度, 路径）排序，读满 max_files 即停 ----
    bulk = [f for f in files if f not in specials and _suffix(f) in exts]
    bulk.sort(key=lambda f: (f.count("/"), f))
    budget = max(int(max_files) - len(specials), 0)
    taken = bulk[:budget]
    truncated = len(bulk) > len(taken)
    if truncated:
        caveats.append(f"扫描上限截断：共 {len(bulk)} 个代码文件，仅读前 {len(taken)} 个"
                       f"（analysis.max_files_scanned={max_files}）")

    texts: dict[str, str] = {}
    read_failures = 0
    for rel in list(specials) + taken:
        text = _read_text(root / rel)
        if text is None:
            read_failures += 1
            if read_failures <= READ_FAILURES_CAP:
                caveats.append(f"文件读取失败（已跳过）：{rel}")
        else:
            texts[rel] = text

    # ---- 代码行数（非空行；只统计 include_extensions 内的代码文件）----
    code_files = [rel for rel in texts if _suffix(rel) in exts]
    loc = sum(1 for rel in code_files for line in texts[rel].splitlines() if line.strip())

    # ---- 公共 API 面（ast 语法树；只解析，不执行）----
    api = _api_surface(texts)
    if api["syntax_errors"]:
        caveats.append(f"AST 解析失败 {len(api['syntax_errors'])} 个文件"
                       f"（如 {api['syntax_errors'][0]}），已跳过其 API 面")
    if api["truncated"]:
        caveats.append(f"公共 API 面超过上限 {API_ENTRIES_CAP} 个模块，"
                       f"仅保留前 {API_ENTRIES_CAP}（按路径排序）")

    # ---- 依赖清单 ----
    deps, deps_from = _parse_deps(texts, caveats)

    # ---- 架构信号 ----
    has_tests = any(_is_test_file(f) for f in files)
    workflows = root / ".github" / "workflows"
    has_ci = workflows.is_dir() and any(
        p.suffix in (".yml", ".yaml") for p in workflows.iterdir() if p.is_file())
    has_docs = (root / "docs").is_dir() or (root / "doc").is_dir()

    quality = {
        "analyzer": ANALYZER_ID,
        "files_scanned": len(texts),
        "code_files": len(code_files),
        "truncated": truncated,
        "loc": loc,
        "tests": has_tests,
        "ci": has_ci,
        "docs_dir": has_docs,
        "readme": readme,
        "readme_chars": len(texts.get(readme, "")) if readme else 0,
        "license_file": license_file,
        "manifests": sorted(manifests),
        "deps_from": deps_from,
        "structure": _top_structure(root),
        "api": {
            "files_parsed": api["files_parsed"],
            "classes": api["classes"],
            "functions": api["functions"],
            "syntax_errors": api["syntax_errors"],
        },
        "caveats": caveats,
        "analyzed_at": now.isoformat(),
    }
    return {"deps": deps, "api_surface": api["surface"], "quality": quality}


# --------------------------------------------------------------------------
# 项目卡与学习笔记
# --------------------------------------------------------------------------
def _build_note(entry: dict, quality: dict, n_deps: int) -> str:
    """学习笔记（人类可读摘要；P7 整合时由人/提案消费，不放模型幻觉，只用信号）。"""
    lang = str(entry.get("language") or "").strip() or "未知语言"
    flags = [label for label, ok in (("测试", quality["tests"]), ("CI", quality["ci"]),
                                     ("文档", quality["docs_dir"])) if ok]
    bits = [
        f"{lang} 项目，读取 {quality['files_scanned']} 个文件、约 {quality['loc']} 行代码",
        ("具备 " + "、".join(flags) + " 信号") if flags else "未见测试/CI/文档信号",
    ]
    if n_deps:
        bits.append(f"可解析依赖 {n_deps} 条（{', '.join(quality['deps_from']) or '—'}）")
    api = quality["api"]
    if api["classes"] or api["functions"]:
        bits.append(f"顶层公共类/函数 {api['classes']}/{api['functions']}")
    if quality["license_file"]:
        bits.append(f"含许可证文件 {quality['license_file']}")
    return "；".join(bits) + "。"


def _build_card(entry: dict, signals: dict, *, now_iso: str, depth: int) -> dict:
    quality = signals["quality"]
    name = str(entry["full_name"])
    reason = (
        f"⑤学习完成：浅克隆 depth={depth} 只读分析；"
        f"{quality['files_scanned']} 文件读取 / {quality['loc']} 行代码 / "
        f"依赖 {len(signals['deps'])} 条 / API 面 {len(signals['api_surface'])} 条"
    )
    return schemas.new_record(
        "project_card",
        name=name,
        url=str(entry.get("url") or f"https://github.com/{name}"),
        domain=str(entry.get("domain") or ""),
        status="analyzed",
        score=round(float(entry.get("score") or 0.0), 2),
        tier=str(entry.get("tier") or "C"),
        version_watched="",  # 版本跟踪归 ③monitor：首轮监控建立基线
        deps=list(signals["deps"]),
        api_surface=list(signals["api_surface"]),
        quality=quality,
        license=str(entry.get("license") or ""),
        first_seen=str(entry.get("discovered_at") or now_iso),
        last_checked=now_iso,
        reason=reason,
    )


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def _date_dirs() -> list[Path]:
    base = Path(store.REPORTS_DIR)
    if not base.is_dir():
        return []
    return sorted((p for p in base.iterdir() if p.is_dir()),
                  key=lambda p: p.name, reverse=True)


def _latest_shortlist() -> Path | None:
    for d in _date_dirs():
        f = d / "shortlist.json"
        if f.exists():
            return f
    return None


def run(
    cfg: dict,
    *,
    write: bool = True,
    now: datetime | None = None,
    limit: int | None = None,
    shortlist_path: Path | str | None = None,
    clone_fn: CloneFn | None = None,
) -> dict:
    """执行一轮学习：shortlist(A/B 增量) → 浅克隆只读分析 → 项目卡。

    write=False（--dry-run）时项目卡与报告都不落盘（克隆与分析照常执行）。
    返回报告：{generated_at, status, source, limit, count_ab, analyzed,
    skipped_existing, skipped_limit, entries, notes, errors}
    """
    now = now or datetime.now(timezone.utc)
    date = now.strftime("%Y-%m-%d")
    now_iso = now.isoformat()
    analysis = cfg.get("analysis") or {}

    # 安全边界启动复核（config.py 校验已拦一道；run 可能被直接调用，这里是第二道）
    if analysis.get("never_execute") is not True:
        raise gconfig.ConfigError(
            "analysis.never_execute 未启用——analyze 拒绝运行"
            "（治理系统对候选代码只读分析，绝不执行）")

    depth = int(analysis.get("clone_depth", 1))
    max_files = int(analysis.get("max_files_scanned", 400))
    exts = tuple(str(e) for e in (analysis.get("include_extensions") or (".py",)))
    lim = int(analysis.get("max_projects_per_run", 3)) if limit is None else int(limit)

    errors: list[str] = []
    notes: list[str] = []
    entries_out: list[dict] = []
    analyzed = skipped_existing = skipped_limit = 0

    # ---- 输入：最新一期 shortlist（显式路径缺失按错误处理，自动发现缺失属冷启动）----
    kind = "file" if shortlist_path is not None else "latest"
    path = Path(shortlist_path) if shortlist_path is not None else _latest_shortlist()
    if path is None:
        report = {
            "generated_at": now_iso, "status": "skipped",
            "source": {"kind": kind, "path": "", "date": ""},
            "limit": lim, "count_ab": 0, "analyzed": 0, "skipped_existing": 0,
            "skipped_limit": 0, "entries": [],
            "notes": ["未找到 shortlist.json（先跑 ①discover + ②score；冷启动跳过属正常）"],
            "errors": [],
        }
        if write:
            store.write_json(report, "analysis.json", date=date)
        return report

    data = store.read_json(path)
    source = {"kind": kind, "path": str(path), "date": path.parent.name}
    entries = [e for e in (data.get("entries") or []) if isinstance(e, dict)]
    ab = [e for e in entries if e.get("tier") in ("A", "B")]
    c_count = len(entries) - len(ab)

    known = set(store.list_project_cards(cfg))
    fresh: list[dict] = []
    for e in ab:
        name = str(e.get("full_name") or "")
        if not name:
            msg = f"tier {e.get('tier')} 条目缺 full_name，无法建档"
            errors.append(msg)
            entries_out.append({"name": "", "tier": e.get("tier"),
                                "score": e.get("score"), "status": "error", "error": msg})
            continue
        if name in known:
            skipped_existing += 1
            entries_out.append({"name": name, "tier": e.get("tier"),
                                "score": e.get("score"), "status": "skipped_existing"})
            continue
        fresh.append(e)

    selected = fresh[:lim]
    for e in fresh[lim:]:
        skipped_limit += 1
        entries_out.append({"name": e["full_name"], "tier": e.get("tier"),
                            "score": e.get("score"), "status": "skipped_limit"})

    git_exe = None if clone_fn is not None else _find_git()

    for e in selected:
        name = str(e["full_name"])
        if clone_fn is None and git_exe is None:
            msg = "git 不可用（未找到 git 可执行文件），未克隆"
            errors.append(f"{name}: {msg}")
            entries_out.append({"name": name, "tier": e.get("tier"), "score": e.get("score"),
                                "status": "error", "error": msg})
            continue
        try:
            with tempfile.TemporaryDirectory(prefix="gov-analyze-",
                                             ignore_cleanup_errors=True) as tmp:
                dest = Path(tmp) / "repo"
                cloner = clone_fn or _clone_repo
                cloner(_repo_url(e), dest, depth=depth, timeout=CLONE_TIMEOUT)
                signals = analyze_tree(dest, include_extensions=exts,
                                       max_files=max_files, now=now)
            signals["quality"]["note"] = _build_note(e, signals["quality"],
                                                     len(signals["deps"]))
            card = _build_card(e, signals, now_iso=now_iso, depth=depth)
            card_path = store.projects_dir(cfg) / store.card_filename(name)
            if write:
                card_path = store.save_project_card(card, cfg)
        except Exception as exc:  # noqa: BLE001 —— 单项失败隔离：显式记 error，不拖垮整轮
            msg = f"{type(exc).__name__}: {exc}"
            errors.append(f"{name}: {msg}")
            entries_out.append({"name": name, "tier": e.get("tier"), "score": e.get("score"),
                                "status": "error", "error": msg})
            continue
        analyzed += 1
        entries_out.append({
            "name": name, "tier": card["tier"], "score": card["score"], "status": "ok",
            "card": str(card_path), "note": signals["quality"]["note"],
            "summary": (f"files={signals['quality']['files_scanned']} "
                        f"loc={signals['quality']['loc']} deps={len(signals['deps'])} "
                        f"api={signals['quality']['api']['files_parsed']}"),
            "quality": signals["quality"],
        })

    if errors and analyzed:
        status = "partial"
    elif errors and not analyzed:
        status = "failed"
    else:
        status = "ok"

    notes.append(f"A/B 候选 {len(ab)} 个；已有项目卡跳过 {skipped_existing}；"
                 f"本轮上限 {lim}（analysis.max_projects_per_run）")
    if c_count:
        notes.append(f"C 级 {c_count} 个不参与学习（⑤ 只做 A/B 增量）")
    if source["date"] != date:
        notes.append(f"最新一期 shortlist 为 {source['date']}"
                     "（今日无新产物，按最新可用计算）")
    notes.append(f"克隆 depth={depth}；全程只读分析，不执行候选代码（never_execute 已复核）")

    report = {
        "generated_at": now_iso,
        "status": status,
        "source": source,
        "limit": lim,
        "count_ab": len(ab),
        "analyzed": analyzed,
        "skipped_existing": skipped_existing,
        "skipped_limit": skipped_limit,
        "entries": entries_out,
        "notes": notes,
        "errors": errors,
    }
    if write:
        store.write_json(report, "analysis.json", date=date)
    return report


def _print_report(report: dict) -> None:
    print("=== Gov Analyze ===")
    print(f"status      : {report['status']}")
    if report["source"]["path"]:
        print(f"source      : {report['source']['path']} (date {report['source']['date']})")
    print(f"limit       : {report['limit']}")
    print(f"analyzed    : {report['analyzed']} "
          f"(skipped_existing {report['skipped_existing']} / "
          f"skipped_limit {report['skipped_limit']})")
    for e in report["entries"]:
        if e["status"] == "ok":
            print(f"  ✓ {e['name']}  {e['tier']} {float(e['score']):>6.2f}  {e['summary']}")
        elif e["status"] == "error":
            print(f"  ! {e['name'] or '<无名称>'}: {e['error']}")
    for n in report["notes"]:
        print(f"  - {n}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gov ⑤学习：shortlist A/B → 浅克隆只读分析 → 项目卡")
    parser.add_argument("--config", default=str(gconfig.DEFAULT_CONFIG), help="治理配置路径")
    parser.add_argument("--shortlist", default=None, help="shortlist.json 路径（缺省取最新一期）")
    parser.add_argument("--limit", type=int, default=None, help="本轮分析上限（缺省取配置）")
    parser.add_argument("--dry-run", action="store_true", help="不落盘（克隆与分析照常执行）")
    parser.add_argument("--print", dest="do_print", action="store_true", help="打印摘要")
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        print("error: --limit 必须 ≥ 1", file=sys.stderr)
        return 2

    try:
        cfg = gconfig.load_config(args.config)
    except gconfig.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        report = run(cfg, write=not args.dry_run, limit=args.limit,
                     shortlist_path=args.shortlist)
    except gconfig.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.do_print or args.dry_run:
        _print_report(report)
    return 0 if report["status"] in ("ok", "partial", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
