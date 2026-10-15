"""治理数据契约（对应 docs/AUDIT_AND_REFACTOR_PLAN.md §5.3）

为什么不用 jsonschema：
1. 不想为一个内部契约再引第三方依赖（治理工具链已经够长了）；
2. 需要的是"一次性报出全部问题 + 给出缺字段默认值"，这套自定义小实现
   200 行就能覆盖，且能被 tests/test_gov_core.py 完整测到。

四类契约：
    candidate       ①发现产出：候选仓库原始信息
    project_card    知识库里的项目卡（长期记忆，跨运行累积）
    metric_record   ④度量/③监控产出：单次运行的度量快照
    decision_record ⑦演进产出：一次提案→行动→结果的完整轨迹

用法
----
    rec = schemas.new_record("candidate", full_name="o/r", url=..., stars=1)
    schemas.validate("candidate", rec)          # 有问题抛 SchemaError
    problems = schemas.problems("candidate", {})  # 只收集不抛
"""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable

KINDS = ("candidate", "project_card", "metric_record", "decision_record")

PROJECT_STATUS = ("discovered", "analyzed", "approved", "integrated", "rejected", "dropped")
TIERS = ("A", "B", "C")
DECISION_OUTCOMES = ("pending", "merged", "rejected", "ci_failed", "superseded")

_SEMVER = re.compile(r"^v?\d+(\.\d+){0,3}([-+][0-9A-Za-z.\-]+)?$")
_FULL_NAME = re.compile(r"^[^/\s]+/[^/\s]+$")

_TYPE_NAMES = {
    str: "str", int: "int", float: "float", bool: "bool",
    list: "list", dict: "dict",
}


class SchemaError(Exception):
    """契约校验失败"""


def _typename(t: Any) -> str:
    if isinstance(t, tuple):
        return "|".join(_typename(x) for x in t)
    return _TYPE_NAMES.get(t, getattr(t, "__name__", str(t)))


def _type_ok(value: Any, expected: Any) -> bool:
    if expected is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is bool:
        return isinstance(value, bool)
    if expected is str:
        return isinstance(value, str)
    if expected is list:
        return isinstance(value, list)
    if expected is dict:
        return isinstance(value, dict)
    return isinstance(value, expected) if isinstance(expected, type) else False


def _f(t: Any, required: bool = True, default: Any = None, enum: Iterable | None = None,
       pattern: re.Pattern | None = None) -> dict:
    return {"type": t, "required": required, "default": default,
            "enum": tuple(enum) if enum else None, "pattern": pattern}


def _list_of(t: Any, required: bool = True) -> dict:
    return _f(list, required=required, default=[])


CANDIDATE: dict[str, dict] = {
    "full_name": _f(str, pattern=_FULL_NAME),
    "url": _f(str),
    "domain": _f(str),
    "keyword": _f(str),
    "stars": _f(int),
    "forks": _f(int, required=False, default=0),
    "open_issues": _f(int, required=False, default=0),
    "language": _f(str, required=False, default=""),
    "license": _f(str, required=False, default=""),
    "topics": _list_of(str, required=False),
    "pushed_at": _f(str, required=False, default=""),
    "description": _f(str, required=False, default=""),
    "archived": _f(bool, required=False, default=False),
    "fork": _f(bool, required=False, default=False),
    "discovered_at": _f(str, required=False, default=""),
}

PROJECT_CARD: dict[str, dict] = {
    "name": _f(str),                                  # full_name（owner/repo）
    "url": _f(str),
    "domain": _f(str),
    "status": _f(str, enum=PROJECT_STATUS),
    "score": _f(float, required=False, default=0.0),
    "tier": _f(str, required=False, default="C", enum=TIERS),
    "version_watched": _f(str, required=False, default=""),
    "deps": _list_of(str, required=False),
    "api_surface": _list_of(str, required=False),
    "quality": _f(dict, required=False, default=dict),
    "license": _f(str, required=False, default=""),
    "first_seen": _f(str, required=False, default=""),
    "last_checked": _f(str, required=False, default=""),
    "reason": _f(str, required=False, default=""),
}

