"""
数据获取器 - 统一的多源数据接口

支持数据源：
- akshare: A股/港股/期货/基金
- tushare: A股专业数据（需 token）
- yfinance: 全球股票/ETF/指数
- ccxt: 加密货币交易所
"""

from typing import Dict, List, Optional, Union
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class DataFetcher:
    """统一数据获取器
    
    自动选择最佳数据源，提供标准化的 OHLCV 数据格式。
    """
    
    def __init__(
        self,
        tushare_token: Optional[str] = None,
        cache_dir: str = "memory/gh_cache",
        okx_url: str = "https://www.okx.com"
    ):
        self.tushare_token = tushare_token
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._ts_api = None
        self.okx_url = okx_url
        # 全时间历史行情缓存
        try:
            from data.cache_manager import MarketDataCache
        except ImportError:
            from cache_manager import MarketDataCache
        self.cache_manager = MarketDataCache(fetcher=self)
        
    @property
    def ts_api(self):
        """懒加载 tushare API"""
        if self._ts_api is None and self.tushare_token:
            try:
                import tushare as ts
                ts.set_token(self.tushare_token)
                self._ts_api = ts.pro_api()
                logger.info("Tushare API 已初始化")
            except Exception as e:
                logger.warning(f"Tushare 初始化失败: {e}")
        return self._ts_api
    
    def fetch(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source: str = "auto",
        use_cache: bool = True
    ) -> pd.DataFrame:
        """获取历史行情数据
        
        Args:
            symbol: 标的代码
                - A股: '000001' (平安银行)
                - 港股: '00700' (腾讯)
                - 美股: 'AAPL' (苹果)
                - 加密货币: 'BTC/USDT'
            start_date: 开始日期 'YYYY-MM-DD'
            end_date: 结束日期 'YYYY-MM-DD'
            source: 数据源 (auto/akshare/tushare/yfinance/ccxt)
            use_cache: 是否使用缓存
            
        Returns:
            标准 OHLCV DataFrame
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        
        # 检查缓存
        if use_cache:
            cached = self._load_cache(symbol, start_date, end_date)
            if cached is not None:
                return cached
        
        # 自动选择数据源
        if source == "auto":
            source = self._auto_detect_source(symbol)
        
        # 获取数据（加密货币走全时间缓存, 缓存优先）
        if source == "ccxt" and hasattr(self, "cache_manager"):
            df = self.cache_manager.get(symbol, start_date, end_date)
        else:
            df = self._fetch_from_source(symbol, start_date, end_date, source)
        
        # 标准化格式
        df = self._standardize(df)
        
        # 保存缓存
        if use_cache and not df.empty:
            self._save_cache(symbol, start_date, end_date, df)
        
        return df
    
    def _auto_detect_source(self, symbol: str) -> str:
        """自动检测最佳数据源"""
        if '/' in symbol:
            return "ccxt"
        elif symbol.isdigit() and len(symbol) == 6:
            return "akshare"
        elif symbol.isdigit() and len(symbol) == 5:
            return "akshare"
        elif symbol.isalpha():
            return "yfinance"
        else:
            return "akshare"
    
    def _fetch_from_source(
        self, symbol: str, start_date: str, end_date: str, source: str
    ) -> pd.DataFrame:
        """从指定数据源获取数据"""
        try:
            if source == "akshare":
                return self._fetch_akshare(symbol, start_date, end_date)
            elif source == "tushare":
                return self._fetch_tushare(symbol, start_date, end_date)
            elif source == "yfinance":
                return self._fetch_yfinance(symbol, start_date, end_date)
            elif source == "ccxt":
                return self._fetch_ccxt(symbol, start_date, end_date)
            else:
                logger.error(f"未知数据源: {source}")
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"从 {source} 获取 {symbol} 数据失败: {e}")
            # 尝试备用数据源
            return self._try_fallback(symbol, start_date, end_date, source)
    
    def _fetch_akshare(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """从 akshare 获取 A股数据"""
        try:
            import akshare as ak
            
            # A股日线数据
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust="qfq"  # 前复权
            )
            
            if df is not None and not df.empty:
                df = df.rename(columns={
                    '日期': 'date',
                    '开盘': 'open',
                    '收盘': 'close',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'volume',
                    '成交额': 'amount'
                })
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                return df
        except Exception as e:
            logger.warning(f"akshare 获取失败: {e}")
        return pd.DataFrame()
    
    def _fetch_tushare(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """从 tushare 获取数据"""
        if self.ts_api is None:
            return pd.DataFrame()
        
        try:
            # 添加交易所后缀
            if symbol.isdigit():
                if symbol.startswith('6'):
                    ts_symbol = f"{symbol}.SH"
                else:
                    ts_symbol = f"{symbol}.SZ"
            else:
                ts_symbol = symbol
            
            df = self.ts_api.daily(
                ts_code=ts_symbol,
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', '')
            )
            
            if df is not None and not df.empty:
                df = df.rename(columns={
                    'trade_date': 'date',
                    'open': 'open',
                    'close': 'close',
                    'high': 'high',
                    'low': 'low',
                    'vol': 'volume',
                    'amount': 'amount'
                })
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                df.sort_index(inplace=True)
                return df
        except Exception as e:
            logger.warning(f"tushare 获取失败: {e}")
        return pd.DataFrame()
    
    def _fetch_yfinance(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """从 yfinance 获取全球市场数据"""
        try:
            import yfinance as yf
            
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_date, end=end_date)
            
            if df is not None and not df.empty:
                df.columns = [c.lower() for c in df.columns]
                return df
        except Exception as e:
            logger.warning(f"yfinance 获取失败: {e}")
        return pd.DataFrame()
    
    def _fetch_ccxt(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """从欧易国内 API 获取加密货币数据"""
        try:
            import requests
            
            # 转换交易对格式: BTC/USDT -> BTC-USDT
            inst_id = symbol.replace('/', '-')
            
            # 目标时间范围（毫秒时间戳）
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            start_ms = int(start_dt.timestamp() * 1000)
            end_ms = int((end_dt + timedelta(days=1)).timestamp() * 1000)
            
            # 分页游标拉取历史 K 线（欧易单页上限 100 条，逐页往更早翻）
            import time as _time
            kline_url = f"{self.okx_url}/api/v5/market/history-candles"
            all_candles = {}
            cursor = end_ms
            page = 0
            max_pages = 60  # 60 页 x 100 条 ≈ 6000 条，足够覆盖多年日线
            
            while page < max_pages:
                params = {
                    'instId': inst_id,
                    'bar': '1D',
                    'limit': 100,
                    'after': cursor,  # 该数据源用 after 往更早翻页（实测有效）
                }
                resp = requests.get(kline_url, params=params, timeout=15)
                if resp.status_code != 200:
                    logger.warning(f"欧易 API 返回状态码: {resp.status_code}")
                    break
                data = resp.json()
                if data.get('code') != '0':
                    logger.warning(f"欧易 API 错误: {data.get('msg')}")
                    break
                candles = data.get('data', [])
                if not candles:
                    break
                
                page += 1
                for c in candles:
                    ts_ms = int(c[0])
                    all_candles[ts_ms] = {
                        'open': float(c[1]),
                        'high': float(c[2]),
                        'low': float(c[3]),
                        'close': float(c[4]),
                        'volume': float(c[5]),
                    }
                
                page_earliest = min(int(c[0]) for c in candles)
                if page_earliest <= start_ms:
                    break
                if page_earliest >= cursor:
                    break  # 游标未继续前移，避免死循环
                cursor = page_earliest
                _time.sleep(0.15)  # 速率保护
            
            if not all_candles:
                return pd.DataFrame()
            
            # 解析 K 线数据: [ts, open, high, low, close, vol, ...]
            rows = []
            for ts_ms, v in all_candles.items():
                rows.append({
                    'date': datetime.fromtimestamp(ts_ms / 1000),
                    **v
                })
            
            df = pd.DataFrame(rows)
            df.set_index('date', inplace=True)
            df.sort_index(inplace=True)
            df = df[(df.index >= start_date) & (df.index <= end_date)]
            
            logger.info(f"欧易 API 分页获取 {symbol} 数据成功，共 {len(df)} 条（{page} 页）")
            return df
            
        except Exception as e:
            logger.warning(f"欧易 API 获取失败: {e}")
        return pd.DataFrame()
    
    def _try_fallback(
        self, symbol: str, start_date: str, end_date: str, failed_source: str
    ) -> pd.DataFrame:
        """尝试备用数据源"""
        fallback_order = {
            "akshare": ["tushare", "yfinance"],
            "tushare": ["akshare", "yfinance"],
            "yfinance": ["akshare"],
            "ccxt": []
        }
        
        for fb_source in fallback_order.get(failed_source, []):
            logger.info(f"尝试备用数据源: {fb_source}")
            df = self._fetch_from_source(symbol, start_date, end_date, fb_source)
            if not df.empty:
                return df
        
        return pd.DataFrame()
    
    def _standardize(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化数据格式"""
        if df.empty:
            return df
        
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in required_cols:
            if col not in df.columns:
                df[col] = 0.0
        
        # 确保数值类型
        for col in required_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df.sort_index(inplace=True)
        return df[required_cols]
    
    def _cache_key(self, symbol: str, start_date: str, end_date: str) -> str:
        """生成缓存键（符号中的斜杠/横杠转义为下划线，避免被当作路径分隔符）"""
        safe_symbol = symbol.replace("/", "_").replace("-", "_")
        return f"{safe_symbol}_{start_date}_{end_date}.parquet"
    
    def _load_cache(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """加载缓存数据"""
        cache_file = self.cache_dir / self._cache_key(symbol, start_date, end_date)
        if cache_file.exists():
            try:
                df = pd.read_parquet(cache_file)
                logger.info(f"从缓存加载 {symbol} 数据")
                return df
            except Exception:
                pass
        return None
    
    def _save_cache(self, symbol: str, start_date: str, end_date: str, df: pd.DataFrame):
        """保存缓存数据（自动创建父目录）"""
        try:
            cache_file = self.cache_dir / self._cache_key(symbol, start_date, end_date)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache_file)
        except Exception as e:
            logger.warning(f"缓存保存失败: {e}")
    
    def get_realtime_quote(self, symbol: str, source: str = "auto") -> dict:
        """获取实时行情
        
        Args:
            symbol: 标的代码
            source: 数据源
            
        Returns:
            实时行情字典
        """
        try:
            if source == "auto":
                source = self._auto_detect_source(symbol)
            
            if source == "akshare":
                import akshare as ak
                df = ak.stock_zh_a_spot_em()
                row = df[df['代码'] == symbol]
                if not row.empty:
                    return {
                        'symbol': symbol,
                        'price': float(row['最新价'].iloc[0]),
                        'change_pct': float(row['涨跌幅'].iloc[0]),
                        'volume': float(row['成交量'].iloc[0]),
                        'timestamp': datetime.now().isoformat()
                    }
            elif source == "yfinance":
                import yfinance as yf
                ticker = yf.Ticker(symbol)
                info = ticker.info
                return {
                    'symbol': symbol,
                    'price': info.get('currentPrice', 0),
                    'change_pct': info.get('regularMarketChangePercent', 0),
                    'volume': info.get('volume', 0),
                    'timestamp': datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"获取实时行情失败: {e}")
        
        return {}
    
    def get_market_indices(self) -> pd.DataFrame:
        """获取主要市场指数"""
        indices = {
            '上证指数': '000001',
            '深证成指': '399001',
            '创业板指': '399006',
            '沪深300': '000300'
        }
        
        results = []
        for name, code in indices.items():
            try:
                import akshare as ak
                df = ak.stock_zh_index_daily(symbol=f"sh{code}")
                if not df.empty:
                    latest = df.iloc[-1]
                    results.append({
                        'name': name,
                        'code': code,
                        'close': float(latest['close']),
                        'change_pct': float(latest.get('pct_chg', 0))
                    })
            except Exception:
                pass
        
        return pd.DataFrame(results)
