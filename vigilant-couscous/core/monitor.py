"""
系统监控模块 - 健康检查、性能指标、Prometheus 兼容

提供：系统健康检查、性能指标收集、Prometheus 格式暴露、告警阈值监控
"""

import contextlib
import json
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
METRICS_FILE = ROOT / "reports" / "metrics.json"
METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class SystemMetrics:
    """系统指标"""
    cpu_percent: float = 0
    memory_percent: float = 0
    disk_percent: float = 0
    uptime_seconds: float = 0
    active_threads: int = 0
    python_memory_mb: float = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TradingMetrics:
    """交易指标"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0
    current_drawdown: float = 0
    sharpe_ratio: float = 0
    win_rate: float = 0
    avg_trade_duration: float = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AGIMetrics:
    """AGI 指标"""
    total_decisions: int = 0
    correct_decisions: int = 0
    avg_confidence: float = 0
    learning_rate: float = 0
    knowledge_entries: int = 0
    evolution_cycles: int = 0
    innovations_discovered: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


class SystemMonitor:
    """系统监控器

    核心能力：
    1. 系统资源监控 - CPU/内存/磁盘
    2. 交易指标收集 - 胜率/收益/回撤
    3. AGI 指标收集 - 决策/学习/进化
    4. Prometheus 格式暴露
    5. 告警阈值检测
    """

    ALERT_THRESHOLDS = {
        "cpu_percent": 90,
        "memory_percent": 85,
        "disk_percent": 90,
        "max_drawdown": 0.20,
        "consecutive_losses": 5,
        "error_rate": 10,
    }

    def __init__(self):
        self.start_time = datetime.now()
        self.metrics_history: deque = deque(maxlen=1000)
        self.alerts: list[dict] = []
        self.last_collection: datetime | None = None

    def collect_system_metrics(self) -> SystemMetrics:
        """收集系统指标"""
        try:
            cpu = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            process = psutil.Process(os.getpid())

            metrics = SystemMetrics(
                cpu_percent=cpu,
                memory_percent=memory.percent,
                disk_percent=disk.percent,
                uptime_seconds=(datetime.now() - self.start_time).total_seconds(),
                active_threads=process.num_threads(),
                python_memory_mb=process.memory_info().rss / 1024 / 1024,
            )
            self._check_alerts(metrics)
            return metrics
        except Exception as e:
            logger.debug(f"系统指标收集失败: {e}")
            return SystemMetrics()

    def collect_trading_metrics(self, db=None) -> TradingMetrics:
        """收集交易指标"""
        try:
            if db:
                stats = db.get_trade_stats()
                return TradingMetrics(
                    total_trades=stats.get("total", 0),
                    winning_trades=int(stats.get("total", 0) * stats.get("win_rate", 0) / 100),
                    losing_trades=int(stats.get("total", 0) * (1 - stats.get("win_rate", 0) / 100)),
                    total_pnl=stats.get("total_pnl", 0) or 0,
                    win_rate=stats.get("win_rate", 0) or 0,
                )
        except Exception as e:
            logger.debug(f"交易指标收集失败: {e}")
        return TradingMetrics()

    def collect_agi_metrics(self, agi_brain=None, eternal_evolver=None) -> AGIMetrics:
        """收集 AGI 指标"""
        try:
            metrics = AGIMetrics()
            if agi_brain:
                status = agi_brain.get_status()
                metrics.total_decisions = status.get("total_decisions", 0)
                metrics.avg_confidence = 0.5
            if eternal_evolver:
                status = eternal_evolver.get_status()
                metrics.evolution_cycles = status.get("total_cycles", 0)
                metrics.innovations_discovered = status.get("discoveries", 0)
            return metrics
        except Exception as e:
            logger.debug(f"AGI 指标收集失败: {e}")
        return AGIMetrics()

    def collect_all(self, db=None, agi_brain=None, eternal_evolver=None) -> dict:
        """收集全部指标"""
        system = self.collect_system_metrics()
        trading = self.collect_trading_metrics(db)
        agi = self.collect_agi_metrics(agi_brain, eternal_evolver)

        all_metrics = {
            "system": system.__dict__,
            "trading": trading.__dict__,
            "agi": agi.__dict__,
            "timestamp": datetime.now().isoformat(),
        }
        self.metrics_history.append(all_metrics)
        self.last_collection = datetime.now()
        self._save_metrics(all_metrics)
        return all_metrics

    def get_health_status(self) -> dict:
        """获取健康状态"""
        try:
            metrics = self.collect_system_metrics()
            issues = []

            if metrics.cpu_percent > self.ALERT_THRESHOLDS["cpu_percent"]:
                issues.append(f"CPU 使用率过高: {metrics.cpu_percent}%")
            if metrics.memory_percent > self.ALERT_THRESHOLDS["memory_percent"]:
                issues.append(f"内存使用率过高: {metrics.memory_percent}%")
            if metrics.disk_percent > self.ALERT_THRESHOLDS["disk_percent"]:
                issues.append(f"磁盘使用率过高: {metrics.disk_percent}%")

            return {
                "status": "healthy" if not issues else "degraded",
                "uptime_hours": round(metrics.uptime_seconds / 3600, 1),
                "cpu": metrics.cpu_percent,
                "memory": metrics.memory_percent,
                "disk": metrics.disk_percent,
                "issues": issues,
                "alerts_count": len(self.alerts),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_prometheus_metrics(self) -> str:
        """生成 Prometheus 格式指标"""
        metrics = self.collect_system_metrics()
        lines = [
            "# HELP self_evolve_cpu_percent CPU 使用率",
            "# TYPE self_evolve_cpu_percent gauge",
            f"self_evolve_cpu_percent {metrics.cpu_percent}",
            "# HELP self_evolve_memory_percent 内存使用率",
            "# TYPE self_evolve_memory_percent gauge",
            f"self_evolve_memory_percent {metrics.memory_percent}",
            "# HELP self_evolve_uptime_seconds 运行时间",
            "# TYPE self_evolve_uptime_seconds gauge",
            f"self_evolve_uptime_seconds {metrics.uptime_seconds}",
            "# HELP self_evolve_active_threads 活跃线程数",
            "# TYPE self_evolve_active_threads gauge",
            f"self_evolve_active_threads {metrics.active_threads}",
        ]
        return "\n".join(lines)

    def _check_alerts(self, metrics: SystemMetrics):
        """检查告警阈值"""
        if metrics.cpu_percent > self.ALERT_THRESHOLDS["cpu_percent"]:
            self.alerts.append({
                "type": "cpu_high",
                "value": metrics.cpu_percent,
                "threshold": self.ALERT_THRESHOLDS["cpu_percent"],
                "timestamp": datetime.now().isoformat(),
            })
            logger.warning(f"CPU 告警: {metrics.cpu_percent}%")

        if metrics.memory_percent > self.ALERT_THRESHOLDS["memory_percent"]:
            self.alerts.append({
                "type": "memory_high",
                "value": metrics.memory_percent,
                "threshold": self.ALERT_THRESHOLDS["memory_percent"],
                "timestamp": datetime.now().isoformat(),
            })
            logger.warning(f"内存告警: {metrics.memory_percent}%")

    def _save_metrics(self, metrics: dict):
        """保存指标"""
        with contextlib.suppress(Exception):
            METRICS_FILE.write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=str))

    def get_status(self) -> dict:
        """获取监控状态"""
        return {
            "health": self.get_health_status(),
            "last_collection": self.last_collection.isoformat() if self.last_collection else None,
            "metrics_count": len(self.metrics_history),
            "alerts_count": len(self.alerts),
        }


monitor = SystemMonitor()
