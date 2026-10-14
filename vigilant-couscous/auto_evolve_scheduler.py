"""
全域自动进化调度器 - 本地 AGI 永续进化 + 云端协同

每15分钟执行完整 AGI 认知架构循环，与云端工作流保持一致。
支持：本地进化、云端同步、状态监控、优雅退出。
"""

import sys
import json
import time
import signal
import logging
from datetime import datetime, timedelta
from pathlib import Path

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False

Path('reports').mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('reports/auto_evolve.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


class AutoEvolveScheduler:
    """全域自动进化调度器 - 本地 AGI 永续进化 + 云端协同"""

    def __init__(self, interval_minutes: int = 15):
        self.interval_minutes = interval_minutes
        self.iteration = 0
        self.start_time = datetime.now()
        self.last_evolve_time = None
        self.last_result = {}
        self.running = True
        self.state_file = ROOT / 'memory' / 'nexus' / 'auto_evolve_state.json'
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        Path('memory/agi').mkdir(parents=True, exist_ok=True)
        Path('strategies').mkdir(parents=True, exist_ok=True)

    def evolve_once(self):
        """执行完整 AGI 永续进化循环（8大模块）"""
        self.iteration += 1
        logger.info(f'===== 第 {self.iteration} 轮全域进化 =====')

        # 0. 同步云端进化结果
        self._sync_from_cloud()

        # 1. GitHub 策略学习
        try:
            from learning_engine import LearningEngine
            learner = LearningEngine()
            cycle = learner.full_cycle()
            logger.info(f'[1/8] GitHub学习: 静态新增{cycle.get("static_added",0)}, 发现{sum(cycle.get("discovered",{}).values())}')
        except Exception as e:
            logger.warning(f'[1/8] 学习跳过: {e}')

        # 2. 多维度进化
        try:
            from evolution.multi_dim_evolve import MultiDimEvolution
            engine = MultiDimEvolution()
            summary = engine.evolve_all(generations=50, population=20)
            logger.info(f'[2/8] 多维度进化: {summary["total"]}任务, {summary["passed"]}通过')
        except Exception as e:
            logger.warning(f'[2/8] 多维度进化跳过: {e}')

        # 3. 自我编程注入
        try:
            from evolution.self_programming import SelfProgrammingEngine
            sp = SelfProgrammingEngine()
            result = sp.full_cycle(max_results=5)
            logger.info(f'[3/8] 自我编程: 提取{result["extracted"]}, 注入{result["injected"]}, 通过{result["passed"]}')
        except Exception as e:
            logger.warning(f'[3/8] 自我编程跳过: {e}')

        # 4. 永续进化引擎
        try:
            from agi.eternal_evolver import EternalEvolver
            evolver = EternalEvolver()
            cycle_result = evolver.eternal_cycle()
            logger.info(f'[4/8] 永续进化: 周期{cycle_result["cycle"]}, 动作{len(cycle_result["actions"])}个')
        except Exception as e:
            logger.warning(f'[4/8] 永续进化跳过: {e}')

        # 5. 对抗训练锦标赛
        try:
            from agi.adversarial_training import AdversarialTraining
            adversarial = AdversarialTraining()
            results = adversarial.run_tournament({'close': [], 'regime': 'sideways'})
            leaderboard = adversarial.get_leaderboard(3)
            top_elo = leaderboard[0]['elo'] if leaderboard else 0
            logger.info(f'[5/8] 对抗训练: {len(results)}场对战, 最高ELO={top_elo:.0f}')
        except Exception as e:
            logger.warning(f'[5/8] 对抗训练跳过: {e}')

        # 6. 自主研究
        try:
            from agi.auto_researcher import AutoResearcher
            researcher = AutoResearcher()
            research_result = researcher.research_cycle()
            logger.info(f'[6/8] 自主研究: 论文{research_result["papers_found"]}, 策略{research_result["strategies_discovered"]}, 假设{research_result["hypotheses_generated"]}')
        except Exception as e:
            logger.warning(f'[6/8] 自主研究跳过: {e}')

        # 7. 元学习超参优化
        try:
            from agi.meta_learner import MetaLearner
            meta = MetaLearner()
            config = meta.optimize_hyperparams([0.01] * 20, n_trials=10)
            logger.info(f'[7/8] 元学习: lr={config.learning_rate:.5f}, layers={config.hidden_layers}')
        except Exception as e:
            logger.warning(f'[7/8] 元学习跳过: {e}')

        # 8. 记忆巩固
        try:
            from agi.memory_system import MemorySystem
            memory = MemorySystem()
            memory.consolidate()
            stats = memory.get_memory_stats()
            logger.info(f'[8/8] 记忆巩固: 情景{stats["episodic_count"]}, 语义{stats["semantic_count"]}')
        except Exception as e:
            logger.warning(f'[8/8] 记忆巩固跳过: {e}')

        self.last_evolve_time = datetime.now()
        self._load_result()
        self._save_state()
        self._commit_changes()
        logger.info(f'===== 第 {self.iteration} 轮全域进化完成 =====')

    def _sync_from_cloud(self):
        """从云端同步进化结果"""
        try:
            import subprocess
            result = subprocess.run(
                ['git', 'pull', 'origin', 'master'],
                cwd=str(ROOT), capture_output=True, text=True, timeout=30
            )
            if 'Already up to date' not in result.stdout and result.returncode == 0:
                logger.info('云端同步: 已拉取最新进化结果')
        except Exception:
            pass

    def _commit_changes(self):
        """提交本地进化结果"""
        try:
            import subprocess
            subprocess.run(
                ['git', 'add', 'memory/', 'reports/', 'strategies/'],
                cwd=str(ROOT), capture_output=True, timeout=10
            )
            diff_result = subprocess.run(
                ['git', 'diff', '--staged', '--quiet'],
                cwd=str(ROOT), capture_output=True, timeout=10
            )
            if diff_result.returncode != 0:
                subprocess.run(
                    ['git', 'commit', '-m', f'auto: local AGI evolve cycle {self.iteration}'],
                    cwd=str(ROOT), capture_output=True, timeout=10
                )
                subprocess.run(
                    ['git', 'push', 'origin', 'master'],
                    cwd=str(ROOT), capture_output=True, timeout=30
                )
                logger.info('本地进化结果已推送至云端')
        except Exception:
            pass

    def _load_result(self):
        result_file = ROOT / 'memory' / 'nexus' / 'evolve_result.json'
        if result_file.exists():
            try:
                self.last_result = json.loads(result_file.read_text(encoding='utf-8'))
            except Exception:
                pass

    def _save_state(self):
        state = {
            'iteration': self.iteration,
            'start_time': self.start_time.isoformat(),
            'last_evolve_time': self.last_evolve_time.isoformat() if self.last_evolve_time else None,
            'last_result': self.last_result,
            'interval_minutes': self.interval_minutes,
            'updated': datetime.now().isoformat(),
        }
        self.state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str))

    def get_status(self) -> dict:
        elapsed = datetime.now() - self.start_time
        next_run = None
        if self.last_evolve_time:
            next_run = self.last_evolve_time + timedelta(minutes=self.interval_minutes)
        return {
            'running': self.running,
            'iteration': self.iteration,
            'elapsed': str(elapsed).split('.')[0],
            'last_evolve': self.last_evolve_time.isoformat() if self.last_evolve_time else None,
            'next_evolve': next_run.isoformat() if next_run else None,
            'interval_minutes': self.interval_minutes,
            'last_result': self.last_result,
        }

    def start(self):
        if not HAS_APSCHEDULER:
            logger.error('APScheduler 未安装，使用简单循环模式')
            self._run_simple_loop()
            return

        logger.info(f'全域自动进化调度器启动 | 间隔: {self.interval_minutes} 分钟 | 8大模块')
        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(
            self.evolve_once,
            IntervalTrigger(minutes=self.interval_minutes),
            id='auto_evolve',
            name='全域AGI进化任务',
            next_run_time=datetime.now()
        )
        self.scheduler.start()
        logger.info('调度器已启动，等待任务触发...')

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            while self.running:
                time.sleep(10)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _run_simple_loop(self):
        logger.info(f'简单循环模式启动 | 间隔: {self.interval_minutes} 分钟')
        self.evolve_once()
        while self.running:
            try:
                time.sleep(self.interval_minutes * 60)
                self.evolve_once()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f'循环异常: {e}')
                time.sleep(60)

    def stop(self):
        self.running = False
        if HAS_APSCHEDULER and hasattr(self, 'scheduler'):
            self.scheduler.shutdown(wait=False)
        self._save_state()
        logger.info(f'调度器已停止 | 共执行 {self.iteration} 轮')

    def _signal_handler(self, signum, frame):
        logger.info(f'收到信号 {signum}，正在停止...')
        self.running = False


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='全域自动进化调度器')
    parser.add_argument('--interval', type=int, default=15, help='进化间隔（分钟），默认15')
    parser.add_argument('--once', action='store_true', help='仅执行一次后退出')
    parser.add_argument('--status', action='store_true', help='查看调度器状态')
    args = parser.parse_args()

    scheduler = AutoEvolveScheduler(interval_minutes=args.interval)

    if args.status:
        status = scheduler.get_status()
        print(json.dumps(status, indent=2, ensure_ascii=False, default=str))
    elif args.once:
        scheduler.evolve_once()
        print(json.dumps(scheduler.get_status(), indent=2, ensure_ascii=False, default=str))
    else:
        scheduler.start()
