"""vigilant-couscous/data 路径安全修复的功能测试（真实代码路径）"""
import os
import sys
import tempfile

VC = "C:/Users/Administrator/WorkBuddy/ww/quanttrading/vigilant-couscous"
sys.path.insert(0, VC)

from data.cache_manager import MarketDataCache  # noqa: E402
from data.fetcher import DataFetcher  # noqa: E402

fails = 0


def check(desc, fn, expect):
    """expect: 'ok' 正常返回 / 'raise' 抛异常 / 'none' 返回 None"""
    global fails
    try:
        r = fn()
        got = "ok" if expect == "ok" else ("none" if r is None and expect == "none" else "ok")
    except Exception as e:
        got = "raise"
        r = e
    good = got == expect
    if not good:
        fails += 1
    print(f"{'PASS' if good else 'FAIL'}  {desc:42s} -> {got} (expect {expect})" + (f"  {r!r}" if got == 'raise' else ""))


with tempfile.TemporaryDirectory() as td:
    # ---------- cache_manager._symbol_dir ----------
    cache = MarketDataCache(cache_root=td)
    check("_symbol_dir('BTC/USDT') 正常", lambda: cache._symbol_dir("BTC/USDT"), "ok")
    check("_symbol_dir('BTC-USDT') 正常", lambda: cache._symbol_dir("BTC-USDT"), "ok")
    check("_symbol_dir('000001') 正常", lambda: cache._symbol_dir("000001"), "ok")
    check("_symbol_dir('..') 中和为下划线目录", lambda: cache._symbol_dir(".."), "ok")
    check("_symbol_dir('') 拒绝", lambda: cache._symbol_dir(""), "raise")
    check("_symbol_dir('../../etc') 拒绝或收敛", lambda: cache._symbol_dir("../../etc"), "ok")
    check("_symbol_dir('a\\x00b') 收敛为下划线", lambda: cache._symbol_dir("a\x00b"), "ok")

    # 验证收敛后的目录确实在 cache_root 内
    for sym in ("../../etc", "..", "a\x00b"):
        d = cache._symbol_dir(sym)
        inside = os.path.realpath(d).startswith(os.path.realpath(td) + os.sep)
        print(f"{'PASS' if inside else 'FAIL'}  {sym!r} 收敛目录仍在 cache_root 内 -> {d}")
        if not inside:
            fails += 1

    # ---------- fetcher._safe_cache_file ----------
    fetcher = DataFetcher(cache_dir=os.path.join(td, "gh_cache"))
    check("_safe_cache_file 正常", lambda: fetcher._safe_cache_file("BTC/USDT", "2024-01-01", "2024-02-01"), "ok")
    check("_safe_cache_file 日期含遍历拒绝", lambda: fetcher._safe_cache_file("BTC", "../../etc", "2024-01-01"), "raise")
    check("_safe_cache_file 日期格式错误拒绝", lambda: fetcher._safe_cache_file("BTC", "2024-1-1", "2024-01-01"), "raise")
    check("_safe_cache_file 符号遍历收敛", lambda: fetcher._safe_cache_file("..", "2024-01-01", "2024-02-01"), "ok")

    p = fetcher._safe_cache_file("..", "2024-01-01", "2024-02-01")
    base = os.path.realpath(os.path.join(td, "gh_cache"))
    inside = os.path.realpath(p).startswith(base + os.sep)
    print(f"{'PASS' if inside else 'FAIL'}  '..' 符号缓存文件仍在 cache_dir 内 -> {p}")
    if not inside:
        fails += 1

print(f"\n{'ALL PASS' if fails == 0 else str(fails) + ' FAILURES'}")
sys.exit(1 if fails else 0)
