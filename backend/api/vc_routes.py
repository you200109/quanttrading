"""
vigilant-couscous 功能整合路由
将 AGI/agents/evolution/strategy/trading/memory 模块整合到主系统 API
"""
import os
import sys
import json
import logging
from pathlib import Path
from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix='/api/vc', tags=['vigilant-couscous'])
logger = logging.getLogger('QuantTrading.vc')

# 将 vc 目录加入 sys.path
VC_ROOT = os.path.join(os.path.dirname(__file__), '..', '..', 'vigilant-couscous')
VC_ROOT = os.path.abspath(VC_ROOT)
if VC_ROOT not in sys.path:
    sys.path.insert(0, VC_ROOT)


# ==================== AGI 进化模块 ====================

@router.get('/agi/status')
async def agi_status():
    """获取 AGI 进化系统状态"""
    try:
        from agi.agi_brain import AGIBrain
        brain = AGIBrain()
        status = brain.get_status() if hasattr(brain, 'get_status') else {'status': 'initialized'}
        return {'code': 0, 'data': status}
    except Exception as e:
        logger.warning(f'AGI status failed: {e}')
        return {'code': 0, 'data': {'status': 'not_available', 'error': '模块加载失败，请查看服务端日志'}}


@router.post('/agi/evolve')
async def agi_evolve(body: dict):
    """触发一次 AGI 进化周期"""
    try:
        from agi.eternal_evolver import EternalEvolver
        evolver = EternalEvolver()
        result = evolver.evolve() if hasattr(evolver, 'evolve') else {'status': 'no_evolve_method'}
        return {'code': 0, 'data': result}
    except Exception as e:
        logger.error(f'AGI evolve failed: {e}')
        return {'code': 1, 'msg': '操作失败，请查看服务端日志'}


@router.get('/agi/learning-report')
async def agi_learning_report():
    """获取持续学习报告"""
    try:
        from agi.continuous_learner import ContinuousLearner
        learner = ContinuousLearner()
        report = learner.get_report() if hasattr(learner, 'get_report') else {'status': 'no_report_method'}
        return {'code': 0, 'data': report}
    except Exception as e:
        logger.warning(f'AGI learning report failed: {e}')
        return {'code': 0, 'data': {'status': 'not_available', 'error': '模块加载失败，请查看服务端日志'}}


# ==================== 策略与回测模块 ====================

@router.get('/strategies')
async def list_strategies():
    """列出所有可用策略"""
    strategies = []
    # 内置策略
    strategies.extend([
        {'name': 'ma_cross', 'description': '均线交叉策略', 'params': {'fast': 5, 'slow': 20}},
        {'name': 'rsi_reversal', 'description': 'RSI 反转策略', 'params': {'period': 14, 'oversold': 30, 'overbought': 70}},
        {'name': 'bollinger_breakout', 'description': '布林带突破策略', 'params': {'period': 20, 'std': 2}},
    ])
    # 尝试加载 vc 策略库
    try:
        lib_path = os.path.join(VC_ROOT, 'memory', 'nexus', 'gh_strategy_library.json')
        if os.path.exists(lib_path):
            with open(lib_path, encoding='utf-8') as f:
                lib = json.load(f)
            for s in lib.get('strategies', []):
                strategies.append({
                    'name': s.get('name', 'unknown'),
                    'description': 'GitHub 学习策略',
                    'params': {k: v for k, v in s.items() if k != 'name'}
                })
    except Exception as e:
        logger.warning(f'Load vc strategies failed: {e}')
    return {'code': 0, 'count': len(strategies), 'data': strategies}


@router.post('/backtest/vc')
async def run_vc_backtest(body: dict):
    """使用 vc 回测验证器运行策略回测
    :body: { inst_id, bar, params, limit }
    """
    import pandas as pd
    inst_id = body.get('inst_id', 'BTC-USDT')
    bar = body.get('bar', '1D')
    params = body.get('params', {})
    limit = body.get('limit', '300')

    # 复用主系统 OKX 数据服务获取数据
    from backend.core.okx_data_service import get_data_service
    svc = get_data_service()
    raw = svc.get_candlesticks(inst_id, bar, limit)

    if not raw:
        return {'code': 1, 'msg': 'No data'}

    cols = ['ts', 'open', 'high', 'low', 'close', 'vol', 'volCcy', 'volCcyQuote', 'confirm']
    df = pd.DataFrame(raw, columns=cols)
    for c in ['open', 'high', 'low', 'close', 'vol']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['ts'] = pd.to_datetime(df['ts'].astype(float), unit='ms')

    try:
        from evolution.backtest_validator import BacktestValidator
        validator = BacktestValidator(df)
        result = validator.validate_strategy(params, 'vc_strategy')
        return {
            'code': 0,
            'data': {
                'strategy_name': result.strategy_name,
                'score': result.score,
                'passed': result.passed if hasattr(result, 'passed') else None,
            }
        }
    except Exception as e:
        logger.error(f'VC backtest failed: {e}')
        return {'code': 1, 'msg': '操作失败，请查看服务端日志'}


