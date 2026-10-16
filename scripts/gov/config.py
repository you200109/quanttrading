"""治理配置加载与校验（scripts/gov/config.yml）

立场：配置缺失/写错必须当场报错退出，不做"静默取默认值"。
理由很直接——这一路上清掉的失效模式，一半是「没配置却假装有一个默认值」：
labeler.yml 不存在时 continue-on-error 让它悄悄通过了两年，auto-label 的
路径维度标签从未生效。治理系统如果继承这个毛病，它所有的自律都是假的。

用法
----
    from scripts.gov import config
    cfg = config.load_config()                 # 默认读 scripts/gov/config.yml
    cfg = config.load_config(Path(".../tmp.yml"))
    n   = config.get(cfg, "discovery.per_keyword_limit")
    PHI = config.get(cfg, "analysis.never_execute")   # 安全边界，analyze.py 必读

CLI：
    python scripts/gov/config.py [--config PATH]     # 校验并打印摘要
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

GOV_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = GOV_DIR / "config.yml"

SUPPORTED_SCHEMA_VERSIONS = (1,)

RELEASE_KINDS = ("release", "tag", "version")


class ConfigError(Exception):
    """配置缺失、类型错误或取值非法"""


# --------------------------------------------------------------------------
# 结构规格：(期望类型或取值集合, 是否必需)
# --------------------------------------------------------------------------
def _t(t: type, optional: bool = False) -> tuple:
    return (t, optional)


TOP_SPEC: dict[str, tuple] = {
    "schema_version": _t(int),
    "discovery": _t(dict),
    "scoring": _t(dict),
    "monitoring": _t(dict),
    "analysis": _t(dict),
    "knowledge": _t(dict),
}

DISCOVERY_SPEC: dict[str, tuple] = {
    "per_keyword_limit": _t(int),
    "max_requests_per_run": _t(int),
    "domains": _t(dict),
    "filters": _t(dict),
}

FILTER_SPEC: dict[str, tuple] = {
    "min_stars": _t(int),
    "pushed_within_days": _t(int),
    "exclude_forks": _t(bool),
    "exclude_archived": _t(bool),
}

DOMAIN_SPEC: dict[str, tuple] = {
    "enabled": _t(bool),
    "keywords": _t(list),
    "topics": _t(list),
}

SCORING_SPEC: dict[str, tuple] = {
    "weights": _t(dict),
    "tiers": _t(dict),
    "whitelist": _t(list),
    "blacklist": _t(list),
}

MONITORING_SPEC: dict[str, tuple] = {
    "self_repo": _t(str),
    "max_requests_per_run": _t(int),
    "watched": _t(list),
    "self_requirements": _t(list),
    "alerts": _t(dict),
}

ALERT_SPEC: dict[str, tuple] = {
    "max_open_alerts": _t(int),
    "ci_success_floor": _t(float),
    "coverage_floor": _t(int),
}

ANALYSIS_SPEC: dict[str, tuple] = {
    "clone_depth": _t(int),
    "max_files_scanned": _t(int),
    "include_extensions": _t(list),
    "never_execute": _t(bool),
}

KNOWLEDGE_SPEC: dict[str, tuple] = {
    "root": _t(str),
    "decisions_file": _t(str),
}


def _check(cfg: dict, spec: dict, trail: str) -> list[str]:
    """按 spec 校验，返回问题描述列表（空=通过）"""
    problems: list[str] = []
    for key, (expected, optional) in spec.items():
        if key not in cfg:
            if not optional:
                problems.append(f"{trail}{key}: 缺失（期望 {expected.__name__}）")
            continue
        value = cfg[key]
        # float 位点同时接受 int（YAML 里 40 会被解析成 int）
        if expected is float and isinstance(value, int) and not isinstance(value, bool):
            continue
        if expected is int and isinstance(value, bool):
            problems.append(f"{trail}{key}: 期望 int，实际 bool({value!r})")
            continue
        if not isinstance(value, expected):
            problems.append(
                f"{trail}{key}: 期望 {expected.__name__}，实际 {type(value).__name__}({value!r})")
    return problems


def validate(cfg: dict) -> list[str]:
    """全量校验，一次返回所有问题（不全在第一处就退出，省得来回改十轮）"""
    problems: list[str] = []
    if not isinstance(cfg, dict):
        return [f"<root>: 期望 dict，实际 {type(cfg).__name__}"]

    problems += _check(cfg, TOP_SPEC, "")

    version = cfg.get("schema_version")
    if isinstance(version, int) and version not in SUPPORTED_SCHEMA_VERSIONS:
        problems.append(f"schema_version: 不支持的版本 {version}"
                        f"（支持 {list(SUPPORTED_SCHEMA_VERSIONS)}）")

    discovery = cfg.get("discovery")
    if isinstance(discovery, dict):
        problems += _check(discovery, DISCOVERY_SPEC, "discovery.")
        domains = discovery.get("domains")
        if isinstance(domains, dict):
            if not domains:
                problems.append("discovery.domains: 至少需要一个域")
            for name, dom in domains.items():
                if not isinstance(dom, dict):
                    problems.append(f"discovery.domains.{name}: 期望 dict")
                    continue
                problems += _check(dom, DOMAIN_SPEC, f"discovery.domains.{name}.")
                for key in ("keywords", "topics"):
                    seq = dom.get(key)
                    if isinstance(seq, list) and any(not isinstance(x, str) for x in seq):
                        problems.append(f"discovery.domains.{name}.{key}: 元素必须全是 str")
        filters = discovery.get("filters")
        if isinstance(filters, dict):
            problems += _check(filters, FILTER_SPEC, "discovery.filters.")

    scoring = cfg.get("scoring")
    if isinstance(scoring, dict):
        problems += _check(scoring, SCORING_SPEC, "scoring.")
        weights = scoring.get("weights")
        if isinstance(weights, dict):
            if not weights:
                problems.append("scoring.weights: 至少一个维度")
            for dim, w in weights.items():
                if isinstance(w, bool) or not isinstance(w, (int, float)):
                    problems.append(f"scoring.weights.{dim}: 权重必须是数值，实际 {w!r}")
        tiers = scoring.get("tiers")
        if isinstance(tiers, dict):
            if not set(tiers) >= {"A", "B", "C"}:
                problems.append("scoring.tiers: 必须包含 A/B/C 三档")

    monitoring = cfg.get("monitoring")
    if isinstance(monitoring, dict):
        problems += _check(monitoring, MONITORING_SPEC, "monitoring.")
        watched = monitoring.get("watched")
        if isinstance(watched, list):
            for i, item in enumerate(watched):
                if not isinstance(item, dict) or "repo" not in item:
                    problems.append(f"monitoring.watched[{i}]: 需要 {{repo, kind}} 结构")
                    continue
                kind = item.get("kind")
                if kind not in RELEASE_KINDS:
                    problems.append(
                        f"monitoring.watched[{i}].kind: {kind!r} 不在 {list(RELEASE_KINDS)}")
        alerts = monitoring.get("alerts")
        if isinstance(alerts, dict):
            problems += _check(alerts, ALERT_SPEC, "monitoring.alerts.")

    analysis = cfg.get("analysis")
    if isinstance(analysis, dict):
        problems += _check(analysis, ANALYSIS_SPEC, "analysis.")
        # 安全边界：never_execute 一旦被改成 false，必须当场拦住
        if "never_execute" in analysis and analysis["never_execute"] is not True:
            problems.append("analysis.never_execute: 必须为 true"
                            "——治理系统对候选代码只读分析，绝不执行")

    knowledge = cfg.get("knowledge")
    if isinstance(knowledge, dict):
        problems += _check(knowledge, KNOWLEDGE_SPEC, "knowledge.")

    return problems


def load_config(path: Path | str | None = None, strict: bool = True) -> dict:
    """读取并校验配置。strict=True 时任何问题都抛 ConfigError"""
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    if not cfg_path.exists():
        raise ConfigError(f"配置文件不存在: {cfg_path}")

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - 视环境而定
        raise ConfigError(
            "PyYAML 未安装，无法解析治理配置（pip install -r requirements-gov.txt）"
        ) from exc

    raw = cfg_path.read_text(encoding="utf-8")
    try:
        cfg = yaml.safe_load(raw)
    except Exception as exc:
        raise ConfigError(f"YAML 解析失败 {cfg_path}: {exc}") from exc

    if cfg is None:
        raise ConfigError(f"配置文件为空: {cfg_path}")

    problems = validate(cfg)
    if problems and strict:
        joined = "\n  - ".join(problems)
        raise ConfigError(f"配置校验失败 {cfg_path}:\n  - {joined}")
    return cfg


def get(cfg: dict, dotted: str, default: Any = None) -> Any:
    """点号取值，如 get(cfg, "monitoring.alerts.coverage_floor")"""
    cur: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def summary(cfg: dict) -> str:
    """人类可读摘要（CI 日志/CLI 用）"""
    problems = validate(cfg)
    domains = cfg.get("discovery", {}).get("domains", {}) or {}
    lines = [
        f"config      : {'OK' if not problems else str(len(problems)) + ' problems'}",
        f"schema      : {cfg.get('schema_version')}",
        f"domains     : {len(domains)} ({', '.join(sorted(domains))})",
        f"per_keyword : {get(cfg, 'discovery.per_keyword_limit')}"
        f" / max_requests {get(cfg, 'discovery.max_requests_per_run')}",
        f"min_stars   : {get(cfg, 'discovery.filters.min_stars')}"
        f" / pushed_within {get(cfg, 'discovery.filters.pushed_within_days')}d",
        f"tiers       : {get(cfg, 'scoring.tiers')}",
        f"watched     : {len(cfg.get('monitoring', {}).get('watched', []) or [])} repos",
        f"knowledge   : {get(cfg, 'knowledge.root')}",
        f"never_exec  : {get(cfg, 'analysis.never_execute')}",
    ]
    if problems:
        lines += ["problems:"] + [f"  - {p}" for p in problems]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="治理配置校验")
    parser.add_argument("--config", help="配置文件路径（默认 scripts/gov/config.yml）")
    parser.add_argument("--no-strict", action="store_true", help="仅打印问题，不按失败退出")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config, strict=False)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("=== Gov Config ===")
    print(summary(cfg))
    return 0 if not validate(cfg) or args.no_strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
