"""
vigilant-couscous/data 路径安全测试（P4a 迁移产物）

迁移自 scripts/test_vc_data_paths.py——原脚本硬编码旧副本绝对路径
（ww/quanttrading/vigilant-couscous），在当前工作副本下 import 即失败；
改为 Path(__file__) 参数化并转为 pytest 断言。

覆盖 vc 数据层两个路径收敛点：
- MarketDataCache._symbol_dir：交易对符号 → 缓存目录（遍历收敛为下划线）
- DataFetcher._safe_cache_file：符号+日期 → 缓存文件（日期格式/遍历拒绝）
"""
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VC_ROOT = REPO_ROOT / 'vigilant-couscous'
sys.path.insert(0, str(VC_ROOT))

from data.cache_manager import MarketDataCache  # noqa: E402
from data.fetcher import DataFetcher  # noqa: E402


@pytest.fixture
def cache(tmp_path):
    return MarketDataCache(cache_root=str(tmp_path))


@pytest.fixture
def fetcher(tmp_path):
    return DataFetcher(cache_dir=str(tmp_path / 'gh_cache'))


class TestSymbolDir:
    @pytest.mark.parametrize('symbol', ['BTC/USDT', 'BTC-USDT', '000001'])
    def test_normal_symbols(self, cache, symbol):
        assert cache._symbol_dir(symbol)  # 正常返回目录路径

    def test_dotdot_neutralized(self, cache):
        """'..' 被中和为下划线目录而非逃逸"""
        d = cache._symbol_dir('..')
        assert '..' not in os.path.basename(d)
        assert cache._symbol_dir('../../etc')  # 收敛而非抛异常

    def test_nul_byte_neutralized(self, cache):
        d = str(cache._symbol_dir('a\x00b'))
        assert '\x00' not in d
        assert d.endswith('a_b')

    def test_empty_symbol_rejected(self, cache):
        with pytest.raises(Exception):
            cache._symbol_dir('')

    @pytest.mark.parametrize('symbol', ['../../etc', '..', 'a\x00b'])
    def test_converged_dir_stays_inside_cache_root(self, cache, tmp_path, symbol):
        d = os.path.realpath(cache._symbol_dir(symbol))
        assert d.startswith(os.path.realpath(str(tmp_path)) + os.sep)


class TestSafeCacheFile:
    def test_normal(self, fetcher):
        p = fetcher._safe_cache_file('BTC/USDT', '2024-01-01', '2024-02-01')
        assert p

    def test_date_traversal_rejected(self, fetcher):
        with pytest.raises(Exception):
            fetcher._safe_cache_file('BTC', '../../etc', '2024-01-01')

    def test_date_format_rejected(self, fetcher):
        with pytest.raises(Exception):
            fetcher._safe_cache_file('BTC', '2024-1-1', '2024-01-01')

    def test_symbol_traversal_converged(self, fetcher, tmp_path):
        p = fetcher._safe_cache_file('..', '2024-01-01', '2024-02-01')
        base = os.path.realpath(str(tmp_path / 'gh_cache'))
        assert os.path.realpath(p).startswith(base + os.sep)
