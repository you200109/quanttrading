"""
热更新管理器 - 系统自更新 + 热更新核心

能力:
1. 实时监测 config.py 与各模块文件的变化
2. 检测到变化自动重新加载，无需重启进程
3. 配置热更新 - 参数改动立即生效
4. 自更新 - 检查版本、下载、替换、触发重载
"""
import hashlib
import importlib
import json
import logging
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent


class ModuleWatcher:
    """单个模块文件监测器"""

    def __init__(self, file_path: Path, module_name: str):
        self.file_path = file_path
        self.module_name = module_name
        self.last_hash = self._calc_hash()
        self.last_mtime = file_path.stat().st_mtime if file_path.exists() else 0

    def _calc_hash(self) -> str:
        """计算文件内容指纹"""
        if not self.file_path.exists():
            return ""
        try:
            return hashlib.md5(self.file_path.read_bytes()).hexdigest()
        except Exception:
            return ""

    def changed(self) -> bool:
        """检查文件是否发生变化"""
        if not self.file_path.exists():
            return False
        new_hash = self._calc_hash()
        if new_hash != self.last_hash:
            self.last_hash = new_hash
            self.last_mtime = self.file_path.stat().st_mtime
            return True
        return False


class HotReloadManager:
    """热更新管理器"""

    # 需要监测的模块（相对路径 -> 模块名）
    WATCH_TARGETS = {
        "config": "config",
        "agents/researcher": "agents.researcher",
        "agents/trader": "agents.trader",
        "agents/risk_manager": "agents.risk_manager",
        "data/fetcher": "data.fetcher",
        "data/live_trader": "data.live_trader",
        "data/portfolio_manager": "data.portfolio_manager",
        "evolution/learning_loop": "evolution.learning_loop",
        "evolution/rl_environment": "evolution.rl_environment",
        "evolution/rl_trainer": "evolution.rl_trainer",
        "evolution/gh_learner": "evolution.gh_learner",
        "evolution/gh_online_learner": "evolution.gh_online_learner",
        "strategies/base_strategy": "strategies.base_strategy",
    }

    def __init__(self, config_path: Path | None = None):
        self.watchers: dict[str, ModuleWatcher] = {}
        self.reload_count = 0
        self.reload_history: list[dict] = []
        self.callbacks: list[Callable] = []
        self.enabled = True
        self._setup_watchers()

    def _setup_watchers(self):
        """建立所有监测器"""
        for rel_path, module_name in self.WATCH_TARGETS.items():
            fp = ROOT / f"{rel_path}.py"
            if fp.exists():
                self.watchers[module_name] = ModuleWatcher(fp, module_name)
        logger.info(f"热更新管理器已启动，监测 {len(self.watchers)} 个模块")

    def register_callback(self, fn: Callable):
        """注册重载回调（重载后执行）"""
        self.callbacks.append(fn)

    def check_and_reload(self) -> list[str]:
        """检查所有模块并重载变化的，返回被重载的模块列表"""
        reloaded = []
        for module_name, watcher in self.watchers.items():
            if watcher.changed() and self._reload_module(module_name):
                reloaded.append(module_name)
                logger.info(f"[热更新] {module_name} 已重新加载")

        if reloaded:
            self.reload_count += 1
            entry = {
                "time": datetime.now().isoformat(),
                "modules": reloaded,
                "count": self.reload_count,
            }
            self.reload_history.append(entry)
            self._save_history()

            # 执行回调
            for cb in self.callbacks:
                try:
                    cb(reloaded)
                except Exception as e:
                    logger.warning(f"热更新回调失败: {e}")

        return reloaded

    def _reload_module(self, module_name: str) -> bool:
        """重新加载单个模块"""
        try:
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
            else:
                importlib.import_module(module_name)
            return True
        except Exception as e:
            logger.error(f"[热更新] {module_name} 重载失败: {e}")
            return False

    def reload_config(self) -> dict:
        """强制重载配置"""
        self._reload_module("config")
        import config as cfg
        importlib.reload(cfg)
        logger.info("[热更新] 配置已重新加载")
        return {
            "symbols": cfg.SYMBOLS,
            "risk": cfg.RISK,
        }

    def _save_history(self):
        """保存重载历史"""
        try:
            history_file = ROOT / "memory" / "nexus" / "hot_reload_history.json"
            history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(self.reload_history[-50:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"保存重载历史失败: {e}")

    def get_status(self) -> dict:
        """获取热更新状态"""
        return {
            "enabled": self.enabled,
            "watching": len(self.watchers),
            "reload_count": self.reload_count,
            "modules": list(self.watchers.keys()),
            "last_reload": self.reload_history[-1] if self.reload_history else None,
        }

    def start_watch_loop(self, interval_seconds: int = 3, max_checks: int | None = None):
        """启动持续监测循环

        Args:
            interval_seconds: 检查间隔（秒）
            max_checks: 最大检查次数（None 表示无限）
        """
        logger.info(f"[热更新] 开始监测，间隔 {interval_seconds} 秒")
        checks = 0
        while self.enabled:
            reloaded = self.check_and_reload()
            if reloaded:
                print(f"[热更新] 检测到变化并重载: {reloaded}")
            checks += 1
            if max_checks and checks >= max_checks:
                break
            time.sleep(interval_seconds)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    mgr = HotReloadManager()
    print(json.dumps(mgr.get_status(), indent=2, ensure_ascii=False))
