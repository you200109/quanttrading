"""
实时风控告警系统

支持 Webhook（企业微信/钉钉/飞书）、邮件、日志多通道告警。
当回撤超阈值、异常交易、系统异常时即时通知。
"""

import json
import logging
import smtplib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class Alert:
    level: AlertLevel
    title: str
    message: str
    source: str = "system"
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False


class AlertManager:
    MAX_HISTORY = 500
    COOLDOWN_SECONDS = {
        AlertLevel.INFO: 60,
        AlertLevel.WARNING: 300,
        AlertLevel.CRITICAL: 120,
        AlertLevel.EMERGENCY: 60,
    }

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.alert_history: deque = deque(maxlen=self.MAX_HISTORY)
        self.last_alert_time: dict[str, datetime] = {}
        self.alert_counts: dict[str, int] = {}
        self.suppressed_until: dict[str, datetime] = {}
        self.webhook_urls: dict[str, str] = self.config.get("webhooks", {})
        self.email_config: dict = self.config.get("email", {})
        self.thresholds: dict = self.config.get("thresholds", {
            "max_drawdown_warning": 0.10,
            "max_drawdown_critical": 0.15,
            "max_drawdown_emergency": 0.25,
            "max_single_loss": 0.05,
            "max_daily_loss": 0.08,
            "max_consecutive_losses": 5,
            "min_daily_volume": 1000,
            "max_position_concentration": 0.30,
            "api_error_threshold": 3,
            "data_stale_minutes": 15,
        })
        self.daily_pnl: float = 0
        self.consecutive_losses: int = 0
        self.api_errors: int = 0
        self.last_data_update: datetime | None = None
        Path("reports/alerts").mkdir(parents=True, exist_ok=True)

    def check_drawdown(self, current_equity: float, peak_equity: float) -> list[Alert]:
        alerts = []
        if peak_equity <= 0:
            return alerts
        drawdown = (peak_equity - current_equity) / peak_equity
        if drawdown >= self.thresholds["max_drawdown_emergency"]:
            alerts.append(self._create_alert(AlertLevel.EMERGENCY, "紧急回撤告警",
                f"当前回撤 {drawdown:.2%} 已超过紧急阈值 {self.thresholds['max_drawdown_emergency']:.0%}，建议立即暂停交易",
                source="risk.drawdown", metadata={"drawdown": drawdown, "peak": peak_equity, "current": current_equity}))
        elif drawdown >= self.thresholds["max_drawdown_critical"]:
            alerts.append(self._create_alert(AlertLevel.CRITICAL, "严重回撤告警",
                f"当前回撤 {drawdown:.2%} 已超过严重阈值 {self.thresholds['max_drawdown_critical']:.0%}",
                source="risk.drawdown", metadata={"drawdown": drawdown}))
        elif drawdown >= self.thresholds["max_drawdown_warning"]:
            alerts.append(self._create_alert(AlertLevel.WARNING, "回撤预警",
                f"当前回撤 {drawdown:.2%} 已超过预警阈值 {self.thresholds['max_drawdown_warning']:.0%}",
                source="risk.drawdown", metadata={"drawdown": drawdown}))
        return alerts

    def check_trade(self, trade_result: dict) -> list[Alert]:
        alerts = []
        pnl = trade_result.get("pnl", 0)
        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
            loss_pct = abs(pnl) / trade_result.get("capital", 100000)
            if loss_pct >= self.thresholds["max_single_loss"]:
                alerts.append(self._create_alert(AlertLevel.WARNING, "单笔大额亏损",
                    f"{trade_result.get('symbol', 'Unknown')} 单笔亏损 {loss_pct:.2%}，超过阈值 {self.thresholds['max_single_loss']:.0%}",
                    source="risk.trade", metadata=trade_result))
            if self.consecutive_losses >= self.thresholds["max_consecutive_losses"]:
                alerts.append(self._create_alert(AlertLevel.CRITICAL, "连续亏损告警",
                    f"已连续亏损 {self.consecutive_losses} 笔，超过阈值 {self.thresholds['max_consecutive_losses']}，建议暂停检查策略",
                    source="risk.consecutive_loss", metadata={"consecutive": self.consecutive_losses}))
        else:
            self.consecutive_losses = 0
        if abs(self.daily_pnl) / trade_result.get("capital", 100000) >= self.thresholds["max_daily_loss"]:
            alerts.append(self._create_alert(AlertLevel.WARNING, "日内亏损超限",
                f"当日累计亏损 {self.daily_pnl:.2f}，已超过日内阈值", source="risk.daily_loss"))
        return alerts

    def check_system_health(self, metrics: dict) -> list[Alert]:
        alerts = []
        if metrics.get("api_errors", 0) > 0:
            self.api_errors += metrics["api_errors"]
            if self.api_errors >= self.thresholds["api_error_threshold"]:
                alerts.append(self._create_alert(AlertLevel.CRITICAL, "API 错误过多",
                    f"累计 API 错误 {self.api_errors} 次，超过阈值 {self.thresholds['api_error_threshold']}",
                    source="system.api_error"))
        if metrics.get("data_timestamp"):
            self.last_data_update = metrics["data_timestamp"]
        if self.last_data_update and (datetime.now() - self.last_data_update).total_seconds() > self.thresholds["data_stale_minutes"] * 60:
            alerts.append(self._create_alert(AlertLevel.WARNING, "数据延迟告警",
                f"数据已 {int((datetime.now() - self.last_data_update).total_seconds() / 60)} 分钟未更新",
                source="system.data_stale"))
        if metrics.get("position_concentration", 0) > self.thresholds["max_position_concentration"]:
            alerts.append(self._create_alert(AlertLevel.WARNING, "仓位集中度告警",
                f"单一仓位占比 {metrics['position_concentration']:.1%}，超过阈值 {self.thresholds['max_position_concentration']:.0%}",
                source="risk.concentration"))
        return alerts

    def send_alert(self, alert: Alert) -> bool:
        if not self._should_send(alert):
            return False
        self.alert_history.append(alert)
        alert_key = f"{alert.source}:{alert.level.value}"
        self.last_alert_time[alert_key] = datetime.now()
        self.alert_counts[alert_key] = self.alert_counts.get(alert_key, 0) + 1
        self._log_alert(alert)
        success = False
        if self.webhook_urls:
            success = self._send_webhook(alert) or success
        if self.email_config:
            success = self._send_email(alert) or success
        self._save_alert(alert)
        return success

    def _should_send(self, alert: Alert) -> bool:
        alert_key = f"{alert.source}:{alert.level.value}"
        if alert_key in self.suppressed_until and datetime.now() < self.suppressed_until[alert_key]:
            return False
        if alert_key in self.last_alert_time:
            cooldown = self.COOLDOWN_SECONDS.get(alert.level, 60)
            if (datetime.now() - self.last_alert_time[alert_key]).total_seconds() < cooldown:
                return False
        return True

    def _create_alert(self, level: AlertLevel, title: str, message: str,
                      source: str = "system", metadata: dict | None = None) -> Alert:
        return Alert(level=level, title=title, message=message, source=source,
                     metadata=metadata or {}, timestamp=datetime.now())

    def _log_alert(self, alert: Alert):
        emoji = {AlertLevel.INFO: "ℹ️", AlertLevel.WARNING: "⚠️",
                 AlertLevel.CRITICAL: "🔴", AlertLevel.EMERGENCY: "🚨"}
        log_msg = f"{emoji.get(alert.level, '')} [{alert.level.value.upper()}] {alert.title}: {alert.message}"
        if alert.level in [AlertLevel.CRITICAL, AlertLevel.EMERGENCY]:
            logger.error(log_msg)
        elif alert.level == AlertLevel.WARNING:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

    def _send_webhook(self, alert: Alert) -> bool:
        if not HAS_REQUESTS:
            return False
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"[{alert.level.value.upper()}] {alert.title}",
                "text": f"## {alert.title}\n\n**级别**: {alert.level.value.upper()}\n**时间**: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n**来源**: {alert.source}\n\n{alert.message}\n\n> 自进化交易系统自动告警",
            }
        }
        success = False
        for name, url in self.webhook_urls.items():
            try:
                resp = requests.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    logger.info(f"Webhook [{name}] 发送成功")
                    success = True
                else:
                    logger.warning(f"Webhook [{name}] 发送失败: {resp.status_code}")
            except Exception as e:
                logger.error(f"Webhook [{name}] 异常: {e}")
        return success

    def _send_email(self, alert: Alert) -> bool:
        config = self.email_config
        if not config.get("smtp_host") or not config.get("to"):
            return False
        try:
            msg = MIMEMultipart()
            msg["From"] = config.get("from", "alert@self-evolve.local")
            msg["To"] = ", ".join(config["to"]) if isinstance(config["to"], list) else config["to"]
            msg["Subject"] = f"[{alert.level.value.upper()}] {alert.title} - 自进化交易系统"
            body = f"""
            <h2>{alert.title}</h2>
            <p><strong>级别</strong>: {alert.level.value.upper()}</p>
            <p><strong>时间</strong>: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>来源</strong>: {alert.source}</p>
            <hr>
            <p>{alert.message}</p>
            <hr>
            <p><small>自进化交易系统自动告警</small></p>
            """
            msg.attach(MIMEText(body, "html", "utf-8"))
            with smtplib.SMTP_SSL(config["smtp_host"], config.get("smtp_port", 465)) as server:
                if config.get("smtp_user"):
                    server.login(config["smtp_user"], config.get("smtp_password", ""))
                server.send_message(msg)
            logger.info("邮件告警发送成功")
            return True
        except Exception as e:
            logger.error(f"邮件告警发送失败: {e}")
            return False

    def _save_alert(self, alert: Alert):
        try:
            alert_file = Path("reports/alerts") / f"alerts_{datetime.now().strftime('%Y%m%d')}.jsonl"
            with open(alert_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    "level": alert.level.value, "title": alert.title,
                    "message": alert.message, "source": alert.source,
                    "timestamp": alert.timestamp.isoformat(),
                    "metadata": alert.metadata,
                }, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"保存告警失败: {e}")

    def suppress_alerts(self, source: str, duration_minutes: int = 30):
        self.suppressed_until[source] = datetime.now() + timedelta(minutes=duration_minutes)
        logger.info(f"已抑制 {source} 告警 {duration_minutes} 分钟")

    def get_summary(self) -> dict:
        now = datetime.now()
        today_alerts = [a for a in self.alert_history if (now - a.timestamp).total_seconds() < 86400]
        return {
            "total_alerts_today": len(today_alerts),
            "by_level": {
                level.value: sum(1 for a in today_alerts if a.level == level)
                for level in AlertLevel
            },
            "consecutive_losses": self.consecutive_losses,
            "daily_pnl": self.daily_pnl,
            "api_errors": self.api_errors,
            "suppressed_sources": list(self.suppressed_until.keys()),
            "last_data_update": self.last_data_update.isoformat() if self.last_data_update else None,
        }

    def reset_daily(self):
        self.daily_pnl = 0
        self.consecutive_losses = 0
        self.api_errors = 0
        logger.info("每日告警统计已重置")
