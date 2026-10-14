"""
自进化交易系统 - 多Agent协同模块

基于 crewai + langchain 实现的多角色 Agent 协同系统：
- Researcher: 市场研究员，负责数据分析和机会发现
- Trader: 交易执行员，负责策略执行和订单管理
- RiskManager: 风控员，负责风险评估和仓位管理
"""

from .researcher import ResearcherAgent
from .risk_manager import RiskManagerAgent
from .trader import TraderAgent

__all__ = ["ResearcherAgent", "TraderAgent", "RiskManagerAgent"]
