"""K3 历史 K 线回补引擎测试——transport 注入，全程零网络。

覆盖：
- bar 校验与日期解析（非法值显式报错）
- 分页向历史方向行走：cursor 链路、短页提前终止、MAX_PAGES 上限标 partial
- 合并去重排序与区间过滤（同 ts：已完结 confirm='1' 存量胜出未完结新快照）
- 行载荷形状校验（官方 v5 数组口径 [ts,o,h,l,c,...]，形状异常显式失败）
- 原子落盘：单文件有序、失败不碰旧文件
- 缺口检测：缺失格点 → status=partial 显式报缺口（不装补全）
- 显式失败：业务信封错误 / TransportError → status=failed、errors 非空
- 断点续传：状态 last_ts + 1 步长起拉；无状态无 start 显式报错；状态损坏降级
- daemon：轮数上限可控退出，失败轮显式计数
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import backend.core.history_backfill as hb  # noqa: E402
from backend.core.history_backfill import (  # noqa: E402
    HistoryBackfill, OkxTransport, TransportError, _to_ms, _row_from_raw,
    CSV_COLUMNS)

H_PATH = '/api/v5/market/history-candles'


def row(ts, o='1', c='2', confirm='1'):
    """按 OKX v5 官方数组口径 [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm] 造一行"""
    return [str(ts), o, '3', '0', c, '10', '10', '10', confirm]


class FakeTransport:
    """按预置页序列回放；记录每次 params；可选注入业务信封错误/传输异常"""

    def __init__(self, pages=None, error=None, transport_error=None):
        self.pages = list(pages) if pages is not None else []
        self.error = error
        self.transport_error = transport_error
        self.calls = []

    def get(self, path, params=None):
        assert path == H_PATH
        self.calls.append(dict(params or {}))
        if self.error:
            raise RuntimeError(f'OKX 业务信封错误: '
                               f"{self.error.get('msg', self.error.get('code'))}")
        if self.transport_error:
            raise TransportError('SimulatedConnectionError: boom')
        if not self.pages:
            return {'code': '0', 'msg': '', 'data': []}
        page = self.pages.pop(0)
        return {'code': '0', 'msg': '', 'data': page}


@pytest.fixture
def store(tmp_path):
    return tmp_path / 'marketdata'


def engine(store, bar='1H', pages=None, error=None, transport_error=None):
    return HistoryBackfill('BTC-USDT', bar=bar, store_dir=store,
                           transport=FakeTransport(pages=pages, error=error,
                                                   transport_error=transport_error),
                           use_limiter=False)


def seed_store(engine_obj, rows):
    """预置存量 CSV（已完结 confirm='1'）"""
    engine_obj.store_dir.mkdir(parents=True, exist_ok=True)
    with open(engine_obj.csv_path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for rec in rows:
            w.writerow({c: rec[c] for c in CSV_COLUMNS})


# ==================== 构造与解析 ====================

def test_unsupported_bar_rejected(store):
    with pytest.raises(ValueError):
        HistoryBackfill('BTC-USDT', bar='1W', store_dir=store, transport=FakeTransport())


def test_to_ms_formats():
    ms = _to_ms('2024-01-01')
    assert datetime.utcfromtimestamp(ms / 1000.0).year == 2024
    assert _to_ms('2024-01-02') == _to_ms('2024-01-01') + hb.BAR_MS['1D']
    with pytest.raises(ValueError):
        _to_ms('not-a-date')


def test_row_from_raw_array_mapping():
    """"官方数组口径位置映射 + 形状异常显式报错"""
    ts, rec = _row_from_raw(row(1706745600000))
    assert ts == 1706745600000
    assert rec['open'] == '1' and rec['high'] == '3'
    assert rec['low'] == '0' and rec['close'] == '2'
    assert rec['confirm'] == '1' and rec['ts'] == '1706745600000'
    with pytest.raises(ValueError):
        _row_from_raw(['1706745600000', '1', '2'])        # 列数不足
    with pytest.raises(ValueError):
        _row_from_raw({'ts': '1'})                        # 非数组载荷


def test_transport_env_fallback(monkeypatch):
    monkeypatch.setenv('OKX_API_HOST', 'aws.okx.com')
    monkeypatch.setenv('OKX_PROXY', 'http://127.0.0.1:7890')
    t = OkxTransport()
    assert t.host == 'aws.okx.com'
    assert t.proxies == {'http': 'http://127.0.0.1:7890',
                         'https': 'http://127.0.0.1:7890'}
    monkeypatch.delenv('OKX_PROXY', raising=False)
    assert OkxTransport().proxies is None


# ==================== 分页行走 ====================

