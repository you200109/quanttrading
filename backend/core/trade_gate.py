"""下单前置风控闸（交易闭环阶段）

POST /api/order 在提交 OKX 之前调用 pre_trade_check：
- 复用 vigilant-couscous 的 RiskManagerAgent.approve_trade（与 /api/vc/risk/approve 同一套阈值）
- ORDER_RISK_GATE=0 可显式关闭（默认开启）
- 风控模块不可用时显式拒绝（项目原则：不静默降级放行）
"""
import logging
import os
import sys

logger = logging.getLogger('TradeGate')

# 与 backend/api/vc_routes.py 相同的 vc 源码路径注入（幂等）
VC_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'vigilant-couscous'))
if VC_ROOT not in sys.path:
    sys.path.insert(0, VC_ROOT)


def pre_trade_check(inst_id: str, side: str, sz: str, simulated: bool = True):
    """预交易风控检查，返回 (approved: bool, reason: str)。

    任何失败路径（闸关闭除外）都显式拒绝，不静默放行。
    """
    if os.getenv('ORDER_RISK_GATE', '1') != '1':
        return True, '风控闸已通过 ORDER_RISK_GATE=0 关闭'
    try:
        from agents.risk_manager import RiskManagerAgent, RiskLimits
    except Exception as exc:
        logger.error('预交易风控不可用: %s', exc)
        return False, f'风控模块不可用（{type(exc).__name__}），拒绝下单'
    signal = {'symbol': inst_id, 'confidence': 1.0, 'action': side}
    portfolio = {'total_value': 0, 'positions': {}}
    approved, reason = RiskManagerAgent(limits=RiskLimits()).approve_trade(signal, portfolio)
    if not approved:
        logger.warning('预交易风控拒绝 %s %s sz=%s: %s', side, inst_id, sz, reason)
    return approved, reason
