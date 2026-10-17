"""
FastAPI 后端路由
- 行情接口: K线、盘口、Ticker
- 交易接口: 挂单、历史委托、成交明细、账单流水
- 指标接口: 指标列表、指标计算
- WebSocket: 实时数据推送
"""
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from typing import Optional

from backend.core.okx_data_service import get_data_service
from backend.core.okx_trade_service import get_trade_service
from backend.core.trade_gate import pre_trade_check
from okx.ccxt.base.errors import NetworkError  # noqa: F401  随 okx-exchange 一同换血，契约见 okx_trade_service
from backend.indicators.indicator_engine import get_indicator_engine
from backend.core.backtest_engine import get_backtest_engine
from backend.core.frame_utils import candles_to_frame
from backend.api.models import BacktestRequest, CancelOrderRequest, IndicatorCalcRequest, OrderRequest

router = APIRouter()

# 下单/撤单审计日志（专用 logger，便于 grep；密钥与普通参数分开，绝不打印凭据）
audit_logger = logging.getLogger('OrderAudit')


# ==================== 行情接口 ====================

@router.get('/api/klines/{inst_id}')
async def get_klines(inst_id: str, bar: str = '1H', limit: str = '300'):
    """获取 K 线数据"""
    svc = get_data_service()
    data = svc.get_candlesticks(inst_id, bar, limit)
    return {'code': 0, 'data': data}


@router.get('/api/klines/multi/{inst_id}')
async def get_multi_klines(inst_id: str, limit: str = '300'):
    """获取多周期 K 线数据"""
    svc = get_data_service()
    data = svc.get_multi_period_klines(inst_id, limit)
    return {'code': 0, 'data': data}


@router.get('/api/orderbook/{inst_id}')
async def get_orderbook(inst_id: str, depth: str = '5'):
    """获取盘口深度"""
    svc = get_data_service()
    data = svc.get_orderbook(inst_id, depth)
    return {'code': 0, 'data': data}


@router.get('/api/ticker/{inst_id}')
async def get_ticker(inst_id: str):
    """获取最新行情"""
    svc = get_data_service()
    data = svc.get_ticker(inst_id)
    return {'code': 0, 'data': data}


@router.get('/api/tickers')
async def get_all_tickers(inst_type: str = 'SPOT'):
    """获取所有行情"""
    svc = get_data_service()
    data = svc.get_all_tickers(inst_type)
    return {'code': 0, 'data': data}


@router.get('/api/instruments')
async def get_instruments(inst_type: str = 'SPOT'):
    """获取交易产品列表"""
    svc = get_data_service()
    data = svc.get_instruments(inst_type)
    return {'code': 0, 'data': data}


# ==================== 交易接口 ====================

@router.get('/api/orders/pending')
async def get_pending_orders(inst_type: str = 'SPOT', inst_id: Optional[str] = None):
    """获取挂单（未成交订单）"""
    svc = get_trade_service()
    data = svc.get_pending_orders(inst_type, inst_id)
    return {'code': 0, 'data': data}


@router.get('/api/orders/history')
async def get_orders_history(inst_type: str = 'SPOT', limit: str = '50'):
    """获取近 7 天历史委托"""
    svc = get_trade_service()
    data = svc.get_orders_history(inst_type, limit)
    return {'code': 0, 'data': data}


@router.get('/api/orders/history/archive')
async def get_orders_history_archive(inst_type: str = 'SPOT', limit: str = '50'):
    """获取近 3 个月历史委托"""
    svc = get_trade_service()
    data = svc.get_orders_history_archive(inst_type, limit)
    return {'code': 0, 'data': data}


@router.get('/api/fills')
async def get_fills(inst_type: str = 'SPOT', limit: str = '50'):
    """获取近 3 天成交明细"""
    svc = get_trade_service()
    data = svc.get_fills(inst_type, limit)
    return {'code': 0, 'data': data}


@router.get('/api/fills/history')
async def get_fills_history(inst_type: str = 'SPOT', limit: str = '50'):
    """获取近 3 个月成交明细"""
    svc = get_trade_service()
    data = svc.get_fills_history(inst_type, limit)
    return {'code': 0, 'data': data}


