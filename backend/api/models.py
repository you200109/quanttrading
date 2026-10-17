"""API 请求模型（Pydantic v2）

集中管理 POST 端点请求体验证。设计原则：
1. 默认值与既有行为完全一致（缺失字段走原默认路径）
2. inst_id/bar/limit 加格式校验——这些值直接流入 OKX API 调用与
   缓存路径构造，格式非法时返回 422 而非把脏值传给下游
3. indicators/strategy 名称白名单——指标名经 pandas_ta getattr 反射
   调用（见 indicators/indicator_engine.py），非法名直接 422
4. coerce_numbers_to_str：兼容历史上传 JSON number 的 limit 字段
"""

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_INST_ID_RE = r'^[A-Za-z0-9-]{3,30}$'
_BAR_RE = r'^[0-9]{1,3}[smHDWM]$'
_LIMIT_RE = r'^[0-9]{1,5}$'
_NAME_RE = r'^[a-z][a-z0-9_]{0,30}$'


class _RequestBase(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)


class IndicatorCalcRequest(_RequestBase):
    """POST /api/indicators/calculate 请求体"""

    inst_id: str = Field('BTC-USDT', pattern=_INST_ID_RE, description='交易对，如 BTC-USDT')
    bar: str = Field('1H', pattern=_BAR_RE, description='K线周期，如 1H/1D/15m')
    indicators: list[str] = Field(default_factory=list, description='指标名列表')
    limit: str = Field('300', pattern=_LIMIT_RE, description='K线根数')

    @field_validator('indicators')
    @classmethod
    def _check_indicator_names(cls, v: list[str]) -> list[str]:
        for name in v:
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,30}', name):
                raise ValueError(f'非法指标名: {name!r}（须为小写字母数字下划线）')
        return v


class BacktestRequest(_RequestBase):
    """POST /api/backtest 请求体"""

    inst_id: str = Field('BTC-USDT', pattern=_INST_ID_RE, description='交易对，如 BTC-USDT')
    bar: str = Field('1H', pattern=_BAR_RE, description='K线周期，如 1H/1D/15m')
    strategy: str = Field('ma_cross', pattern=_NAME_RE, description='策略名')
    params: dict = Field(default_factory=dict, description='策略参数')
    limit: str = Field('300', pattern=_LIMIT_RE, description='K线根数')


class VcBacktestRequest(_RequestBase):
    """POST /api/vc/backtest/vc 请求体"""

    inst_id: str = Field('BTC-USDT', pattern=_INST_ID_RE, description='交易对，如 BTC-USDT')
    bar: str = Field('1D', pattern=_BAR_RE, description='K线周期，如 1H/1D/15m（默认 1D，与历史行为一致）')
    params: dict = Field(default_factory=dict, description='策略参数')
    limit: str = Field('300', pattern=_LIMIT_RE, description='K线根数')


class OrderRequest(_RequestBase):
    """POST /api/order 请求体（交易闭环阶段）

    只放行 OKX 贴现必填形态：数量/价格走数字字符串；limit 单必须带 px；
    simulated=true（模拟盘）为默认，false=实盘且必须 confirm_live=true。
    """

    inst_id: str = Field(..., pattern=_INST_ID_RE, description='交易对，如 BTC-USDT')
    side: str = Field(..., pattern=r'^(buy|sell)$', description='方向')
    ord_type: str = Field('limit', pattern=r'^(limit|market|post_only|fok|ioc)$',
                          description='订单类型（与 OKXTradeService.VALID_ORD_TYPES 对齐）')
    sz: str = Field(..., pattern=r'^[0-9]{1,16}(\.[0-9]{1,8})?$', description='数量（数字字符串，如 0.01）')
    px: Optional[str] = Field(None, pattern=r'^[0-9]{1,12}(\.[0-9]{1,8})?$',
                              description='价格（limit/post_only 必填）')
    td_mode: str = Field('cash', pattern=r'^(cash|cross|isolated)$', description='交易模式')
    simulated: bool = Field(True, description='true=模拟盘（默认）；false=实盘需 confirm_live=true')
    confirm_live: bool = Field(False, description='实盘下单确认开关')

    @model_validator(mode='after')
    def _limit_needs_px(self) -> 'OrderRequest':
        if self.ord_type == 'limit' and self.px is None:
            raise ValueError('limit 订单必须提供 px')
        return self


class CancelOrderRequest(_RequestBase):
    """POST /api/order/cancel 请求体"""

    inst_id: str = Field(..., pattern=_INST_ID_RE, description='交易对，如 BTC-USDT')
    ord_id: str = Field(..., pattern=r'^[A-Za-z0-9-]{1,40}$', description='OKX 订单 ID')
    simulated: bool = Field(True, description='true=模拟盘（默认）')