def test_pagination_walks_backwards_cursor_chain(store):
    """cursor=上页最旧 ts；覆盖完 [start, end] 后 status=ok"""
    step = hb.BAR_MS['1H']
    base = _to_ms('2024-01-10')
    new_page = [row(base + step * i) for i in range(100)]
    old_page = [row(base - step * i) for i in range(100)]
    e = engine(store, pages=[new_page, old_page])
    rep = e.run(start=base - step * 99, end=base + step * 99)
    assert len(e.transport.calls) == 2
    assert 'after' not in e.transport.calls[0]            # 首页从最新起拉
    assert e.transport.calls[1]['after'] == str(base)     # cursor = 上页最旧
    assert rep['status'] == 'ok'
    assert rep['total_rows'] == 199


def test_pagination_stops_on_short_page(store):
    step = hb.BAR_MS['1H']
    base = _to_ms('2024-01-10')
    short = [row(base + step * i) for i in range(37)]
    e = engine(store, pages=[short])
    rep = e.run(start=base, end=base + step * 36)
    assert len(e.transport.calls) == 1
    assert rep['status'] == 'ok' and rep['total_rows'] == 37


def test_max_pages_guard_marks_partial(store):
    """翻页达上限：status=partial 且 errors 里显式说明，绝不装 ok"""
    step = hb.BAR_MS['1H']
    full_page = [row(_to_ms('2024-06-01') + step * i) for i in range(100)]
    e = engine(store, pages=[full_page] * 500)
    e.MAX_PAGES_PER_RUN = 3
    rep = e.run(start=_to_ms('2024-01-01'), end=_to_ms('2024-12-31'))
    assert len(e.transport.calls) == 3
    assert rep['status'] == 'partial'
    assert any('上限' in err for err in rep['errors'])


def test_gap_detection_marks_partial(store):
    """页提前空了但区间未盖满：缺口检测显式 partial"""
    step = hb.BAR_MS['1H']
    base = _to_ms('2024-06-01')
    recent = [row(base + step * i) for i in range(5)]
    e = engine(store, pages=[recent])
    rep = e.run(start=base - step * 40, end=base + step * 40)
    assert rep['status'] == 'partial'
    assert rep['gaps']
    assert any('缺口' in err for err in rep['errors'])


# ==================== 合并去重 / 落盘 ====================

def test_merge_dedupe_completed_wins(store):
    """同 ts：已完结(confirm='1')存量胜出未完结(confirm='0')新快照"""
    step = hb.BAR_MS['1H']
    base = _to_ms('2024-02-10')
    seed_store(engine(store),
               [{'ts': str(base), 'open': 'old-o', 'high': 'old-h', 'low': 'old-l',
                 'close': 'old-c', 'vol': '9', 'volCcy': '9', 'volCcyQuote': '9',
                 'confirm': '1'}])
    fetched = [row(base, confirm='0')] + [row(base - step * i) for i in (1, 2, 3)]
    e = engine(store, pages=[fetched])
    rep = e.run(start=base - step * 3, end=base)
    assert rep['status'] == 'ok'
    assert rep['total_rows'] == 4
    rows = e.load_existing()
    assert rows[base]['close'] == 'old-c'                 # 已完结优先
    assert rows[base - step * 1]['close'] == '2'          # 新行入库


def test_store_is_sorted_and_deduped(store):
    step = hb.BAR_MS['1H']
    base = _to_ms('2024-02-10')
    page = [row(base - step * i) for i in range(5)]       # DESC 来源
    e = engine(store, pages=[page])
    rep = e.run(start=base - step * 4, end=base)
    assert rep['status'] == 'ok'
    lines = e.csv_path.read_text(encoding='utf-8').strip().splitlines()
    ts_list = [int(l.split(',')[0]) for l in lines[1:]]
    assert ts_list == [base - step * 4 + step * i for i in range(5)]  # 升序无重复


def test_range_filter_drops_out_of_range(store):
    """区间外行（跨页越界）不落盘"""
    step = hb.BAR_MS['1H']
    base = _to_ms('2024-02-10')
    page = [row(base + step * 50)] + [row(base - step * i) for i in (0, 1, 2, 3)]
    e = engine(store, pages=[page])
    rep = e.run(start=base - step * 3, end=base)
    assert rep['status'] == 'ok'
    ts_list = [int(l.split(',')[0])
               for l in e.csv_path.read_text().strip().splitlines()[1:]]
    assert base + step * 50 not in ts_list
    assert len(ts_list) == 4


# ==================== 显式失败语义 ====================