@router.get('/api/bills')
async def get_bills(limit: str = '50'):
    """获取近 7 天账单流水"""
    svc = get_trade_service()
    data = svc.get_account_bills(limit)
    return {'code': 0, 'data': data}


@router.get('/api/bills/archive')
async def get_bills_archive(limit: str = '50'):
    """获取近 3 个月账单流水"""
    svc = get_trade_service()
    data = svc.get_account_bills_archive(limit)
    return {'code': 0, 'data': data}


@router.get('/api/account/balance')
async def get_account_balance():
    """获取账户余额"""
    svc = get_trade_service()
    data = svc.get_account_balance()
    return {'code': 0, 'data': data}


@router.get('/api/account/positions')
async def get_account_positions(inst_type: Optional[str] = None):
    """获取持仓信息"""
    svc = get_trade_service()
    data = svc.get_account_position(inst_type)
    return {'code': 0, 'data': data}


# ==================== 交易执行（下单 / 撤单） ====================
# 安全链：X-API-Key 认证（中间件）→ Pydantic 422 → 实盘 confirm_live 显式确认
#        → 前置风控闸（trade_gate）→ okx-exchange SDK（模拟盘默认）→ 审计日志
# 差异化失败语义（不静默降级）：
#        实盘未确认 / 风控拒绝 → HTTP 403；业务拒单 → 200 信封 code=1；传输层错误 → HTTP 502

@router.post('/api/order')
async def place_order(body: OrderRequest):
    """下单（默认模拟盘；实盘需 confirm_live=true，且被前置风控闸检查）"""
    if not body.simulated and not body.confirm_live:
        audit_logger.warning('ORDER/PLACE rejected (live not confirmed) inst_id=%s side=%s',
                             body.inst_id, body.side)
        return JSONResponse(status_code=403, content={
            'code': 1, 'msg': '实盘下单被拒：confirm_live=false（必须显式确认实盘）'})

    approved, reason = pre_trade_check(body.inst_id, body.side, body.sz, simulated=body.simulated)
    if not approved:
        audit_logger.warning('ORDER/PLACE rejected (risk gate) inst_id=%s side=%s: %s',
                             body.inst_id, body.side, reason)
        return JSONResponse(status_code=403, content={'code': 1, 'msg': f'风控拒绝下单: {reason}'})

    audit_logger.info(
        'ORDER/PLACE simulated=%s inst_id=%s side=%s ord_type=%s sz=%s px=%s td_mode=%s',
        body.simulated, body.inst_id, body.side, body.ord_type, body.sz, body.px, body.td_mode)
    svc = get_trade_service(body.simulated)
    try:
        resp = svc.place_order(body.inst_id, body.side, body.ord_type, body.sz,
                               px=body.px, td_mode=body.td_mode)
    except NetworkError as exc:
        audit_logger.warning('ORDER/PLACE network error: %s', type(exc).__name__)
        return JSONResponse(status_code=502, content={
            'code': 1, 'msg': f'OKX 网络错误: {type(exc).__name__}'})
    if isinstance(resp, dict) and resp.get('code') == '0':
        audit_logger.info('ORDER/PLACE accepted: %s', resp.get('data'))
        return {'code': 0, 'msg': '下单成功', 'data': resp.get('data', [])}
    code = resp.get('code') if isinstance(resp, dict) else '1'
    msg = resp.get('msg') if isinstance(resp, dict) else str(resp)
    audit_logger.warning('ORDER/PLACE rejected by OKX: code=%s msg=%s', code, msg)
    return {'code': 1, 'msg': f'OKX 拒单: {msg}', 'data': resp if isinstance(resp, dict) else None}