METRIC_RECORD: dict[str, dict] = {
    "date": _f(str),
    "ci_success_rate": _f(float, required=False, default=0.0),
    "avg_duration": _f(float, required=False, default=0.0),
    "coverage": _f(float, required=False, default=0.0),
    "alerts_open": _f(int, required=False, default=0),
    "deps_outdated": _f(int, required=False, default=0),
    "quota_used": _f(int, required=False, default=0),
    "notes": _list_of(str, required=False),
}

DECISION_RECORD: dict[str, dict] = {
    "ts": _f(str),
    "proposal": _f(str),
    "evidence": _list_of(str),
    "action": _f(str),
    "pr_url": _f(str, required=False, default=""),
    "outcome": _f(str, required=False, default="pending", enum=DECISION_OUTCOMES),
    "ci_result": _f(str, required=False, default=""),
}

SCHEMAS: dict[str, dict[str, dict]] = {
    "candidate": CANDIDATE,
    "project_card": PROJECT_CARD,
    "metric_record": METRIC_RECORD,
    "decision_record": DECISION_RECORD,
}


def problems(kind: str, obj: Any) -> list[str]:
    """返回全部契约问题；空列表表示通过（不抛异常，便于一次性看全）"""
    if kind not in SCHEMAS:
        return [f"unknown kind {kind!r}（可选 {sorted(SCHEMAS)}）"]
    if not isinstance(obj, dict):
        return [f"<root>: 期望 dict，实际 {_typename(type(obj))}"]

    spec = SCHEMAS[kind]
    issues: list[str] = []
    for field, rule in spec.items():
        if field not in obj:
            if rule["required"]:
                issues.append(f"{field}: 必需字段缺失")
            continue
        value = obj[field]
        if not _type_ok(value, rule["type"]):
            issues.append(
                f"{field}: 期望 {_typename(rule['type'])}，"
                f"实际 {_typename(type(value))}({value!r})")
            continue
        if rule["enum"] is not None and value not in rule["enum"]:
            issues.append(f"{field}: {value!r} 不在允许取值 {list(rule['enum'])}")
        if rule["pattern"] is not None and not rule["pattern"].match(value):
            issues.append(f"{field}: {value!r} 不匹配 {rule['pattern'].pattern}")
    unknown = sorted(set(obj) - set(spec))
    if unknown:
        issues.append(f"未知字段: {unknown}")
    return issues


def validate(kind: str, obj: Any) -> None:
    """校验，失败时一次性抛出全部问题"""
    issues = problems(kind, obj)
    if issues:
        joined = "\n  - ".join(issues)
        raise SchemaError(f"{kind} 契约校验失败:\n  - {joined}")


def new_record(kind: str, **fields: Any) -> dict:
    """按契约造一条记录：缺的可选字段补默认值，缺的必需字段报错

    生产者一律走这里，避免"少写一个字段 → 下游读 None → 静默按 0 处理"。
    """
    if kind not in SCHEMAS:
        raise SchemaError(f"unknown kind {kind!r}")
    rec: dict[str, Any] = {}
    for field, rule in SCHEMAS[kind].items():
        default = rule["default"]
        if callable(default):
            # dict/list 在这里当"工厂"用：每次调用产出新实例，
            # 避免多张卡共享同一个可变对象（改一张串一片）
            default = default()
        elif isinstance(default, (list, dict)):
            default = copy.deepcopy(default)
        rec[field] = default
    rec.update(fields)
    validate(kind, rec)
    return rec


def is_version(text: str) -> bool:
    """宽松 tag 判定：v1.2.3 / 1.2 / 20260101 都算版本号"""
    return bool(_SEMVER.match(text))
