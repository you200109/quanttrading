"""
自进化交易系统 - 统一配置
所有 API 凭证、数据源、策略参数集中管理
从主系统 .env 环境变量读取，避免硬编码
"""

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

# ===== 数据源配置（从 .env 读取）=====
DATA_SOURCE = {
    "okx_url": os.getenv("OKX_BASE_URL", "https://www.okx.com"),
    "default_timeframe": os.getenv("DEFAULT_TIMEFRAME", "1D"),
    "history_days": int(os.getenv("HISTORY_DAYS", "365")),
}

# ===== 欧易交易 API（从环境变量读取，避免明文泄露）=====
OKX_API = {
    "api_key": os.getenv("OKX_API_KEY", ""),
    "secret_key": os.getenv("OKX_SECRET_KEY", ""),
    "passphrase": os.getenv("OKX_PASSPHRASE", ""),
    "demo": os.getenv("OKX_DEMO", "true").lower() == "true",
}

# ===== GitHub API（从环境变量读取）=====
GITHUB = {
    "token": os.getenv("GITHUB_TOKEN", ""),
    "search_interval_days": int(os.getenv("GITHUB_SEARCH_INTERVAL_DAYS", "15")),
}

# ===== 交易标的（从 .env 读取）=====
_symbols_str = os.getenv("TRADING_SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT")
SYMBOLS = [s.strip() for s in _symbols_str.split(",")]

# ===== 风控参数（从 .env 读取）=====
RISK = {
    "min_confidence": float(os.getenv("RISK_MIN_CONFIDENCE", "0.01")),
    "max_position_pct": float(os.getenv("RISK_MAX_POSITION_PCT", "0.2")),
    "max_drawdown_pct": float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "0.15")),
    "stop_loss_pct": float(os.getenv("RISK_STOP_LOSS_PCT", "0.05")),
    "take_profit_pct": float(os.getenv("RISK_TAKE_PROFIT_PCT", "0.15")),
    "trailing_stop": os.getenv("RISK_TRAILING_STOP", "true").lower() == "true",
    "atr_stop_multiple": float(os.getenv("RISK_ATR_STOP_MULTIPLE", "2.0")),
}

# ===== 初始资金（从 .env 读取）=====
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "100000"))

# ===== 系统参数（从 .env 读取）=====
SYSTEM = {
    "population_size": int(os.getenv("POPULATION_SIZE", "40")),
    "max_generations": int(os.getenv("MAX_GENERATIONS", "400")),
    "trade_interval_minutes": int(os.getenv("TRADE_INTERVAL_MINUTES", "5")),
    "rl_timesteps": int(os.getenv("RL_TIMESTEPS", "100000")),
}

# ===== 多时间框架（从 .env 读取）=====
_tf_str = os.getenv("TIMEFRAMES", "3,5,7,10,14,20,50,200")
TIMEFRAMES = [int(x) for x in _tf_str.split(",")]