def test_business_envelope_error_failed_and_no_half_store(store):
    e = engine(store, error={'code': '50011', 'msg': 'Rate limit reached'})
    rep = e.run(start=_to_ms('2024-01-01'), end=_to_ms('2024-12-31'))
    assert rep['status'] == 'failed'
    assert any('信封' in err for err in rep['errors'])
    assert not e.csv_path.exists()   # 首轮失败：不造半成品数据文件


def test_business_error_keeps_existing_store(store):
    step = hb.BAR_MS['1H']
    base = _to_ms('2024-02-10')
    e = engine(store, pages=[[row(base)]])
    rep1 = e.run(start=base, end=base)
    assert rep1['status'] == 'ok'
    old = e.csv_path.read_bytes()
    e.transport = FakeTransport(error={'code': '50013', 'msg': 'wrong'})
    rep2 = e.run(start=base, end=base)
    assert rep2['status'] == 'failed'
    assert e.csv_path.read_bytes() == old   # 失败不碰旧文件


def test_transport_error_propagates_to_failed(store):
    e = engine(store, transport_error=True)
    rep = e.run(start=_to_ms('2024-01-01'), end=_to_ms('2024-12-31'))
    assert rep['status'] == 'failed'
    assert any('TransportError' in err for err in rep['errors'])


def test_unexpected_exception_failed_not_silent(store):
    """任意异常路径统一 failed + errors（保险丝测试）"""
    e = engine(store, pages=[[row(_to_ms('2024-02-10'))]])
    e._pull_loop = None  # 直接破坏内部可调用对象 → TypeError
    rep = e.run(start=_to_ms('2024-01-01'), end=_to_ms('2024-12-31'))
    assert rep['status'] == 'failed'
    assert rep['errors'] and rep['errors'][0].startswith('TypeError')


# ==================== 断点续传 ====================

def test_resume_from_state_last_ts(store):
    step = hb.BAR_MS['1H']
    base = _to_ms('2024-02-01')
    e = engine(store, pages=[[row(base), row(base + step)]])
    rep1 = e.run(start=base, end=base + step)
    assert rep1['status'] == 'ok'
    # 第二轮：无 start → 从 last_ts+1 步长续传（本轮区间 base+2 .. base+4 = 3 格点）
    newer = [row(base + step * 2), row(base + step * 3), row(base + step * 4)]
    e.transport = FakeTransport(pages=[newer])
    rep2 = e.run(end=base + step * 4)
    assert rep2['status'] == 'ok'
    assert rep2['total_rows'] == 3
    assert e.transport.calls[0].get('after') is None  # 首页仍从最新落拉（区间过滤收口）


def test_resume_without_state_and_start_fails(store):
    e = engine(store, pages=[[]])
    rep = e.run()
    assert rep['status'] == 'failed'
    assert any('start' in err for err in rep['errors'])


def test_corrupted_state_degrades(store):
    base = _to_ms('2024-02-01')
    e = engine(store, pages=[[row(base)]])
    e.state_path.parent.mkdir(parents=True, exist_ok=True)
    e.state_path.write_text('{broken json', encoding='utf-8')
    rep = e.run(start=base, end=base)
    assert rep['status'] == 'ok'   # 状态损坏按无状态处理，不拦正常回补
    state = json.loads(e.state_path.read_text(encoding='utf-8'))  # 已覆写为合法 JSON
    assert state['last_status'] == 'ok'


def test_state_written(store):
    base = _to_ms('2024-02-01')
    e = engine(store, pages=[[row(base)]])
    e.run(start=base, end=base)
    state = json.loads(e.state_path.read_text(encoding='utf-8'))
    assert state['bar'] == '1H'
    assert state['last_ts'] == base
    assert state['last_status'] == 'ok'


# ==================== daemon ====================

def test_daemon_rounds_and_failure_counted(store):
    """常驻 daemon：轮数上限可控退出；单轮失败显式计数，不静默"""
    tr = FakeTransport(transport_error=True)   # 每轮都失败
    cache = hb.daily_daemon('BTC-USDT', bar='1H', interval_seconds=0.1,
                            transport=tr, max_rounds=2)
    assert cache['rounds'] == 2
    assert cache['failed_rounds'] == 2
    assert all(rep['status'] == 'failed' for rep in cache['reports'])


def test_daemon_default_start_used_when_no_state(store):
    """无状态时 daemon 以默认回看窗口起拉并可跑通"""
    step = hb.BAR_MS['1H']
    anchor = _to_ms('2024-06-01')
    page = [row(anchor + step * i) for i in range(3)]
    tr = FakeTransport(pages=[page])
    cache = hb.daily_daemon('BTC-USDT', bar='1H', interval_seconds=0.1,
                            transport=tr, max_rounds=1)
    rep = cache['reports'][0]
    assert isinstance(json.dumps(rep), str) and rep['status'] in ('ok', 'partial')
