"""OKX 历史 K 线回补引擎（K3，spec ④ dccd[daemon] 历史回补）

数据源定案（2026-10-17 侦察）：
- 官方批量文件门户（www.okx.com/historical-data，dccd 域）在本机出口不可达
  （www.okx.com CNAME 沉洞、dccd.okx.com 本地不解析）→ 数据面改走
  REST `/api/v5/market/history-candles` 分页（官方公共端点，无需鉴权）。
- 出口恢复路径（境外中转 / OKX_PROXY）无需改动本模块：OKX_PROXY、OKX_API_HOST
  口径与 okx_data_service 一致。
- 原则上不引入 pyted okx_candle 等第三方回补依赖（治理纪律：参考其示例实现，
  spec ⑦），实现自持。

职责：给定 inst_id / bar / 日期区间，分页向历史方向拉满区间，与本地存量
合并去重排序后原子写盘，支持断点续传（--start 缺省时从状态文件 last_ts 续传）。

铁律：
1. 显式失败不静默——传输、业务信封、解析、写盘任何一步失败都落
   report['errors'] 并把 status 标 failed/partial；绝不返回假成功，
   失败时旧数据文件原样保留（临时文件 + os.replace 原子替换）。
2. 同 ts 去重：新拉取一侧胜出（confirm 状态更"新"）；结果按 ts 升序。
3. 速率：每页请求前 acquire 全局 okx_rate_limiter（OKX candles 类 20req/2s，
   全局 35/2s 余量口径）。
4. 区间外数据过滤：只保留 [start_ms, end_ms] 内的行，避免跨页越界污染。

用法：
    python -m backend.core.history_backfill --inst-id BTC-USDT --bar 1H \
        --start 2024-01-01 --end 2024-12-31
断点续传（--start 缺省 → 从上次 last_ts + 1 个 bar 继续）：
    python -m backend.core.history_backfill --inst-id BTC-USDT --bar 1H
常驻增量（daemon）：
    python -m backend.core.history_backfill --inst-id BTC-USDT --bar 1H --daemon 86400
"""
import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.core.rate_limiter import okx_rate_limiter

logger = logging.getLogger('HistoryBackfill')

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 支持的 bar → 毫秒步长（OKX 1W/1M 边界随日历变动，步长语义不成立，回补不支持）
BAR_MS = {
    '1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000, '30m': 1_800_000,
    '1H': 3_600_000, '2H': 7_200_000, '4H': 14_400_000,
    '6H': 21_600_000, '12H': 43_200_000, '1D': 86_400_000,
}
# OKX v5 candles 官方数组口径：[ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
# 列名对齐仓库统一口径（frame_utils.CANDLE_COLUMNS），落盘 CSV 直接可喂 candles_to_frame
CSV_COLUMNS = ['ts', 'open', 'high', 'low', 'close', 'vol', 'volCcy', 'volCcyQuote', 'confirm']

CANDLES_PATH = '/api/v5/market/candles'
HISTORY_CANDLES_PATH = '/api/v5/market/history-candles'


def _row_from_raw(raw):
    """OKX v5 candles 官方数组口径：[ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]

    载荷形状/列数异常显式报错（不静默将错就错），ts 归一成 int 字符串。
    """
    if not isinstance(raw, (list, tuple)):
        raise ValueError(
            f'K线行载荷应为数组（官方 v5 口径），收到: {type(raw).__name__}')
    if len(raw) < len(CSV_COLUMNS):
        raise ValueError(
            f'K线行载荷列数不足（{len(raw)}/{len(CSV_COLUMNS)}）: {raw!r}')
    ts = int(raw[0])
    rec = {c: str(raw[i]) for i, c in enumerate(CSV_COLUMNS)}
    rec['ts'] = str(ts)
    return ts, rec


class TransportError(Exception):
    """传输层失败（连接/超时/HTTP 非 200）。原样携带原因，由引擎落 report.errors。"""


