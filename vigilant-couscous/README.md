# 🧬 自进化交易系统

[![CI](https://github.com/you200109/-/actions/workflows/ci.yml/badge.svg)](https://github.com/you200109/-/actions/workflows/ci.yml)
[![CodeQL](https://github.com/you200109/-/actions/workflows/codeql.yml/badge.svg)](https://github.com/you200109/-/actions/workflows/codeql.yml)
[![Cloud Evolve](https://github.com/you200109/-/actions/workflows/auto-evolve.yml/badge.svg)](https://github.com/you200109/-/actions/workflows/auto-evolve.yml)

> 多Agent协同、GitHub学习、400轮迭代、7天内化的 AGI 永续进化交易平台

## 架构概览

```
认知层 → 感知、记忆、推理、目标
进化层 → 学习、博弈、元学习、泛化
协同层 → 分布式、共识、自主研究
执行层 → 扫描、重构、自我编程
```

## 核心能力

| 层级 | 模块 | 能力 |
|------|------|------|
| 认知 | AGIBrain | LLM 多步推理，自主策略生成 |
| 认知 | SelfReflection | 交易复盘，因果推理，策略修正 |
| 认知 | MultiModalPerception | 新闻+社交+链上数据融合 |
| 认知 | MemorySystem | 情景记忆+语义记忆双层存储 |
| 认知 | GoalManager | 5级市场状态自适应目标调整 |
| 进化 | ContinuousLearner | 每笔交易实时增量学习 |
| 进化 | AdversarialTraining | 8策略ELO锦标赛博弈进化 |
| 进化 | MetaLearner | 贝叶斯超参优化+课程学习 |
| 进化 | ZeroShotAdapter | 新市场零样本泛化 |
| 进化 | EternalEvolver | 永续进化：自主目标+突变+跨域迁移 |
| 协同 | DistributedOrchestrator | 5实例分布式协同+共识决策 |
| 协同 | AutoResearcher | arXiv论文搜索+假设生成 |
| 执行 | MarketScanner | 20+币种全市场扫描 |
| 执行 | AutoRefactor | AST分析+LLM代码重构 |
| 执行 | SelfProgramming | GitHub代码搜索→改写→注入 |

## 快速启动

```bash
# 克隆仓库
git clone https://github.com/you200109/-.git
cd self-evolution-trading

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt
pip install -e ".[dev]"

# 启动 Web 控制台
python web_console.py

# 单次交易分析
python auto_trade.py --once

# 全域自动进化（每15分钟）
python auto_evolve_scheduler.py --interval 15
```

## 云端永续进化

即使本地关机，GitHub Actions 每15分钟自动执行完整 AGI 循环：

```
GitHub学习 → 多维度进化(18任务) → 自我编程注入
→ 永续进化引擎 → 对抗训练 → 自主研究 → 元学习 → 记忆巩固
```

## 技术栈

- **语言**: Python 3.12
- **AI**: CrewAI + LangChain + OpenAI/Claude
- **进化**: 遗传算法 + Stable-Baselines3 (PPO/DQN)
- **数据**: Pandas + NumPy + CCXT
- **Web**: Python HTTP Server + Chart.js
- **CI/CD**: GitHub Actions (21个工作流)
- **容器**: Docker + docker-compose

## 项目结构

```
self-evolution-trading/
├── agi/                    # AGI 认知架构（15模块）
├── agents/                 # 多Agent协同
├── evolution/              # 进化引擎
├── strategies/             # 策略库
├── data/                   # 数据管道
├── memory/                 # 记忆和知识库
├── reports/                # 日志和报告
├── tests/                  # 单元测试
├── .github/workflows/      # 21个自动化工作流
├── auto_trade.py           # 自动交易主循环
├── auto_evolve_scheduler.py # 全域进化调度器
├── web_console.py          # Web控制台
└── Dockerfile              # 容器化部署
```

## 许可证

MIT License
