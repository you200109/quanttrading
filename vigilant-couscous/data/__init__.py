"""
自进化交易系统 - 数据采集模块

集成多数据源：
- akshare: A股/港股/期货数据
- tushare: A股专业数据
- yfinance: 全球市场数据
- ccxt: 加密货币数据
"""

from .fetcher import DataFetcher

__all__ = ["DataFetcher"]
