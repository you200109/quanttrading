"""
自动迭代调度器 - 自进化闭环总控

把四块能力串成一次完整迭代:
    学习(发现工具/指标/策略/参数) -> 进化(400轮优化) -> 版本升级 -> 热更新生效 -> 记录

用法:
    python auto_iterate.py once              执行一轮完整迭代
    python auto_iterate.py loop              持续迭代(默认每7天)
    python auto_iterate.py loop 24           持续迭代(每24小时)
"""
import contextlib
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
NEXUS = ROOT / "memory" / "nexus"
NEXUS.mkdir(parents=True, exist_ok=True)


class AutoIterator:
    """自动迭代总控"""

    def __init__(self):
        self.history_file = NEXUS / "iterate_history.json"
        self.history = []
        if self.history_file.exists():
            with contextlib.suppress(Exception):
                self.history = json.loads(self.history_file.read_text(encoding="utf-8")).get("history", [])

    def _load_cfg(self):
        import config
        return config

    def step_learn(self) -> dict:
        """阶段1: 自动发现并学习GitHub上的工具/指标/策略/参数"""
        logger.info("[1/4] 学习: 发现工具/指标/策略/参数...")
        try:
            from learning_engine import LearningEngine
            cfg = self._load_cfg()
            engine = LearningEngine(token=cfg.GITHUB["token"])
            cycle = engine.full_cycle()
            logger.info(f"      静态新增 {cycle['static_added']} | 发现 {sum(cycle['discovered'].values())} | 入库 {cycle['params_added']}")
            return {"ok": True, "discovered": sum(cycle["discovered"].values()), "params_added": cycle["params_added"]}
        except Exception as e:
            logger.warning(f"      学习阶段跳过: {e}")
            return {"ok": False, "error": str(e)[:120]}

    def step_evolve(self, mode: str = "weekly") -> dict:
        """阶段2: 进化优化"""
        logger.info(f"[2/4] 进化: {mode} 模式参数优化...")
        try:
            import unified_evolve
            if mode == "weekly":
                unified_evolve.cmd_weekly()
            elif mode == "daily":
                unified_evolve.cmd_daily()
            else:
                unified_evolve.cmd_once()
            result = {}
            rf = NEXUS / "evolve_result.json"
            if rf.exists():
                result = json.loads(rf.read_text(encoding="utf-8"))
            return {"ok": True, "fitness": result.get("best_fitness", 0), "params": result.get("best_params", {})}
        except Exception as e:
            logger.warning(f"      进化阶段跳过: {e}")
            return {"ok": False, "error": str(e)[:120]}

    def step_version(self) -> str:
        """阶段3: 版本升级"""
        logger.info("[3/4] 版本升级...")
        vf = NEXUS / "version.json"
        data = json.loads(vf.read_text(encoding="utf-8")) if vf.exists() else {"version": "0.1.0", "history": []}
        parts = [int(x) for x in data["version"].split(".")]
        parts[2] += 1
        data["version"] = ".".join(str(p) for p in parts)
        data["last_updated"] = datetime.now().isoformat()
        data.setdefault("history", []).append({"version": data["version"], "time": datetime.now().isoformat()})
        vf.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"      新版本: {data['version']}")
        return data["version"]

    def step_hotreload(self) -> list:
        """阶段4: 触发热更新，让新代码/新参数即时生效"""
        logger.info("[4/4] 热更新: 使改动即时生效...")
        reloaded = []
        try:
            from hot_reload import HotReloadManager
            mgr = HotReloadManager()
            # 标记全部模块检查变化
            for _name, watcher in mgr.watchers.items():
                watcher.changed()
            reloaded = mgr.check_and_reload()
            logger.info(f"      重载模块: {reloaded if reloaded else '无变化'}")
        except Exception as e:
            logger.warning(f"      热更新阶段跳过: {e}")
        return reloaded

    def iterate_once(self, mode: str = "weekly") -> dict:
        """执行一轮完整迭代"""
        logger.info("=" * 56)
        logger.info(f"自动迭代开始 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 56)

        learn = self.step_learn()
        evolve = self.step_evolve(mode)
        version = self.step_version()
        reloaded = self.step_hotreload()

        entry = {
            "time": datetime.now().isoformat(),
            "mode": mode,
            "learn": learn,
            "evolve": evolve,
            "version": version,
            "hot_reloaded": reloaded,
        }
        self.history.append(entry)
        self.history_file.write_text(
            json.dumps({"history": self.history[-50:], "total": len(self.history)}, indent=2, ensure_ascii=False),
            encoding="utf-8")

        logger.info("-" * 56)
        logger.info(f"迭代完成 | 版本 {version} | 适应度 {evolve.get('fitness', 'N/A')}")
        logger.info("=" * 56)
        return entry

    def run_loop(self, interval_hours: float = 168):
        """持续迭代"""
        logger.info(f"持续迭代模式启动，间隔 {interval_hours} 小时")
        n = 0
        while True:
            n += 1
            logger.info(f"\n########## 第 {n} 次迭代 ##########")
            try:
                self.iterate_once()
            except Exception as e:
                logger.error(f"迭代异常: {e}")
            logger.info(f"等待 {interval_hours} 小时后进行下一次迭代...")
            time.sleep(interval_hours * 3600)

    def status(self) -> dict:
        vf = NEXUS / "version.json"
        version = json.loads(vf.read_text(encoding="utf-8")).get("version", "?") if vf.exists() else "?"
        return {
            "current_version": version,
            "total_iterations": len(self.history),
            "last_iteration": self.history[-1] if self.history else None,
        }


if __name__ == "__main__":
    it = AutoIterator()
    if len(sys.argv) < 2:
        print(json.dumps(it.status(), indent=2, ensure_ascii=False))
        print("\n用法: python auto_iterate.py once | loop [间隔小时]")
    else:
        cmd = sys.argv[1]
        if cmd == "once":
            it.iterate_once()
        elif cmd == "loop":
            hours = float(sys.argv[2]) if len(sys.argv) > 2 else 168
            it.run_loop(interval_hours=hours)
        else:
            print(f"未知命令: {cmd}")