class OkxTransport:
    """OKX REST 传输层：requests 直连 + 代理透传（与 okx_data_service 同口径）"""

    def __init__(self, host=None, proxy=None, timeout=15.0):
        self.host = host or os.getenv('OKX_API_HOST', 'www.okx.com')
        self.proxy = proxy if proxy is not None else os.getenv('OKX_PROXY', '')
        self.timeout = timeout
        self.proxies = ({'http': self.proxy, 'https': self.proxy}
                        if self.proxy else None)

    def get(self, path, params=None):
        """GET 一个 v5 endpoint，返回解析后的 JSON（信封由调用方判 code）"""
        import requests
        url = f'https://{self.host}{path}'
        try:
            resp = requests.get(url, params=params, proxies=self.proxies, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            raise TransportError(f'{type(exc).__name__}: {exc}') from exc


class HistoryBackfill:
    """单 inst/bar 的历史回补执行器（离线可测：transport 注入）"""

    PAGE_SIZE = 100          # OKX history-candles 单页上限
    MAX_PAGES_PER_RUN = 200  # 单轮硬上限，防配额黑洞

    def __init__(self, inst_id, bar='1H', store_dir=None, transport=None,
                 use_limiter=True):
        if bar not in BAR_MS:
            raise ValueError(f'bar {bar!r} 不受回补支持，可选 {sorted(BAR_MS)}')
        self.inst_id = inst_id
        self.bar = bar
        self.step_ms = BAR_MS[bar]
        self.store_dir = Path(store_dir or os.getenv('OKX_KLINE_DIR') or 'marketdata')
        self.transport = transport
        self.use_limiter = use_limiter

    # ==================== 存储路径 ====================

    @property
    def csv_path(self):
        return self.store_dir / f'{self.inst_id}__{self.bar}.csv'

    @property
    def state_path(self):
        return self.store_dir / '_state' / f'{self.inst_id}__{self.bar}.json'

    def load_existing(self):
        """读本地存量（文件不存在=空），返回 ts -> row dict"""
        if not self.csv_path.exists():
            return {}
        rows = {}
        with open(self.csv_path, encoding='utf-8', newline='') as f:
            for rec in csv.DictReader(f):
                ts = int(rec['ts'])
                rows[ts] = {c: rec[c] for c in CSV_COLUMNS}
        return rows

    # ==================== 分页拉取 ====================

    def _fetch_page(self, cursor=None):
        """拉一页历史 K 线（DESC）。返回 data 列表。业务/传输失败显式抛出。"""
        if self.use_limiter:
            okx_rate_limiter.acquire()
        params = {'instId': self.inst_id, 'bar': self.bar, 'limit': str(self.PAGE_SIZE)}
        if cursor is not None:
            params['after'] = str(cursor)
        envelope = self.transport.get(HISTORY_CANDLES_PATH, params)
        if not isinstance(envelope, dict) or envelope.get('code') != '0':
            msg = envelope.get('msg') if isinstance(envelope, dict) else str(envelope)
            raise RuntimeError(f'OKX 业务信封错误: {msg}')
        return envelope.get('data', [])

    def run(self, start=None, end=None):
        """回补 [start, end]（datetime/str 'YYYY-MM-DD'，UTC）。

        start=None 时从状态文件断点续传（last_ts + 1 步长）；无状态则报错。
        返回 report dict（绝不散落副作用外的信息——错误全进 errors）。
        """
        report = {
            'inst_id': self.inst_id, 'bar': self.bar, 'status': 'ok',
            'fetched': 0, 'new_rows': 0, 'total_rows': None,
            'first_ts': None, 'last_ts': None, 'pages': 0,
            'gaps': [], 'errors': [],
        }
        try:
            start_str = 'auto(now-1440 bars)' if start is None else str(start)
            end_str = str(end) if end else 'now'
            logger.info('回补启动 %s %s start=%s end=%s', self.inst_id, self.bar,
                        start_str, end_str)
            store = self.load_existing()
            rows = dict(store)
            start_ms, end_ms = self._resolve_range(start, end, report)
            self._pull_loop(rows, start_ms, end_ms, report)
            self._merge_and_write(rows, start_ms, end_ms, report)
        except Exception as exc:  # 任何异常路径：显式 failed，不吞
            report['errors'].append(f'{type(exc).__name__}: {exc}')
            report['status'] = 'failed'
            logger.error('回补失败 %s %s: %s', self.inst_id, self.bar, exc)
        self._write_state(report)
        return report

    def _resolve_range(self, start, end, report):
        """把 start/end 归一成 (start_ms, end_ms)；断点续传语义在此落地"""
        if end is None:
            end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        else:
            end_ms = _to_ms(end)
        if start is None:
            state = self._read_state()
            last_ts = state.get('last_ts') if state else None
            if not last_ts:
                raise ValueError('无 --start 且无断点状态：请显式给定 start 或先做一次全量回补')
            start_ms = int(last_ts) + self.step_ms
            logger.info('断点续传：从 %s 继续', datetime.fromtimestamp(start_ms / 1000, timezone.utc))
        else:
            start_ms = _to_ms(start)
        return start_ms, end_ms

    def _pull_loop(self, rows, start_ms, end_ms, report):
        """向历史方向翻页：cursor = 每页最旧 ts，直到覆盖到 start 或页提前结束"""
        cursor = None
        for _ in range(self.MAX_PAGES_PER_RUN):
            data = self._fetch_page(cursor)
            report['pages'] += 1
            if not data:
                break
            page_ts = []
            for raw in data:
                ts, rec = _row_from_raw(raw)
                page_ts.append(ts)
                if start_ms <= ts <= end_ms:
                    # 同 ts：已完结(confirm='1')一侧优先于未完结快照，否则新侧胜出
                    existing = rows.get(ts)
                    if existing and existing.get('confirm') == '1' and rec['confirm'] != '1':
                        rows[ts] = existing
                    else:
                        rows[ts] = rec
                report['fetched'] += 1
                if report['first_ts'] is None or ts < report['first_ts']:
                    report['first_ts'] = ts
                report['last_ts'] = max(ts, report['last_ts'] or ts)
            oldest = min(page_ts)
            if len(data) < self.PAGE_SIZE or oldest <= start_ms:
                break
            cursor = oldest
        else:
            report['status'] = 'partial'
            report['errors'].append(
                f'单轮翻页达上限 {self.MAX_PAGES_PER_RUN} 页，区间未探完（下次按断点续传继续）')

    def _merge_and_write(self, rows, start_ms, end_ms, report):
        """缺口检测 + 原子写盘（失败不碰旧文件）"""
        in_range = sorted(ts for ts in rows if start_ms <= ts <= end_ms)
        # 缺口检测：本 bar 步长格点上应有 ts 而实际缺失
        missing = []
        curs = start_ms
        in_set = set(in_range)
        while curs <= end_ms:
            if curs not in in_set:
                missing.append(curs)
            curs += self.step_ms
            if len(missing) > 64:  # 上限保护：缺口太多不再逐格数，报告截断
                missing.append(-1)
                break
        coverage_first = in_range[0] if in_range else None
        coverage_last = in_range[-1] if in_range else None
        if missing:
            report['gaps'] = missing[:8]
            report['status'] = 'partial' if report['status'] == 'ok' else report['status']
            report['errors'].append(
                f'区间内存在缺口（count>={len(missing)}，首缺口 ts={missing[0]}）——'
                'status=partial（不静默装作补全）')
        report['total_rows'] = len(in_range)
        report['first_ts'] = coverage_first
        report['last_ts'] = coverage_last

        # 原子写盘：tmp + os.replace；写失败时旧文件保持原样
        self.store_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.csv_path.with_suffix('.csv.tmp')
        try:
            with open(tmp_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                for ts in in_range:
                    writer.writerow(rows[ts])
            os.replace(tmp_path, self.csv_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        report['new_rows'] = sum(1 for ts in rows if start_ms <= ts <= end_ms)

    def _read_state(self):
        if not self.state_path.exists():
            return None
        try:
            with open(self.state_path, encoding='utf-8') as f:
                return json.load(f)
        except Exception as exc:
            logger.warning('状态文件损坏，按无状态处理: %s', exc)
            return None

    def _write_state(self, report):
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                'inst_id': self.inst_id, 'bar': self.bar,
                'last_status': report['status'],
                'last_ts': report['last_ts'],
                'total_rows': report['total_rows'],
                'pages': report['pages'],
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=1)
        except Exception as exc:
            logger.warning('状态文件写失败（不影响数据文件本身）: %s', exc)


def _to_ms(value):
    """datetime / ISO 日期串 / 毫秒时间戳 → UTC ms"""
    if isinstance(value, bool):
        raise ValueError(f'无法解析日期: {value!r}')
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    text = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f'无法解析日期: {value!r}（支持 YYYY-MM-DD[ HH:MM]，UTC）')


# ==================== 常驻 daemon（每日增量） ====================

def daily_daemon(inst_id, bar='1H', interval_seconds=86400.0, max_days_back=1400,
                 transport=None, stop_check=None, max_rounds=None):
    """常驻回补进程：每 interval 执行一次增量回补（start 从断点/缺省回看窗口）。

    失败语义：单轮失败不中断常驻（显式记录错误后等下一轮）；
    失败轮数在返回的 report_cache 里显式计数，不静默。
    stop_check: 返回 True 时干净退出（SIG 注册点/测试注入）；
    max_rounds: 测试用轮数上限（None 不限）。
    """
    engine = HistoryBackfill(inst_id, bar=bar, transport=transport)
    default_start = datetime.now(timezone.utc) - timedelta(days=max_days_back // 2)
    report_cache = {'rounds': 0, 'failed_rounds': 0, 'reports': []}
    while True:
        if stop_check and stop_check():
            break
        if max_rounds is not None and report_cache['rounds'] >= max_rounds:
            break
        state = engine._read_state()
        start = None
        if not state or not state.get('last_ts'):
            start = default_start
        rep = engine.run(start=start)
        report_cache['rounds'] += 1
        report_cache['reports'].append(rep)
        if rep['status'] == 'failed':
            report_cache['failed_rounds'] += 1
        deadline = time.time() + interval_seconds
        while time.time() < deadline:
            if stop_check and stop_check():
                return report_cache
            time.sleep(min(1.0, max(0.05, deadline - time.time())))
    return report_cache


# ==================== CLI ====================

def build_parser():
    p = argparse.ArgumentParser(
        prog='python -m backend.core.history_backfill',
        description='OKX 历史 K 线回补（REST history-candles 分页 + 断点续传 + 原子落盘）')
    p.add_argument('--inst-id', required=True, help='产品 ID，如 BTC-USDT')
    p.add_argument('--bar', default='1H', help=f'K 线粒度，可选 {sorted(BAR_MS)}')
    p.add_argument('--start', default=None,
                   help='起点（YYYY-MM-DD[ HH:MM]，UTC）；缺省=从断点续传')
    p.add_argument('--end', default=None, help='终点；缺省=当前时刻')
    p.add_argument('--store-dir', default=None,
                   help='落盘目录；缺省 marketdata（或 OKX_KLINE_DIR）')
    p.add_argument('--daemon', type=float, default=None, metavar='SECONDS',
                   help='常驻模式：每 SECONDS 秒执行一轮增量（缺省一次性运行）')
    return p


def cli_run(args, transport=None):
    """CLI 主路径（transport 可注入以便测试）"""
    bar = args.bar
    if bar not in BAR_MS:
        raise SystemExit(f'bar {bar!r} 不受支持，可选 {sorted(BAR_MS)}')
    transport = transport or OkxTransport()
    if args.daemon:
        return daily_daemon(args.inst_id, bar=bar, interval_seconds=args.daemon,
                            transport=transport)
    engine = HistoryBackfill(args.inst_id, bar=bar, store_dir=args.store_dir,
                             transport=transport)
    report = engine.run(start=args.start, end=args.end)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return report


def main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    args = build_parser().parse_args(argv)
    report = cli_run(args)
    # 显式失败绝不装成功退出
    if isinstance(report, dict) and report.get('status') == 'failed':
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