@router.post('/api/order/cancel')
async def cancel_order(body: CancelOrderRequest):
    """撤单（默认模拟盘）"""
    audit_logger.info('ORDER/CANCEL simulated=%s inst_id=%s ord_id=%s',
                      body.simulated, body.inst_id, body.ord_id)
    svc = get_trade_service(body.simulated)
    try:
        resp = svc.cancel_order(body.inst_id, body.ord_id)
    except NetworkError as exc:
        audit_logger.warning('ORDER/CANCEL network error: %s', type(exc).__name__)
        return JSONResponse(status_code=502, content={
            'code': 1, 'msg': f'OKX 网络错误: {type(exc).__name__}'})
    if isinstance(resp, dict) and resp.get('code') == '0':
        audit_logger.info('ORDER/CANCEL accepted: %s', resp.get('data'))
        return {'code': 0, 'msg': '撤单请求已提交', 'data': resp.get('data', [])}
    code = resp.get('code') if isinstance(resp, dict) else '1'
    msg = resp.get('msg') if isinstance(resp, dict) else str(resp)
    audit_logger.warning('ORDER/CANCEL rejected by OKX: code=%s msg=%s', code, msg)
    return {'code': 1, 'msg': f'OKX 撤单失败: {msg}', 'data': resp if isinstance(resp, dict) else None}


# ==================== 指标接口 ====================

@router.get('/api/indicators')
async def list_indicators(category: Optional[str] = None):
    """列出所有可用指标"""
    engine = get_indicator_engine()
    data = engine.list_indicators(category)
    return {'code': 0, 'count': len(data), 'data': data}


@router.get('/api/indicators/categories')
async def get_indicator_categories():
    """获取指标分类统计"""
    engine = get_indicator_engine()
    data = engine.get_categories()
    return {'code': 0, 'total': engine.get_indicator_count(), 'data': data}


@router.post('/api/indicators/calculate')
async def calculate_indicators(body: IndicatorCalcRequest):
    """计算指定指标
    :body: { inst_id, bar, indicators: [name1, name2, ...], limit }（见 api/models.py）
    """
    inst_id = body.inst_id
    bar = body.bar
    indicators = body.indicators
    limit = body.limit

    svc = get_data_service()
    raw = svc.get_candlesticks(inst_id, bar, limit)

    if not raw:
        return {'code': 1, 'msg': 'No data'}

    df = candles_to_frame(raw)

    engine = get_indicator_engine()
    df = engine.calculate_multiple(df, indicators)

    # 转为可序列化格式
    result = df.fillna('').to_dict(orient='records')
    return {'code': 0, 'count': len(result), 'data': result}


# ==================== 回测接口 ====================

@router.post('/api/backtest')
async def run_backtest(body: BacktestRequest):
    """运行策略回测
    :body: { inst_id, bar, strategy, params, limit }（见 api/models.py）
    """
    inst_id = body.inst_id
    bar = body.bar
    strategy = body.strategy
    params = body.params
    limit = body.limit

    svc = get_data_service()
    raw = svc.get_candlesticks(inst_id, bar, limit)

    if not raw:
        return {'code': 1, 'msg': 'No data'}

    df = candles_to_frame(raw)

    engine = get_backtest_engine()
    result = engine.run(df, strategy, params)
    return result


# ==================== 历史数据下载接口 ====================

@router.get('/api/history/download')
async def download_history(inst_id: str = 'BTC-USDT', bar: str = '1H', limit: str = '100'):
    """下载历史K线数据（CSV格式）"""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    svc = get_data_service()
    raw = svc.get_candlesticks(inst_id, bar, limit)

    if not raw:
        return {'code': 1, 'msg': 'No data'}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'volume', 'volume_quote', 'confirm'])
    for row in raw:
        writer.writerow(row)

    output.seek(0)
    filename = f'{inst_id}_{bar}_{limit}.csv'
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )


# ==================== WebSocket 实时推送 ====================

@router.websocket('/ws/market')
async def ws_market(websocket: WebSocket, inst_id: str = 'BTC-USDT'):
    """公共 WebSocket 实时行情推送"""
    await websocket.accept()
    svc = get_data_service()

    async def on_data(data):
        await websocket.send_json(data)

    try:
        await svc.start_public_ws(inst_id, on_data)
    except WebSocketDisconnect:
        await svc.stop_ws('public')
    except Exception:
        await svc.stop_ws('public')


@router.websocket('/ws/trade')
async def ws_trade(websocket: WebSocket):
    """私有 WebSocket 交易状态推送"""
    await websocket.accept()
    svc = get_trade_service()

    async def on_data(data):
        await websocket.send_json(data)

    try:
        await svc.start_private_ws(on_data)
    except WebSocketDisconnect:
        await svc.stop_private_ws()
    except Exception:
        await svc.stop_private_ws()
