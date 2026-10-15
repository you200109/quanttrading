"""
统一学习引擎 - GitHub 学习能力三合一

整合原三处分散能力:
1. 静态策略模板库 (原 gh_learner)
2. 在线仓库搜索与参数提取 (原 gh_online_learner)
3. 四类资源自动发现 (原 auto_discover)

对外统一接口:
    engine = LearningEngine(token=...)
    engine.learn_static()        静态知识学习
    engine.search_repos(query)   在线搜索
    engine.discover()            四类资源发现
    engine.full_cycle()          完整学习循环
"""
import base64
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# 数据根目录：本文件位于 vigilant-couscous/strategy/ 下，仓库数据契约为
# vigilant-couscous/memory/nexus（与 vc_routes 的 /strategies 端点、
# unified_evolve 等共用）。历史上曾误用 Path(__file__).parent（指向
# strategy/），导致读写分裂到 strategy/memory/nexus，2026-10-16 P3a 修复。
ROOT = Path(__file__).resolve().parent.parent
NEXUS = ROOT / "memory" / "nexus"
CACHE = ROOT / "memory" / "gh_cache"
NEXUS.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)


class LearningEngine:
    """统一学习引擎"""

    API = "https://api.github.com"

    # 静态策略模板库（原 gh_learner 内置知识）
    STATIC_STRATEGIES = [
        {"name": "经典RSI均值回归", "source": "quantopian/zipline", "rsi_period": 14, "sma_fast": 5, "sma_slow": 20, "stop_loss": 0.05, "take_profit": 0.15, "rsi_oversold": 30, "rsi_overbought": 70, "stars": 12500},
        {"name": "短线动量突破", "source": "freqtrade/freqtrade-strategies", "rsi_period": 7, "sma_fast": 3, "sma_slow": 10, "stop_loss": 0.03, "take_profit": 0.08, "rsi_oversold": 25, "rsi_overbought": 75, "stars": 8900},
        {"name": "趋势跟踪海龟", "source": "turtle-trading", "rsi_period": 21, "sma_fast": 8, "sma_slow": 30, "stop_loss": 0.08, "take_profit": 0.25, "rsi_oversold": 35, "rsi_overbought": 65, "stars": 6700},
        {"name": "自适应波动率", "source": "quantconnect/lean", "rsi_period": 10, "sma_fast": 4, "sma_slow": 25, "stop_loss": 0.06, "take_profit": 0.20, "rsi_oversold": 28, "rsi_overbought": 72, "stars": 9800},
        {"name": "保守价值投资", "source": "vnpy/vnpy", "rsi_period": 20, "sma_fast": 6, "sma_slow": 40, "stop_loss": 0.04, "take_profit": 0.12, "rsi_oversold": 32, "rsi_overbought": 68, "stars": 21000},
        {"name": "高频做市策略", "source": "hummingbot", "rsi_period": 5, "sma_fast": 2, "sma_slow": 8, "stop_loss": 0.01, "take_profit": 0.03, "rsi_oversold": 20, "rsi_overbought": 80, "stars": 7500},
        {"name": "多因子融合", "source": "ailabx", "rsi_period": 12, "sma_fast": 7, "sma_slow": 28, "stop_loss": 0.07, "take_profit": 0.18, "rsi_oversold": 27, "rsi_overbought": 73, "stars": 4500},
        {"name": "反趋势震荡", "source": "jesse-ai/jesse", "rsi_period": 9, "sma_fast": 5, "sma_slow": 15, "stop_loss": 0.04, "take_profit": 0.10, "rsi_oversold": 35, "rsi_overbought": 65, "stars": 5600},
        {"name": "深度学习预测", "source": "microsoft/qlib", "rsi_period": 16, "sma_fast": 9, "sma_slow": 35, "stop_loss": 0.06, "take_profit": 0.22, "rsi_oversold": 29, "rsi_overbought": 71, "stars": 15800},
        {"name": "加密货币专用", "source": "ccxt/ccxt", "rsi_period": 8, "sma_fast": 4, "sma_slow": 18, "stop_loss": 0.05, "take_profit": 0.30, "rsi_oversold": 22, "rsi_overbought": 78, "stars": 44345},
    ]

    # 四类资源发现关键词（原 auto_discover）
    DISCOVER_MATRIX = {
        "tool": ["quantitative+trading+framework+stars:>200+language:Python", "backtesting+engine+stars:>200+language:Python", "crypto+trading+bot+stars:>100+language:Python"],
        "indicator": ["technical+indicators+library+language:Python", "ta+library+pandas+trading+language:Python"],
        "strategy": ["freqtrade+strategy+language:Python", "trading+strategy+collection+language:Python"],
        "param": ["hyperparameter+optimization+trading+language:Python", "strategy+optimization+genetic+language:Python"],
    }

    def __init__(self, token: str = ""):
        self.token = token
        self.session = requests.Session()
        headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "LearningEngine/1.0"}
        if token:
            headers["Authorization"] = f"token {token}"
        self.session.headers.update(headers)
        self.discovered: dict[str, list[dict]] = {"tool": [], "indicator": [], "strategy": [], "param": []}
        self.learned_repos: list[dict] = []
        self.history: list[dict] = []
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        for fname, attr in [("learning_history.json", "learned_repos"), ("discovery_history.json", "discovered")]:
            f = NEXUS / fname
            if f.exists():
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if attr == "learned_repos":
                        self.learned_repos = data.get("repos", [])
                    else:
                        self.discovered = data.get("discovered", self.discovered)
                except Exception as e:
                    logger.warning(f"加载 {fname} 失败: {e}")

    def _save(self):
        (NEXUS / "learning_history.json").write_text(
            json.dumps({"repos": self.learned_repos[-100:], "last_update": datetime.now().isoformat()}, indent=2, ensure_ascii=False),
            encoding="utf-8")
        (NEXUS / "discovery_history.json").write_text(
            json.dumps({"discovered": self.discovered, "history": self.history[-30:], "last_update": datetime.now().isoformat()}, indent=2, ensure_ascii=False),
            encoding="utf-8")

    # ---------- GitHub 交互 ----------
    def _search(self, query: str, per_page: int = 6) -> list[dict]:
        try:
            r = self.session.get(f"{self.API}/search/repositories",
                                 params={"q": query, "sort": "stars", "order": "desc", "per_page": per_page}, timeout=15)
            if r.status_code == 200:
                return r.json().get("items", [])
            if r.status_code == 403:
                logger.warning("GitHub 速率限制")
                time.sleep(5)
            return []
        except Exception as e:
            logger.warning(f"搜索异常: {e}")
            return []

    def _readme(self, full_name: str) -> str:
        try:
            r = self.session.get(f"{self.API}/repos/{full_name}/readme", timeout=15)
            if r.status_code == 200:
                return base64.b64decode(r.json()["content"]).decode("utf-8", errors="ignore")
        except Exception:
            pass
        return ""

    def _extract_params(self, text: str) -> dict:
        p = {}
        m = re.search(r'rsi[\s_]*period[\s=:]*(\d+)|RSI[\s(]*(\d+)', text, re.IGNORECASE)
        if m: p["rsi_period"] = int(m.group(1) or m.group(2))
        m = re.search(r'stop[_-]?loss[\s=:]*(0?\.\d+)', text, re.IGNORECASE)
        if m: p["stop_loss"] = float(m.group(1))
        m = re.search(r'take[_-]?profit[\s=:]*(0?\.\d+)', text, re.IGNORECASE)
        if m: p["take_profit"] = float(m.group(1))
        m = re.search(r'sma[\s(]*(\d+)[\s,]+(\d+)', text, re.IGNORECASE)
        if m: p["sma_fast"], p["sma_slow"] = int(m.group(1)), int(m.group(2))
        return p

    # ---------- 能力一: 静态学习 ----------
    def learn_static(self) -> int:
        """加载内置静态策略模板到策略库"""
        lib_file = NEXUS / "gh_strategy_library.json"
        lib = json.loads(lib_file.read_text(encoding="utf-8")) if lib_file.exists() else {"strategies": []}
        existing = {s.get("name") for s in lib.get("strategies", [])}
        added = 0
        for s in self.STATIC_STRATEGIES:
            if s["name"] not in existing:
                lib["strategies"].append(s)
                existing.add(s["name"])
                added += 1
        lib["total_strategies"] = len(lib["strategies"])
        lib_file.write_text(json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"静态学习: 新增 {added} 组模板（累计 {lib['total_strategies']}）")
        return added

    # ---------- 能力二: 在线搜索 ----------
    def search_repos(self, query: str, per_page: int = 6) -> list[dict]:
        """在线搜索仓库"""
        repos = self._search(query, per_page)
        for repo in repos:
            fn = repo["full_name"]
            if any(r.get("full_name") == fn for r in self.learned_repos):
                continue
            entry = {
                "full_name": fn, "name": repo.get("name", ""),
                "stars": repo.get("stargazers_count", 0), "language": repo.get("language", ""),
                "description": (repo.get("description") or "")[:200],
                "url": repo.get("html_url", ""), "learned_at": datetime.now().isoformat(),
            }
            readme = self._readme(fn)
            params = self._extract_params(readme)
            if params:
                entry["params"] = params
            self.learned_repos.append(entry)
            time.sleep(0.5)
        self._save()
        logger.info(f"在线搜索 '{query[:30]}': 新增 {len(repos)} 个仓库")
        return repos

    # ---------- 能力三: 四类发现 ----------
    def discover(self, categories: list[str] | None = None) -> dict:
        """四类资源自动发现"""
        categories = categories or list(self.DISCOVER_MATRIX.keys())
        summary = {}
        for cat in categories:
            seen = {r["full_name"] for r in self.discovered.get(cat, [])}
            found = []
            for query in self.DISCOVER_MATRIX.get(cat, []):
                for repo in self._search(query):
                    fn = repo["full_name"]
                    if fn in seen:
                        continue
                    seen.add(fn)
                    entry = {
                        "full_name": fn, "name": repo.get("name", ""), "category": cat,
                        "stars": repo.get("stargazers_count", 0), "language": repo.get("language", ""),
                        "description": (repo.get("description") or "")[:200],
                        "url": repo.get("html_url", ""), "found_at": datetime.now().isoformat(),
                    }
                    if cat in ("strategy", "param"):
                        params = self._extract_params(self._readme(fn))
                        if params:
                            entry["params"] = params
                    found.append(entry)
                time.sleep(1.0)
            self.discovered.setdefault(cat, []).extend(found)
            summary[cat] = len(found)
            logger.info(f"[{cat}] 发现 {len(found)} 个资源")
        self._save()
        return summary

    # ---------- 参数入库 ----------
    def integrate_params(self) -> int:
        """把发现的参数并入策略库"""
        lib_file = NEXUS / "gh_strategy_library.json"
        lib = json.loads(lib_file.read_text(encoding="utf-8")) if lib_file.exists() else {"strategies": []}
        existing = {s.get("name") for s in lib.get("strategies", [])}
        added = 0
        sources = list(self.learned_repos) + [i for cat in ("strategy", "param") for i in self.discovered.get(cat, [])]
        for item in sources:
            params = item.get("params")
            if not params:
                continue
            name = f"learned_{item.get('name', 'x')[:30]}"
            if name in existing:
                continue
            lib["strategies"].append({
                "name": name, "source": item.get("url", ""), "stars": item.get("stars", 0),
                "rsi_period": params.get("rsi_period", 14), "sma_fast": params.get("sma_fast", 5),
                "sma_slow": params.get("sma_slow", 20), "stop_loss": params.get("stop_loss", 0.05),
                "take_profit": params.get("take_profit", 0.15), "rsi_oversold": 30, "rsi_overbought": 70,
            })
            existing.add(name)
            added += 1
        lib["total_strategies"] = len(lib["strategies"])
        lib["last_integrated"] = datetime.now().isoformat()
        lib_file.write_text(json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"参数入库: 新增 {added} 组（累计 {lib['total_strategies']}）")
        return added

    # ---------- 完整循环 ----------
    def full_cycle(self) -> dict:
        """完整学习循环: 静态 + 在线 + 发现 + 入库"""
        static_added = self.learn_static()
        disc = self.discover()
        params_added = self.integrate_params()
        entry = {
            "time": datetime.now().isoformat(),
            "static_added": static_added,
            "discovered": disc,
            "params_added": params_added,
            "total_repos": len(self.learned_repos),
            "total_resources": sum(len(v) for v in self.discovered.values()),
        }
        self.history.append(entry)
        self._save()
        return entry

    def get_seed_genes(self, n: int = 8) -> list[dict]:
        """提取种子参数供进化引擎使用"""
        lib_file = NEXUS / "gh_strategy_library.json"
        if not lib_file.exists():
            return []
        lib = json.loads(lib_file.read_text(encoding="utf-8"))
        seeds = []
        for s in lib.get("strategies", [])[:n]:
            seeds.append({
                "name": s.get("name", ""), "source": s.get("source", ""),
                "params": {k: s.get(k) for k in ("rsi_period", "sma_fast", "sma_slow", "stop_loss", "take_profit", "rsi_oversold", "rsi_overbought")},
            })
        return seeds

    def get_status(self) -> dict:
        return {
            "total_repos": len(self.learned_repos),
            "by_category": {k: len(v) for k, v in self.discovered.items()},
            "total_resources": sum(len(v) for v in self.discovered.values()),
            "cycles": len(self.history),
            "last_cycle": self.history[-1] if self.history else None,
        }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    sys.path.insert(0, str(ROOT))
    try:
        import config
        token = config.GITHUB["token"]
    except Exception:
        token = ""
    engine = LearningEngine(token=token)
    print("统一学习引擎 - 状态")
    print(json.dumps(engine.get_status(), indent=2, ensure_ascii=False))
