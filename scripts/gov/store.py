"""治理数据的统一落盘层（reports/ 产出 + 知识库长期记忆）

两处截然不同的东西，别混为一谈：

`reports/`（仓库根，**运行时产物**）
    单次运行的输出，按日期命名，被 .gitignore 忽略，只在 CI 上以 artifact
    留存 90 天（P5d 之前的 20 个 mon-*/q-* 就是输在这里：结果只进日志，
    次日随日志过期而永久丢失）。

`vigilant-couscous/memory/knowledge/`（**长期记忆**）
    随仓库版本化——项目评分历史、整合成败原因、每轮的演进决策。这是治理系统
    能"自我演进"的前提：没有跨运行的记忆，每轮都是第一次看见这个世界。

契约（candidate/project_card/metric_record/decision_record）由 schemas.py
把关，本模块只负责"按契约读写"，并在落盘前统一过一遍 validate——
写脏数据到知识库比不写更糟，后者至少不会污染后续所有决策。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from scripts.gov import schemas

GOV_DIR = Path(__file__).resolve().parent
REPO_ROOT = GOV_DIR.parent.parent
REPORTS_DIR = REPO_ROOT / "reports"

DEFAULT_KNOWLEDGE_ROOT = "vigilant-couscous/memory/knowledge"
PROJECTS_SUBDIR = "projects"
DECISIONS_FILE = "decisions.jsonl"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# reports/ —— 运行产物
# --------------------------------------------------------------------------
def report_path(*parts: str, date: str | None = None) -> Path:
    """reports/<date>/<parts...> ；不传 date 用当天（UTC）"""
    return REPORTS_DIR / (date or today_stamp()) / Path(*parts)


def write_json(obj: Any, *parts: str, date: str | None = None,
               validate_as: str | None = None) -> Path:
    """写 JSON 到 reports/。返回落盘路径。

    validate_as 传入契约名时先校验再写：宁可报错不落盘，也不让脏数据进流水线。
    """
    if validate_as:
        schemas.validate(validate_as, obj)
    path = report_path(*parts, date=date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 知识库 —— 长期记忆（随仓库版本化）
# --------------------------------------------------------------------------
def knowledge_root(cfg: dict | None = None) -> Path:
    """知识库根。cfg 为空时用默认相对路径（测试里通常直接传 tmp 根）"""
    rel = DEFAULT_KNOWLEDGE_ROOT
    if cfg:
        rel = (cfg.get("knowledge") or {}).get("root", DEFAULT_KNOWLEDGE_ROOT)
    root = Path(rel)
    return root if root.is_absolute() else REPO_ROOT / root


def projects_dir(cfg: dict | None = None) -> Path:
    return knowledge_root(cfg) / PROJECTS_SUBDIR


def decisions_path(cfg: dict | None = None) -> Path:
    name = DECISIONS_FILE
    if cfg:
        name = (cfg.get("knowledge") or {}).get("decisions_file", DECISIONS_FILE)
    return knowledge_root(cfg) / name


def ensure_knowledge(cfg: dict | None = None) -> Path:
    """保证知识库目录结构存在（幂等）"""
    root = knowledge_root(cfg)
    (root / PROJECTS_SUBDIR).mkdir(parents=True, exist_ok=True)
    return root


def card_filename(full_name: str) -> str:
    """owner/repo -> owner__repo.json（避免路径分隔符）"""
    if "/" not in full_name:
        raise ValueError(f"full_name 应为 owner/repo 形式，实际 {full_name!r}")
    owner, repo = full_name.split("/", 1)
    if not owner or not repo:
        raise ValueError(f"full_name 形式非法: {full_name!r}")
    return f"{owner}__{repo}.json"


def save_project_card(card: dict, cfg: dict | None = None) -> Path:
    """写一张项目卡（先过 project_card 契约）"""
    schemas.validate("project_card", card)
    ensure_knowledge(cfg)
    path = projects_dir(cfg) / card_filename(card["name"])
    path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_project_card(full_name: str, cfg: dict | None = None) -> dict | None:
    path = projects_dir(cfg) / card_filename(full_name)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_project_cards(cfg: dict | None = None) -> dict[str, dict]:
    """返回 {full_name: card}。坏文件跳过但记 stderr，不静默整目录失效"""
    base = projects_dir(cfg)
    if not base.is_dir():
        return {}
    cards: dict[str, dict] = {}
    for path in sorted(base.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"warn: 跳过损坏的项目卡 {path}: {exc}")
            continue
        if isinstance(card, dict) and "name" in card:
            cards[card["name"]] = card
    return cards


def append_decision(record: dict, cfg: dict | None = None) -> Path:
    """追加一条决策记录到 decisions.jsonl（演进闭环的审计轨迹）"""
    schemas.validate("decision_record", record)
    ensure_knowledge(cfg)
    path = decisions_path(cfg)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def read_decisions(cfg: dict | None = None, limit: int = 50) -> list[dict]:
    path = decisions_path(cfg)
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 单行损坏不影响其余历史可读
    return rows[-limit:] if limit else rows


def iter_project_cards(cfg: dict | None = None) -> Iterator[dict]:
    return iter(list_project_cards(cfg).values())
