"""
自进化交易系统 - 多Agent协同模块

基于 crewai + langchain 实现的多角色 Agent 协同系统：
- Researcher: 市场研究员，负责数据分析和机会发现
- Trader: 交易执行员，负责策略执行和订单管理
- RiskManager: 风控员，负责风险评估和仓位管理

注意: crewai 为可选依赖，未安装时相关 Agent 自动降级。
"""

__all__ = ["ResearcherAgent", "TraderAgent", "RiskManagerAgent"]

# 延迟导入: crewai 为可选依赖，未安装时跳过但不影响核心模块
try:
    from .researcher import ResearcherAgent
except ImportError:
    ResearcherAgent = None

try:
    from .trader import TraderAgent
except ImportError:
    TraderAgent = None

try:
    from .risk_manager import RiskManagerAgent
except ImportError:
    RiskManagerAgent = None
