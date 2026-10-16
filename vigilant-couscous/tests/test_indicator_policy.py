"""
K2 指标政策锁：标准技术指标必须出自成熟库（pandas-ta），禁止手写公式回潮

背景：OKX 集成升级 spec ①——指标强制成熟库、禁脚本生成。2026-10-17 K2 将
vigilant-couscous 的全部手写指标迁移至 pandas-ta（8 个模块，含收尾补漏的
agents/parallel_scheduler.py），本文件是防回潮锁：

1. 全库静态扫描（tests/ 除外的全部 .py）禁止出现：
   - `.ewm(`：手写 EMA/RSI/ATR 递归式；
   - `np.convolve`：手写滑动平均；
   - `100 - 100/(1+…)` 式手写 RSI 公式。
2. K2 迁移模块必须保留成熟库委托标记（pandas_ta / backtest_core）。
3. 行为对拍：calc_rsi / calc_sma / multi_timeframe 的 RSI、MACD 与
   pandas-ta 直算结果一致。

允许范围（K2 边界）：收益率/波动率/峰谷距离/量比/偏度峰度等派生统计与
形态识别保留 pandas 原生原语（rolling/std/min/max/skew/kurt 等），不在禁令内。

若未来确有 `.ewm(` 的正当场景（如对派生统计做平滑），必须先在此文件显式
加白名单并说明理由——宁可显式豁免，不可静默回归手写指标。
"""
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# K2 迁移的 8 个模块（OKX spec ① 范围）
K2_MIGRATED_MODULES = [
    "agents/multi_timeframe.py",
    "agents/researcher.py",
    "agents/parallel_scheduler.py",
    "evolution/backtest_core.py",
    "evolution/backtest_validator.py",
    "evolution/multi_dim_evolve.py",
    "evolution/rl_environment.py",
    "agi/adversarial_training.py",
]

BANNED_PATTERNS = [
    (r"\.ewm\(", "手写 EMA/RSI/ATR 递归式（应委托 pandas-ta）"),
    (r"np\.convolve", "手写滑动平均（应委托 pandas-ta）"),
    (r"100\s*-\s*\(?100\s*/", "手写 RSI 式公式（应委托 pandas-ta）"),
]


def _source_files():
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT)
        if rel.parts[0] == "tests":
            continue
        if any(part in {"__pycache__", ".venv", "venv", ".git"} for part in rel.parts):
            continue
        yield p, rel


def _oscillating_close(n: int = 120) -> np.ndarray:
    """多空交替的确定性价格序列（让 RSI 脱离 0/100 退化值）"""
    return 100.0 * np.cumprod(1 + 0.02 * np.sin(np.linspace(0, 30, n)))


def _policy_dataframe(close: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(
        {'close': close, 'high': close * 1.01,
         'low': close * 0.99, 'volume': np.full(len(close), 1000.0)},
        index=pd.date_range(end=datetime.now(), periods=len(close), freq='D'))


class TestNoHandwrittenIndicators:
    @pytest.mark.parametrize("pattern,why", BANNED_PATTERNS)
    def test_source_tree_clean(self, pattern, why):
        rx = re.compile(pattern)
        hits = []
        for p, rel in _source_files():
            for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{lineno}: {line.strip()}")
        assert not hits, f"检测到手写指标模式（{why}）：\n" + "\n".join(hits)

    def test_k2_modules_delegate_to_mature_library(self):
        for rel in K2_MIGRATED_MODULES:
            src = (ROOT / rel).read_text(encoding="utf-8")
            assert ("pandas_ta" in src) or ("backtest_core" in src), \
                f"{rel} 未见成熟库委托标记（pandas_ta / backtest_core）"


class TestDelegationBehavior:
    """行为对拍：内核/分析器输出 == pandas-ta 直算"""

    def test_calc_rsi_equals_pandas_ta(self):
        import pandas_ta as ta
        from evolution import backtest_core
        close = _oscillating_close()
        expected = ta.rsi(pd.Series(close), length=14).to_numpy()
        assert np.array_equal(backtest_core.calc_rsi(close, 14), expected, equal_nan=True)

    def test_calc_sma_equals_pandas_ta(self):
        import pandas_ta as ta
        from evolution import backtest_core
        close = _oscillating_close()
        expected = ta.sma(pd.Series(close), length=10).to_numpy()
        assert np.allclose(backtest_core.calc_sma(close, 10), expected,
                           equal_nan=True, rtol=1e-12, atol=1e-12)

    def test_multi_timeframe_rsi_equals_pandas_ta(self):
        import pandas_ta as ta
        from agents.multi_timeframe import MultiTimeframeAnalyzer
        close = _oscillating_close()
        analyzer = MultiTimeframeAnalyzer(_policy_dataframe(close), "POLICY")
        expected = float(ta.rsi(pd.Series(close), length=14).iloc[-1])
        assert analyzer._calc_rsi(close) == pytest.approx(expected, rel=1e-12)

    def test_multi_timeframe_macd_equals_pandas_ta(self):
        import pandas_ta as ta
        from agents.multi_timeframe import MultiTimeframeAnalyzer
        close = np.concatenate([np.linspace(100, 80, 40), np.linspace(80, 130, 40)])
        analyzer = MultiTimeframeAnalyzer(_policy_dataframe(close), "POLICY")
        m = ta.macd(pd.Series(close), fast=12, slow=26, signal=9)
        expected = "buy" if m.iloc[-1, 0] > m.iloc[-1, 2] else (
            "sell" if m.iloc[-1, 0] < m.iloc[-1, 2] else "hold")
        assert analyzer._calc_macd_signal(close) == expected == "buy"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
