"""
可观测性模块
- 链路追踪：轻量级请求追踪（contextvars + logging）
- 实时告警：基于阈值的告警触发和 Issue 创建
- 仪表盘：系统状态汇总数据
"""
import time
import uuid
import logging
import threading
from contextvars import ContextVar
from typing import Dict, List
from datetime import datetime, timezone

logger = logging.getLogger('Observability')

# ==================== 链路追踪 ====================

# 请求级追踪上下文
trace_id_var: ContextVar[str] = ContextVar('trace_id', default='')
request_start_var: ContextVar[float] = ContextVar('request_start', default=0.0)

# 追踪记录存储（内存，生产环境可替换为 Redis/数据库）
_trace_records: List[Dict] = []
_trace_lock = threading.Lock()
_MAX_RECORDS = 1000


def generate_trace_id() -> str:
    """生成唯一追踪 ID"""
    return uuid.uuid4().hex[:16]


def start_trace(path: str) -> str:
    """开始请求追踪"""
    trace_id = generate_trace_id()
    trace_id_var.set(trace_id)
    request_start_var.set(time.time())
    
    record = {
        'trace_id': trace_id,
        'path': path,
        'start_time': datetime.now(timezone.utc).isoformat(),
        'timestamp': time.time(),
    }
    
    with _trace_lock:
        _trace_records.append(record)
        if len(_trace_records) > _MAX_RECORDS:
            _trace_records.pop(0)
    
    logger.info(f'Trace started: {trace_id} for {path}')
    return trace_id


def end_trace(status_code: int, extra: Dict = None):
    """结束请求追踪"""
    trace_id = trace_id_var.get()
    if not trace_id:
        return
    
    duration = time.time() - request_start_var.get()
    
    with _trace_lock:
        for record in reversed(_trace_records):
            if record['trace_id'] == trace_id:
                record['duration_ms'] = round(duration * 1000, 2)
                record['status_code'] = status_code
                record['end_time'] = datetime.now(timezone.utc).isoformat()
                if extra:
                    record.update(extra)
                break
    
    logger.info(f'Trace ended: {trace_id} status={status_code} duration={duration*1000:.1f}ms')


def get_trace_records(limit: int = 50) -> List[Dict]:
    """获取追踪记录"""
    with _trace_lock:
        return list(reversed(_trace_records[-limit:]))


def get_trace_stats() -> Dict:
    """获取追踪统计"""
    with _trace_lock:
        if not _trace_records:
            return {'total': 0, 'avg_duration_ms': 0, 'error_count': 0}
        
        completed = [r for r in _trace_records if 'duration_ms' in r]
        if not completed:
            return {'total': len(_trace_records), 'avg_duration_ms': 0, 'error_count': 0}
        
        durations = [r['duration_ms'] for r in completed]
        errors = len([r for r in completed if r.get('status_code', 200) >= 400])
        
        return {
            'total': len(_trace_records),
            'completed': len(completed),
            'avg_duration_ms': round(sum(durations) / len(durations), 2),
            'max_duration_ms': max(durations),
            'min_duration_ms': min(durations),
            'error_count': errors,
            'error_rate': round(errors / len(completed) * 100, 2),
        }


# ==================== 实时告警 ====================

# 告警规则
_alert_rules = []
_alert_history: List[Dict] = []
_alert_lock = threading.Lock()


class AlertRule:
    """告警规则"""
    def __init__(self, name: str, condition: callable, message: str, severity: str = 'warning'):
        self.name = name
        self.condition = condition
        self.message = message
        self.severity = severity
        self.last_triggered = None
        self.trigger_count = 0


def add_alert_rule(name: str, condition: callable, message: str, severity: str = 'warning'):
    """添加告警规则"""
    rule = AlertRule(name, condition, message, severity)
    _alert_rules.append(rule)
    logger.info(f'Alert rule added: {name}')


def check_alerts(context: Dict) -> List[Dict]:
    """检查告警规则"""
    triggered = []
    for rule in _alert_rules:
        try:
            if rule.condition(context):
                alert = {
                    'name': rule.name,
                    'message': rule.message,
                    'severity': rule.severity,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'context': context,
                }
                rule.last_triggered = alert['timestamp']
                rule.trigger_count += 1
                triggered.append(alert)
                
                with _alert_lock:
                    _alert_history.append(alert)
                    if len(_alert_history) > 100:
                        _alert_history.pop(0)
                
                logger.warning(f'Alert triggered: {rule.name} - {rule.message}')
        except Exception as e:
            logger.error(f'Alert check failed for {rule.name}: {e}')
    return triggered


def get_alert_history(limit: int = 20) -> List[Dict]:
    """获取告警历史"""
    with _alert_lock:
        return list(reversed(_alert_history[-limit:]))


# 初始化默认告警规则
def _init_default_alerts():
    """初始化默认告警规则"""
    add_alert_rule(
        'high_error_rate',
        lambda ctx: ctx.get('error_rate', 0) > 10,
        'Error rate exceeds 10%',
        'critical'
    )
    add_alert_rule(
        'high_latency',
        lambda ctx: ctx.get('avg_duration_ms', 0) > 5000,
        'Average latency exceeds 5 seconds',
        'warning'
    )
    add_alert_rule(
        'memory_high',
        lambda ctx: ctx.get('memory_pct', 0) > 80,
        'Memory usage exceeds 80%',
        'warning'
    )
    add_alert_rule(
        'service_down',
        lambda ctx: not ctx.get('healthy', True),
        'Service is not responding',
        'critical'
    )

_init_default_alerts()


# ==================== 仪表盘 ====================

def get_dashboard_data() -> Dict:
    """获取仪表盘数据"""
    from backend.core.resilience import resource_limiter
    from backend.indicators.indicator_engine import get_indicator_engine
    
    # 系统资源
    resources = resource_limiter.get_status()
    
    # 追踪统计
    trace_stats = get_trace_stats()
    
    # 告警检查
    alert_context = {
        'error_rate': trace_stats.get('error_rate', 0),
        'avg_duration_ms': trace_stats.get('avg_duration_ms', 0),
        'memory_pct': resources.get('memory', {}).get('usage_pct', 0),
        'healthy': True,
    }
    active_alerts = check_alerts(alert_context)
    
    # 指标引擎状态
    try:
        engine = get_indicator_engine()
        indicator_count = engine.get_indicator_count()
    except Exception:
        indicator_count = 0
    
    return {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'system': {
            'memory_mb': resources.get('memory', {}).get('memory_mb', 0),
            'memory_max_mb': resources.get('memory', {}).get('max_mb', 0),
            'memory_pct': resources.get('memory', {}).get('usage_pct', 0),
            'cpu_pct': resources.get('cpu', {}).get('cpu_pct', 0),
            'memory_exceeded': resources.get('memory', {}).get('exceeded', False),
        },
        'requests': {
            'total': trace_stats.get('total', 0),
            'completed': trace_stats.get('completed', 0),
            'avg_duration_ms': trace_stats.get('avg_duration_ms', 0),
            'max_duration_ms': trace_stats.get('max_duration_ms', 0),
            'error_count': trace_stats.get('error_count', 0),
            'error_rate': trace_stats.get('error_rate', 0),
        },
        'alerts': {
            'active_count': len(active_alerts),
            'active': active_alerts,
            'history_count': len(_alert_history),
        },
        'indicators': {
            'total': indicator_count,
        },
    }
