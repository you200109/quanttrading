"""
自进化交易系�?- 统一配置
所�?API 凭证、数据源、策略参数集中管�?"""

import os
from pathlib import Path

# ===== 项目路径 =====
ROOT_DIR = Path(__file__).parent
MEMORY_DIR = ROOT_DIR / "memory"
NEXUS_DIR = MEMORY_DIR / "nexus"
REPORTS_DIR = ROOT_DIR / "reports"
GH_REPOS_DIR = ROOT_DIR / "gh_repos"

for d in [MEMORY_DIR, NEXUS_DIR, REPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ===== 数据源配�?=====
DATA_SOURCE = {
    "okx_url": "https://www.www.okx.com",
    "default_timeframe": "1D",
    "history_days": 365,
}

# ===== 欧易交易 API（从环境变量读取，避免明文泄露）=====
OKX_API = {
    "api_key": os.getenv("OKX_API_KEY", ""),
    "secret_key": os.getenv("OKX_SECRET_KEY", ""),
    "passphrase": os.getenv("OKX_PASSPHRASE", ""),
    "demo": os.getenv("OKX_DEMO", "true").lower() == "true",
}

# ===== GitHub API（从环境变量读取�?====
GITHUB = {
    "token": os.getenv("GITHUB_TOKEN", ""),
    "search_interval_days": 15,
}

# ===== 交易标的 =====
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

# ===== 风控参数 =====
RISK = {
    "min_confidence": 0.01,
    "max_position_pct": 0.2,
    "max_drawdown_pct": 0.15,
    "stop_loss_pct": 0.05,
    "take_profit_pct": 0.15,
    "trailing_stop": True,
    "atr_stop_multiple": 2.0,
}

# ===== 初始资金 =====
INITIAL_CAPITAL = 100000

# ===== 系统参数 =====
SYSTEM = {
    "population_size": 40,
    "max_generations": 400,
    "trade_interval_minutes": 5,
    "rl_timesteps": 100000,
}

# ===== 多时间框�?=====
TIMEFRAMES = [3, 5, 7, 10, 14, 20, 50, 200]