# ==================== 风控模块 ====================

@router.get('/risk/status')
async def risk_status():
    """获取风控系统状态"""
    try:
        from agents.risk_manager import RiskManagerAgent, RiskLimits
        rm = RiskManagerAgent(limits=RiskLimits())
        return {
            'code': 0,
            'data': {
                'limits': {
                    'max_position_pct': rm.limits.max_position_pct,
                    'max_drawdown_pct': rm.limits.max_drawdown_pct,
                    'stop_loss_pct': rm.limits.stop_loss_pct,
                    'take_profit_pct': rm.limits.take_profit_pct,
                },
                'current_drawdown': rm.current_drawdown,
                'daily_pnl': rm.daily_pnl,
                'risk_events_count': len(rm.risk_events),
            }
        }
    except Exception as e:
        logger.warning(f'Risk status failed: {e}')
        return {'code': 0, 'data': {'status': 'not_available', 'error': '模块加载失败，请查看服务端日志'}}


@router.post('/risk/approve')
async def risk_approve_trade(body: dict):
    """审批交易信号
    :body: { signal: { symbol, confidence, action }, portfolio: { total_value } }
    """
    try:
        from agents.risk_manager import RiskManagerAgent, RiskLimits
        rm = RiskManagerAgent(limits=RiskLimits())
        signal = body.get('signal', {})
        portfolio = body.get('portfolio', {})
        approved, reason = rm.approve_trade(signal, portfolio)
        return {'code': 0, 'data': {'approved': approved, 'reason': reason}}
    except Exception as e:
        logger.error(f'Risk approve failed: {e}')
        return {'code': 1, 'msg': '操作失败，请查看服务端日志'}


# ==================== 记忆存储模块 ====================

@router.get('/memory/nexus')
async def get_nexus_data():
    """获取记忆存储数据列表"""
    nexus_dir = os.path.join(VC_ROOT, 'memory', 'nexus')
    files = []
    if os.path.exists(nexus_dir):
        for f in os.listdir(nexus_dir):
            if f.endswith('.json'):
                filepath = os.path.join(nexus_dir, f)
                files.append({
                    'name': f,
                    'size': os.path.getsize(filepath),
                    'modified': os.path.getmtime(filepath)
                })
    return {'code': 0, 'count': len(files), 'data': files}


@router.get('/memory/nexus/{filename}')
async def get_nexus_file(filename: str):
    """获取记忆存储文件内容（仅允许纯文件名，拒绝路径遍历）"""
    # 安全校验 1：拒绝任何路径分隔符与相对路径片段
    if (filename != os.path.basename(filename)
            or '/' in filename or '\\' in filename
            or filename in ('.', '..') or filename.startswith('.')):
        return {'code': 1, 'msg': 'Invalid filename'}
    nexus_dir = os.path.abspath(os.path.join(VC_ROOT, 'memory', 'nexus'))
    filepath = os.path.abspath(os.path.join(nexus_dir, filename))
    # 安全校验 2：解析后的绝对路径必须仍在 nexus 目录内
    if not filepath.startswith(nexus_dir + os.sep):
        return {'code': 1, 'msg': 'Invalid filename'}
    if not os.path.isfile(filepath):
        return {'code': 1, 'msg': 'File not found'}
    try:
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
        return {'code': 0, 'data': data}
    except Exception as e:
        logger.warning(f'Read nexus file {filename} failed: {type(e).__name__}')
        return {'code': 1, 'msg': '文件读取失败，请查看服务端日志'}


# ==================== GitHub 学习模块 ====================

@router.post('/github/learn')
async def github_learn(body: dict):
    """触发 GitHub 策略学习"""
    try:
        n_repos = body.get('n_repos', 3)
        from strategy.learning_engine import LearningEngine
        learner = LearningEngine()
        knowledge = learner.daily_search_and_learn(n_repos=n_repos)
        return {
            'code': 0,
            'count': len(knowledge) if knowledge else 0,
            'data': knowledge or []
        }
    except Exception as e:
        logger.error(f'GitHub learn failed: {e}')
        return {'code': 1, 'msg': '操作失败，请查看服务端日志'}


@router.get('/github/seeds')
async def get_github_seeds(n: int = 5):
    """获取种子参数"""
    try:
        from strategy.learning_engine import LearningEngine
        learner = LearningEngine()
        seeds = learner.get_seed_params(n=n)
        return {'code': 0, 'count': len(seeds), 'data': seeds}
    except Exception as e:
        logger.warning(f'GitHub seeds failed: {e}')
        return {'code': 0, 'count': 0, 'data': []}
