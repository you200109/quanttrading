"""
FastAPI 后端路由
- 行情接口: K线、盘口、Ticker
- 交易接口: 挂单、历史委托、成交明细、账单流水
- 指标接口: 指标列表、指标计算
- WebSocket: 实时数据推送
"""
import os
import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse
from typing import Optional

from backend.core.okx_data_service import get_data_service
from backend.core.okx_trade_service import get_trade_service
from backend.indicators.indicator_engine import get_indicator_engine
from backend.core.backtest_engine import get_backtest_engine
from backend.core.frame_utils import candles_to_frame
from backend.api.models import BacktestRequest, IndicatorCalcRequest

router = APIRouter()


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
