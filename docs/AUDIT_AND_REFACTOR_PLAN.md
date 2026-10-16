# quanttrading 重构审计与实施计划

**阶段：第一阶段（扫描与审计）—— 本文件即交付物。本阶段不修改任何代码、不产生任何 commit。**
日期：2026-10-16 ｜ 审计基准：远端 `main` @ `eb555e90d1`（本地磁盘副本已陈旧，见 §2.7）

---

## 0. 结论摘要

仓库现状可以一句话概括：**一个活着的 FastAPI 量化服务（backend）+ 一个半死的 vendored AI 进化项目（vigilant-couscous）+ 两代前端 + 74 个 workflow 的治理草样**。具体数字：

| 维度 | 现状 | 问题度 |
|---|---|---|
| Python 代码 | 19,246 行 / 88 文件（backend 12 + vc 59 + scripts 18 + tests 1，前端 0） | vc 占 82%，其中约 40% 是死代码或一次性脚本 |
| 后端 API | 28 个路由（21 业务 + 10 vc + 7 system） | **4 个 vc 端点调用不存在的方法，实际不可用** |
| 回测内核 | **4 份近乎相同的 RSI+SMA 回测实现** | 合并为 1 |
| 进化引擎 | 7 个（GA 核心库 + 3 个并发包装 + RL + 永续进化 + 学习引擎） | 收敛为 1 核 + 2 可选 |
| 死代码 | backend `vc_adapter.py`(76行)、vc `core/` 整包(1030行，import 即崩)、`strategy/` 3 个一次性脚本、前端 `app.js/styles.css`(700行孤儿)、`docs/` 前端重复拷贝 | 全部可删 |
| 工作流 | 74 个（远端 73） | **约 51 个可删**（18 个 echo 纯桩 + 10 个 mon-* 空壳 + 10 个失效/重复 CI 变体 + 若干重复安全件 + 1 个必然损坏）；定时任务 ~120 次/天，超免费额度 3.5–5 倍 |
| 测试 | 1 个 pytest 文件 5 用例；4 个安全测试脚本质量好但不在 CI | 覆盖率 ~0 |
| 数据契约 | memory/nexus 13 个 JSON，**路径 bug 导致读写分裂**（strategy/memory/nexus vs memory/nexus） | 必修 |
| 治理系统 | 种子已存在（meta-evolve 闭环雏形 + auto-search/okx-scanner 双通道发现） | 缺持久化、缺真实执行、缺反馈闭环 |

**重构策略**：不推翻重写，采用"**先清障、再修约、后收敛、终进化**"的八阶段推进，每阶段一个 commit，全部过构建/lint/测试/冒烟门禁，任何阶段不改变对外业务行为（API 契约、端口、数据格式保持兼容）。

---

## 1. 审计范围与方法

- 四路并行只读扫描：backend（12 文件全读）、vigilant-couscous（59 文件全读）、frontend/scripts/tests/docs/根配置、.github/workflows（74 文件全读）
- 交叉验证：本地磁盘 vs 远端 API、导入链实测（venv 实跑）、API 契约逐方法核对（backend 调用 vs vc 实际方法名）
- 审计中发现的全部结论均附文件:行号证据

---

## 2. 第一阶段审计报告

### 2.1 入口与可运行命令

| 入口 | 位置 | 状态 |
|---|---|---|
| **主服务（唯一活入口）** | `backend/main.py:34` 模块级 `app = FastAPI(...)`；`uvicorn backend.main:app --host 0.0.0.0 --port 8000`（README:25 / Dockerfile:34 / ci-smoke.yml:21 一致） | ✅ 可用 |
| `python -m` 块 | `backend/main.py:148-152`（reload=True 开发模式；`API_HOST/API_PORT` 仅此处读取，CLI 启动时不生效） | ⚠️ 半可用 |
| vc Web 控制台 | `vigilant-couscous/web/web_console.py`（stdlib :8765，13 API） | ❌ **Dockerfile CMD `python web_console.py` 路径失效**（实际在 web/ 下）；sys.path 插入自身目录，仅 cwd 巧合时可跑 |
| vc 进化调度器 | `auto_evolve_scheduler.py --interval 15` | ⚠️ 可跑但危险：L142-178 每轮自动 `git pull/commit/push origin master`（vendored 进主仓后必须移除） |
| vc 统一 CLI | `cli/start.py`（10 子命令） | ❌ 裸模块导入 + subprocess 相对路径，运行时大部分命令不可用 |
| vc 集成 CLI | `cli/run_all.py` | ❌ 调用 LearningEngine 不存在的 API（L50/64/284），必败 |
| vc 交互 demo | `cli/main.py` | ⚠️ 包式导入在 `python cli/main.py` 时失败降级；`--live` 是占位（L402） |
| 前端 | 无构建系统，`backend/main.py:74-76` 静态挂载 `/app`，`/` 返回 index.html | ✅ 可用（Chart.js CDN） |

**环境变量硬需求**：`API_AUTH_KEY`（无它所有交易类端点 503）——但 `.env.example` 和 README **均未列出**，部署必踩坑。`OKX_DEMO=true`（Dockerfile:27/devcontainer:45）是**死变量**，全仓无代码读取（真实开关 `OKX_SIMULATED`）。

### 2.2 模块依赖关系

```
backend/main.py
├── api/routes.py ──→ core/okx_data_service（requests+websockets 裸实现）
│                    core/okx_trade_service（okx SDK，含 HMAC 私有 WS）
│                    core/backtest_engine（pandas_ta）
│                    indicators/indicator_engine（pandas_ta 反射 400+ 变体）
├── api/vc_routes.py ──(sys.path 注入)──→ vigilant-couscous/:
│       agi.agi_brain ✅ / agi.eternal_evolver ⚠️ / agi.continuous_learner ⚠️
│       evolution.backtest_validator ✅ / agents.risk_manager ✅
│       strategy.learning_engine ⚠️（且写入 strategy/memory/nexus 而非 memory/nexus）
│       + 直接文件读写 memory/nexus/*.json（三层路径防护）
└── core/{auth, rate_limiter, observability, resilience}

vigilant-couscous 内部（半死半边）：
auto_evolve_scheduler → multi_dim_evolve/self_programming/adversarial_training/
                        meta_learner/memory_system/auto_researcher
learning_loop（GA 核心库）← multi_dim_evolve / unified_evolve / cli/main
backtest_validator ← multi_dim_evolve / unified_evolve / self_programming / vc_routes
data/fetcher ← multi_dim_evolve / unified_evolve / self_programming / cli/*
web/web_console ←（独立，引用 auto_trade【构造即崩】/ unified_evolve / backtest_validator）

关键事实：
· backend 导入链实测硬依赖仅 numpy/pandas/requests（scripts/verify_import_chain.py 断言成立）
· 前端零调用 /api/vc —— vc 路由目前没有 UI 消费者
· frontend/src 全仓无 /api/vc 调用；docs/ 下是前端整套重复拷贝
```

### 2.3 核心数据模型

**后端无任何 Pydantic/dataclass/TypedDict**，全部裸 `dict` 传输，无输入校验。现存事实契约：

| 契约 | 位置 | 结构 |
|---|---|---|
| K 线行 | routes.py:183,217；vc_routes.py:113；vc_adapter.py:35（**4 份逐字重复**） | `ts,open,high,low,close,vol,volCcy,volCcyQuote,confirm` |
| 指标计算请求 | routes.py:167-174 | `inst_id, bar, indicators[], limit` |
| 回测请求 | routes.py:201-209 | `inst_id, bar, strategy, params{}, limit` |
| 回测结果 | backtest_engine.py:243-255 | `code, initial/final_capital, total_return_pct, buy_hold_return_pct, max_drawdown_pct, sharpe_ratio, total_trades, win_rate, trades[], equity_curve[]` |
| 风控审批请求 | vc_routes.py:166-172 | `signal{symbol,confidence,action}, portfolio{total_value}` |
| 指标注册条目 | indicator_engine.py:33-38 | `{name, params, callable, category}`（基础版）+ 400+ 参数变体 |
| 追踪记录 | observability.py:41-46 | `trace_id, path, start_time, timestamp, duration_ms, status_code, end_time` |
| AlertRule | observability.py:118-123 | `name, condition, message, severity, last_triggered, trigger_count` |
| vc BacktestResult | vc evolution/backtest_validator.py:20-36 | `strategy_name, total_return, annual_return, sharpe_ratio, max_drawdown, win_rate, total_trades, profit_factor, calmar_ratio, sortino_ratio, avg_holding_days, passed, score, warnings, monthly_returns` |
| vc RiskLimits | vc agents/risk_manager.py:26-33 | `max_position_pct, max_drawdown_pct, stop_loss_pct, take_profit_pct, daily_loss_limit_pct` |

**memory/nexus 数据契约（13 个 JSON，全部键级已清点）**：`gh_strategy_library.json`（79 条策略，键 `[name,source,stars,stop_loss,timeframe,rsi_period,sma_fast,sma_slow,take_profit,rsi_oversold,rsi_overbought]`）、`version.json`、`evolution_state.json`、`evolve_result.json`、`daily_evolution.json`、`btc_evolution_result.json`、`learning_history.json`、`discovery_history.json`、`backtest_results.json`、`auto_trade_state.json`、`iterate_history.json`、`rl_optimized_result.json`、`rl_models/training_history.json`。

### 2.4 重复代码（合并清单）

| # | 重复项 | 位置 | 处置 |
|---|---|---|---|
| 1 | **K线→DataFrame 转换 ×4** | routes.py:183-187 / routes.py:217-221 / vc_routes.py:113-117 / vc_adapter.py:35-39（逐字相同） | 抽 `backend/core/frame_utils.py::candles_to_frame` |
| 2 | **RSI+SMA+SL/TP 回测模拟器 ×4** | strategy/unified_evolve.py:_simulate(L56-108) / evolution/multi_dim_evolve.py:_run_sim(L300-343) / strategy/backtest_gh_strategies.py:backtest(L41-116) / evolution/backtest_validator.py:_run_backtest(L130-170) | 合并为单一回测内核（validator 为实现基准） |
| 3 | multi_dim_evolve vs unified_evolve | 重复度 ~80%（取数→GA→验证→写 nexus） | 合并为一个引擎 + 两种配置（单币/多币） |
| 4 | 双检锁单例 ×4 | okx_data_service:168 / okx_trade_service:221 / backtest_engine:258 / indicator_engine:309 | 抽 `core/singleton.py` 装饰器；顺带修"首参定死"缺陷 |
| 5 | load_dotenv ×4 | main.py:32 / auth.py:16 / okx_data_service:17 / okx_trade_service:20 | 收敛到 `core/config.py` 单点加载 |
| 6 | try→logger→通用错误 dict ×10 | vc_routes.py 全文 | 抽装饰器 `vc_endpoint` |
| 7 | OKX 项目搜索 ×2 | auto-search.yml（13 关键词，每小时建 Issue）vs okx-scanner.yml（脚本 5 关键词，只存 artifact） | 合并为 gov/discover.py（见 §5） |
| 8 | CodeQL ×2 | codeql.yml（远端唯一）vs sec-codeql.yml（**本地陈旧副本**，远端已删） | 本地删除即对齐 |
| 9 | 前端三套拷贝 | frontend/（活）+ frontend/app.js+styles.css（死）+ docs/index.html+app.js+styles.css（重复） | 删两套死拷 |
| 10 | 文档口径分裂 | README/architecture.md 说 lightweight-charts+65 工作流；wiki 说 Chart.js；实际 74→73、Chart.js | 统一（Phase 1） |

### 2.5 死代码与孤儿模块（删除清单）

**backend**：
- `core/vc_adapter.py`（76 行）——全仓零导入，纯死代码

**vigilant-couscous**（约 3,700 行可删）：
- `core/` 整包 5 文件 1,030 行——全仓零导入，且 `__init__.py:10-11` 引用不存在的 config_validator/database，`import core` 必崩
- `strategy/backtest_gh_strategies.py`、`strategy/analyze_strategies.py`、`strategy/github_scanner.py`——零导入者、导入即执行的一次性脚本
- `web/visualize.py`——导入即执行 + 相对路径 subprocess 唤起
- `agi/` 中 5 个仅被 `__init__.py` re-export、无任何调用方的模块：market_scanner / goal_manager / self_reflection / multi_modal_perception / auto_refactor（1,477 行）——注意：被动加载有成本（顶层 import numpy/openai try），建议 `__init__` 改懒加载
- `trading/auto_trade.py`（413 行）——L70/74/75 类名错误（RiskManager/StrategyResearcher/SmartTrader 不存在，实际为 RiskManagerAgent/ResearcherAgent/TraderAgent），构造即 ImportError，事实上不可达
- `cli/` 3 文件（933 行）——入口全损，能力已被 backend + gov 系统覆盖
- `web/web_console.py`（520 行）——能力与 backend 重复，Docker 路径已失效；建议删（backend 即唯一 UI 服务）
- 根级垃圾文件 ` m flutter_app`（1,453 字节，空格开头文件名，内容是误重定向的 git log）
- `setup_scheduler.bat`——引用已删除的 weekly_evolve.py

**scripts/**（14 个可删/可归档）：push_advanced/push_codespaces/push_community/push_phase2/push_remaining（一次性 bootstrap，历史使命已完成）、close_issues（破坏性）、create_project、enable_security、setup_repo、test_network（探测第三方镜像域名，与 BASELINE 安全口径矛盾）、test_okxcn（同）、check_ci（被 gh CLI 替代）、`__pycache__` 14 个 .pyc

**前端/docs**：frontend/app.js + styles.css（700 行孤儿，操作不存在的 DOM）、docs/index.html + app.js + styles.css（前端整套重复）、docs/wiki 中 3 个死链接页

### 2.6 缺失模块与配置（需新建）

| 缺失项 | 影响 | 阶段 |
|---|---|---|
| `pyproject.toml` | publish.yml 必然失败；无 lint/type 配置事实标准（CI 用 `-o addopts=''` 空跑） | P1 |
| `.dockerignore` | `COPY . .` 带入 .git/__pycache__/.pytest_cache/quanttrading.log/reports | P1 |
| `.github/labeler.yml` | auto-label.yml 引用缺失（被 continue-on-error 掩盖） | P5 |
| `LICENSE` | sec-license.yml 永远告警；开源治理生态的合法性基础 | P1 |
| `API_AUTH_KEY` in .env.example/README | 部署必踩坑（503） | P1 |
| `docs/evolution-log.md` | meta-evolve 首次运行才创建 | P7 |
| `backend/mcp/` | 两份文档（copilot-instructions.md、wiki/Architecture.md）声称存在，实际不存在——要么删文档要么建模块 | P1 决策点 |
| `SECURITY-NOTES` | requirements.txt 注释引用，全仓不存在（悬空引用） | P1 |
| Pydantic 请求/响应模型 | 全部裸 dict，无校验 | P2 |
| `tests/` 真实用例 | 5 用例覆盖 ~0%；4 个安全测试脚本（21/7/15 用例）质量好但硬编码 Windows 路径且不在 CI | P4 |
| `gov/` 治理包 | 治理系统本体不存在（§5 设计） | P6-P7 |
| `reports/` 持久化 | mon-*/q-* 10+10 个工作流输出全部 echo 后即失 | P5-P6 |

### 2.7 ⚠️ 本地/远端一致性警告（实施前必读）

- **本地磁盘副本已陈旧**：本地 74 个 workflow（含远端已删除的 `sec-codeql.yml`），远端 main 73 个为权威。本地 git 为 `master` 空 init、零提交、零 ref——**git 历史分析在本地不可用，一切以远端 API 为准**。
- **实施第一步必须是重新对齐工作副本**（`git clone` 远端或 fetch 后 reset），否则 Phase 1 的推送会把已删除的 sec-codeql.yml 等旧文件复活。
- `.git/config` remote URL 内嵌明文 PAT（`ghp_…`）——见 §8 安全事项。

---

## 3. 保留 / 合并 / 废弃总表

### 3.1 代码模块

| 模块 | 判定 | 理由 |
|---|---|---|
| backend/main.py + api/routes.py + core/{okx_data,okx_trade,backtest_engine,auth,rate_limiter,observability,resilience} + indicators/ | **保留**（resilience 的熔断/幂等从未使用——P2 接线或删） | 服务本体，行为契约 |
| backend/api/vc_routes.py | **保留+修约** | 4 个端点方法名不匹配（evolve/get_report/daily_search_and_learn/get_seed_params），修约后可用 |
| backend/core/vc_adapter.py | **删** | 零导入死代码 |
| vc: agi/agi_brain, continuous_learner; agents/risk_manager; evolution/backtest_validator, learning_loop; strategy/learning_engine; data/fetcher, cache_manager; strategies/base_strategy; config.py | **保留** | backend 导入链 + 引擎本体 |
| vc: agi/{eternal_evolver, adversarial_training, auto_researcher, meta_learner, memory_system, distributed_orchestrator, zero_shot_adapter, market_scanner, goal_manager, self_reflection, multi_modal_perception, auto_refactor} | **合并/降级** | eternal_evolver 用 `random.uniform` 冒充进化指标（L273-287）→ 删端点或重写；5 个无调用方模块 → `__init__` 懒加载；其余仅 scheduler 引用，随 P3 收敛 |
| vc: evolution/{multi_dim_evolve, self_programming} + strategy/unified_evolve | **合并** | 与 learning_loop/backtest_validator 重复 80%，收敛为 1 引擎 + 配置 |
| vc: evolution/rl_* | **保留为可选** | gymnasium/SB3 未装时优雅降级，已工作 |
| vc: core/ 整包、cli/、web/、trading/、strategy/ 一次性脚本、web/visualize.py | **删** | 死代码/能力重复/入口全损 |
| vc: agents/{researcher,trader,alert_manager,multi_timeframe,parallel_scheduler} | **保留（测试覆盖着）** | researcher 顶层 crewai import 靠 __init__ try 兜底 → 改函数内导入 |
| frontend/index.html | **保留** | 唯一在役 UI |
| frontend/app.js + styles.css、docs/{index.html,app.js,styles.css} | **删** | 孤儿/重复 |
| scripts/ 4 个安全测试 + post_merge_check.py + okx_scanner.py | **保留并迁入** | 迁 tests/ + scripts/gov/，参数化路径，接 CI |
| scripts/ 其余 14 个 | **删/归档** | 一次性 bootstrap 已完成历史使命 |

### 3.2 工作流（远端 73 个 → 目标 ~20 个）

| 判定 | 数量 | 文件 |
|---|---|---|
| **保留（核心）** | 8 | ci.yml、ci-smoke.yml、codeql.yml、docker.yml、meta-evolve.yml（升级）、audit.yml、sec-gatekeeper.yml、sec-secret-scan.yml |
| **保留（有用，改造后）** | 12 | ci-cd.yml（去每次 push 自动建 Release）、sec-dep-review.yml、sec-permissions.yml、auto-label.yml（补 labeler.yml）、auto-stale.yml、rel-tag.yml、rel-publish.yml、deploy-staging.yml、deploy-pages.yml（改名为 backtest-report）、auto-search.yml（降频每日，并入 gov/discover）、mon-*/q-*（合并为 1 个 gov-metrics.yml）、dependabot.yml |
| **删（echo 纯桩 18）** | 18 | deploy-canary/preview/rollback；rel-archive/docker/notify/pages/pypi/rollback/snapshot/validate；auto-assign/benchmark/changelog/dependabot/docs-sync/pr-lint/release-draft |
| **删（mon-*/q-* 空壳 18）** | 18 | 全部 echo 后即失，改造合并进 gov-metrics.yml |
| **删（失效/重复 CI 变体 9）** | 9 | ci-build/ci-test/ci-lint/ci-format/ci-typecheck/ci-matrix/ci-integration/ci-nightly/ci-docker |
| **删（重复安全 4）** | 4 | sec-audit.yml（audit.yml 已覆盖）、sec-trivy.yml（exit-code 0 永不失败，ci.yml 的 Trivy 已上传 SARIF）、sec-scorecard.yml（结果不上传）、sec-license.yml（补 LICENSE 后删）、sec-zipslip.yml |
| **删/重建（损坏 1）** | 1 | publish.yml（无 pyproject 必败 + twine 用 GITHUB_TOKEN 当 PyPI 密码必 403） |
| **本地删（对齐远端 1）** | 1 | sec-codeql.yml（远端已删，本地陈旧副本） |

> 定时任务从 ~120 次/天降到 ~10 次/天，Actions 用量回落至免费额度内。

---

## 4. 目标架构一：量化工作台（重构目标态）

```
┌──────────────────────────────────────────────────────────────┐
│ 表现层  frontend/index.html（Chart.js SPA，唯一来源）           │  ← 删 app.js/docs 拷贝
├──────────────────────────────────────────────────────────────┤
│ API 层   backend/api/                                         │
│   routes.py    行情/指标/回测/订单/历史（21 端点，Pydantic 化）  │
│   vc_routes.py AI/风控/记忆（10 端点，修约 4 个）                │
├──────────────────────────────────────────────────────────────┤
│ 服务层   backend/core/                                        │
│   okx_data_service（限速+重连）  okx_trade_service（限速+重连）  │
│   backtest_engine ──────────────┐                            │
│   indicator_engine（508 指标）   │ 共用单一回测内核             │
│   auth / rate_limiter / observability / resilience（接线熔断幂等）│
├──────────────────────────────────────────────────────────────┤
│ 引擎层   vigilant-couscous/（清理后 ~35 文件）                   │
│   evolution/（GA 核心库 + 回测验证内核 + 可选 RL）               │
│   agi/（决策大脑 + 持续学习，__init__ 懒加载）                   │
│   agents/（风控/研究/交易/告警）  strategy/（学习引擎）           │
│   data/（多源获取 + 缓存，安全路径）  memory/（nexus 知识库）      │
├──────────────────────────────────────────────────────────────┤
│ 数据层   memory/nexus/*.json（契约冻结+版本化）  reports/        │
└──────────────────────────────────────────────────────────────┘
        ↕ 被 §5 治理系统持续发现/监控/学习/整合/演进
```

**重构不变量（硬约束）**：
1. 对外 API 路径、方法、响应码、JSON 键名不变（修约的 4 个端点从"恒定失败"变为"真实返回"，属于缺陷修复而非行为变更）
2. 端口 8000、静态挂载 `/app`、WS `/ws/market`+`/ws/trade` 不变
3. memory/nexus 的 13 个 JSON 键结构不变（修路径 bug 是让读写指向同一文件，恢复设计意图）
4. 环境变量名只增不减（`API_AUTH_KEY` 补进 .env.example；`OKX_DEMO` 死变量可删）

---

## 5. 目标架构二：自我演进的开源治理系统

> 基于仓库 + GitHub 全量 API（REST / GraphQL / Actions / Webhooks / Apps，以下统称"GitHub API 面"）建设的自动化治理系统。定位：**量化工作台的"生态系统引擎"**——持续发现金融/AI Agent/量化领域热门项目，筛选、监控、学习、整合，并用治理结果反哺工作台自身演进。

### 5.1 总体架构（七层闭环）

```
        ┌─────────────────────────────────────────────────────┐
        │                 知识库 memory/knowledge/              │
        │  projects(项目卡) metrics(度量) decisions(决策)        │
        │  playbooks(打法) integrations(整合记录)                │
        └──────┬──────────────────────────────────┬───────────┘
               │ 读写                              │ 反馈
   ┌───────────▼──────────┐              ┌────────▼─────────┐
   │ ①发现 Discovery       │              │ ⑦演进 Evolution  │
   │  GitHub Search API    │              │  meta-evolve v2  │
   │  3 域 13+ 关键词      │              │  学习→反省→决策  │
   │  topics/stars/活跃度  │              │  →行动→验证      │
   └───────────┬──────────┘              └────────▲─────────┘
               │ candidates.json                  │ proposals
   ┌───────────▼──────────┐              ┌────────┴─────────┐
   │ ②筛选 Scoring         │              │ ⑥整合 Integration│
   │  7 维评分→A/B/C 分层   │              │  依赖升级/适配器 │
   │  黑白名单 gov/config  │              │  /特性移植→PR    │
   └───────────┬──────────┘              └────────▲─────────┘
               │ shortlist.json                    │ approved
   ┌───────────▼──────────┐              ┌────────┴─────────┐
   │ ③监控 Monitoring      │              │ ⑤学习 Analysis   │
   │  依赖版本/发布/仓库    │              │  浅克隆+依赖清单  │
   │  健康/配额→异常建Issue│              │  +API面+质量扫描  │
   └───────────┬──────────┘              └────────▲─────────┘
               │ metrics/*.json                    │ project cards
   ┌───────────▼──────────┐                        │
   │ ④度量 Metrics        │────────────────────────┘
   │  CI 成功率/覆盖率/性能 │
   └──────────────────────┘
```

### 5.2 核心模块（`scripts/gov/` 包 + `.github/workflows/gov-*.yml`）

| 层 | 模块 | 触发 | 输入 → 输出 | 关键实现 |
|---|---|---|---|---|
| ① 发现 | `gov/discover.py` | 每日 1 次（合并 auto-search+okx-scanner） | GitHub Search API → `reports/discovery/<date>.json`（去重、增量、3 域分类） | 关键词/topic/star 下限/活跃天数全在 `gov/config.yml`；命中知识库已有的自动跳过 |
| ② 筛选 | `gov/score.py` | 发现后同 job | candidates → `reports/shortlist.json`（A/B/C 分层） | 7 维：star 趋势、提交新鲜度、issue 响应、许可证、依赖健康度、语言适配、维护状态；黑白名单 |
| ③ 监控 | `gov/monitor.py` | 每日（合并 10 个 mon-*） | GitHub API + pip → `reports/metrics/<date>.json` |  watched 项目 release/version 跟踪；自身依赖 outdated/CVE；阈值越界 → 建 Issue（告警终于落地） |
| ④ 度量 | `gov/metrics.py` | 每次 CI 后 / 每日汇总（合并 10 个 q-*） | Actions API + pytest-cov + 基准 → `reports/quality/<date>.json` |  CI 成功率/时长、覆盖率、复杂度、TODO、重复率；趋势入知识库 |
| ⑤ 学习 | `gov/analyze.py` | shortlist A/B 级项目 | 浅克隆（depth=1）→ `memory/knowledge/projects/<name>.json` | 提取：依赖清单、公共 API 面（AST）、架构信号、质量摘要、许可证；**只读分析，不执行候选代码** |
| ⑥ 整合 | `gov/integrate.py` | 每周 / 人工 dispatch | 已批准项目卡 → 分支 + PR（脚手架 + 适配器 + 测试） | 三类整合：依赖直采（requirements+Dependabot）、适配器模块（backend/core/adapters/<name>.py）、特性移植（受控 patch）；**一切变更走 PR，CI 是验证 harness** |
| ⑦ 演进 | `gov/evolve.py` + `meta-evolve.yml` v2 | 每 6 小时 | 知识库 + metrics → `reports/evolution/<ts>.json` + PR/Issue | 学习（Actions 失败热点 + 新 Action 版本）→ 反省（上轮提案的 CI 结果）→ 决策（评分排序）→ 行动（低风险自动 PR：版本戳、度量收集器；高风险只建议）→ 验证（CI 结果回写知识库） |

**依赖迭代管理**：自身依赖由 Dependabot（pip×2 + github-actions，已配置）承担 PR；`gov/monitor.py` 每月出一份《依赖健康报告》Issue（outdated 全量 + 冲突分析 + 升级顺序建议），把 14 个 PR 洪水收敛为 1 份可执行清单。

### 5.3 关键数据流

```
GitHub API 面 ──①发现──→ candidates.json ──②筛选──→ shortlist.json
                                                      │
                                    ┌─────────────────┼──────────────────┐
                                    ▼                 ▼                  ▼
                            ③监控(持续)         ⑤学习(A/B级)        人工决策点
                            metrics/*.json      project cards           │
                                    │                 │                ▼
                                    ▼                 ▼         ⑥整合 → PR → CI 门禁
                            ④度量 quality/*.json ──→ 知识库 memory/knowledge/ ←──┐
                                                      │                          │
                                                      ▼                          │
                                            ⑦演进 proposals ──→ 行动(PR/Issue) ──┘ CI 结果回写
```

**数据契约**（全部 JSON， schema 冻结在 `gov/schemas/`）：
- `project card`：`{name, url, domain, score, tier, version_watched, deps[], api_surface[], quality{}, license, status: discovered|analyzed|approved|integrated|rejected|dropped, first_seen, last_checked, reason}`
- `metric record`：`{date, ci_success_rate, avg_duration, coverage, alerts_open, deps_outdated, quota_used}`
- `decision record`：`{ts, proposal, evidence[], action, pr_url, outcome, ci_result}`

### 5.4 自我演进机制

1. **记忆**：知识库是系统的长期记忆——每个项目的评分历史、每次整合的成败与原因、每轮 CI 的度量，全部结构化落盘（`memory/knowledge/`，随仓库版本化）。
2. **反省**：每轮演进先读上一轮的 decision records——上轮的升级 PR 挂了吗？整合的特性被回滚了吗？失败原因归类（依赖冲突/测试挂/API 漂移）。
3. **决策**：提案按"预期收益 × 成功率 × 风险"评分排序；低风险且历史成功率高的（如 Action 版本戳、度量收集器完善）自动执行，其余只建议。
4. **行动与验证**：所有代码变更以 PR 形式提交，仓库自身的 CI（构建/lint/测试/冒烟）就是验证 harness；CI 结果回写知识库，形成"行动→验证→记忆"闭环。
5. **边界**：自治仅限"读 + 提案 + 低风险 PR"；合并权始终在人（或未来的 auto-merge 规则：仅 trivial 版本戳 + 全绿 + 有回滚）。

### 5.5 与仓库的协同关系

| 治理系统 | 量化工作台 |
|---|---|
| 发现/学习的新库、新策略范式 | 经 ⑥整合 变成工作台的新能力（适配器/依赖/特性） |
| ③监控 盯住的依赖与 GitHub Actions 版本 | 保持工作台"升得动"（升级 PR + 健康报告） |
| ④度量 产出的 CI/覆盖率/性能趋势 | 就是工作台"跑得稳"的量化证据（替代现在 echo 即失的 mon-*/q-*） |
| ⑦演进 的反省对象 | 首先是工作台自身的工作流与代码（meta-evolve 现有雏形直接升级） |
| 知识库 `memory/knowledge/` | 与 nexus 策略库并列，成为 `/api/vc/memory` 的新数据源 |

一句话：**工作台是产品，治理系统是让产品持续进化的生态系统；两者共享同一套 CI 验证 harness 和同一套知识库。**

---

## 6. 分阶段实施计划（每阶段 1 commit，门禁：构建 ✅ lint ✅ 测试 ✅ 冒烟 ✅）

| 阶段 | 主题 | 关键动作 | 风险控制 |
|---|---|---|---|
| **P0** | 审计（本文档） | 无代码改动 | — |
| **P1** | 对齐与清障 | 重新 clone 远端对齐工作副本；删死代码（§2.5 全清单：vc_adapter、vc/core/、cli/、web/、trading/、strategy 一次性脚本、前端孤儿、docs 拷贝、scripts 14 个、垃圾文件）；补 `.dockerignore`、`pyproject.toml`、`LICENSE`、`.env.example` 加 `API_AUTH_KEY`、删 `OKX_DEMO` 死变量；文档口径统一（65→73 工作流、Chart.js、删 mcp 声称或建模块） | 纯删除+配置，不动 import 链上的活代码；删后跑全套门禁 |
| **P2** | backend 契约硬化 | 修 4 个 vc 端点方法名（evolve/get_report/daily_search_and_learn→learn_static 等真实 API/get_seed_params→get_seed_genes）；Pydantic 请求/响应模型；抽 `frame_utils`/`singleton`/`config` 去重；resilience 熔断+幂等接入 okx 服务（或删除未用件）；私有 WS 补重连；交易服务补限速 | 每步单测+冒烟；API 响应键名不变 |
| **P2 执行记录（2026-10-16，commit e351a36）** | a+b+c 已交付 | ①4 端点修约（P2a 9/9）；②Pydantic 模型 models.py（P2b 13/13，含指标名反射面白名单）；③frame_utils 收敛三处重复（逐字节一致性验证）。**剩余项（resilience 接线/私有 WS 重连/交易限速）移至 P8**——与性能可观测同主题，且改活服务行为需基准数据先行 | 四门禁全绿 + P2a/P2b 专项验证 |
| **P3** | 引擎收敛 | 4 份回测模拟器合并为 1 内核；multi_dim_evolve+unified_evolve 合并为 1 引擎+配置；修 `strategy/memory/nexus` 路径 bug（`.parent.parent`）；删 eternal_evolver 端点或重写为真实度量；rl_models Windows 反斜杠路径规范化；`agi/__init__` 懒加载 | 保留 backtest_validator 为实现基准，逐模块对照输出 |
| **P3a 执行记录（2026-10-16，commit e8c4824）** | nexus 路径分裂修复 | ①learning_engine + **unified_evolve**（审计漏项，同为 `.parent.parent` bug 且读写 79 个学习策略的 gh_strategy_library.json）ROOT 推导修正为 `parent.parent`；②数据迁移 2 repos + 10 discovery 合并入 `vc/memory/nexus/`，删 `strategy/memory/`（备份 `.workbuddy/tmp_nexus_backup/`）；③tests/test_nexus_paths.py 4 回归测试（契约位置断言 + 持久化落点 monkeypatch 隔离 + `strategy/memory/` 不得复活） | 四门禁全绿（compileall / flake8 0+0 / pytest 9+50 / smoke 16/16 / import chain OK），CI 4/5 success（仅 Codespaces 排队） |
| **P3b 执行记录（2026-10-16）** | 回测内核合并 + 演进引擎统一 + 假度量清零 | ①**backtest_core 内核**（calc_rsi/calc_sma/simulate/fitness_score）：validator/unified/multi 三处模拟器收敛，validator 黄金快照 18/18、unified 四值逐字节一致、multi 4 模板不变；②**evolve_engine 编排层**（fetch_history/run_ga/validate_params/register_strategy）：两调用方重接，配置口径（elite/early_stop）由调用方传入；③**修 3 个静默失效 bug**：multi_dim 的 rsi_reversal/sma_cross 指标恒零（GA 在坏适应度上进化）、run_evolution 重新初始化清空种子基因（get_seed_genes 取回策略从未生效）、调度器/weekly 的 `from learning_engine import` 失效导入（学习环节一直走 except 分支）；④**eternal_evolver 假度量清零**：4 处 random.uniform 改进度改为真实系统状态增量（策略库通过数/库规模/风控覆盖/内化数/语义记忆/归档/发现数，全部文件可查），4 个 _evolve_* 执行真实动作（参数入库/风控审计修复/记忆巩固/目标治理），_last_system_state 持久化支撑跨周期评估，突变适用度静态化；⑤**agi/__init__ PEP 562 懒加载**（7 个无调用方模块不再拖累导入，import agi 零子模块副作用）；⑥rl_trainer model_dir 锚定仓库根 | 黄金快照先行（重构前存旧输出）；意图修复项单独测试锁定新值；六门禁全绿（compileall / flake8 / vc 119 passed+4 skipped / 根级 9 passed / import chain / smoke）；新测试 91 个（baseline 18 + core 40 + engine 14 + eternal 19） |
| **P4 执行记录（2026-10-16）** | 测试体系落地（commit 3050a75，推送受代理 502 阻塞见下） | ①**P4a 失效脚本复活**：scripts/ 下 3 个安全脚本硬编码旧副本绝对路径（`ww/quanttrading/vigilant-couscous`）在当前工作副本 import 即失败——"质量好但从未真正运行过"；迁入 tests/ 参数化重写：test_nexus_file_security.py(23，直调真实 get_nexus_file，合法用例锚定 3 个契约文件存在)、test_vc_data_paths.py(13，_symbol_dir/_safe_cache_file 遍历收敛)、test_security_smoke.py(14，smoke_routes 的 TestClient 化含 503 无硬编码回退)，删旧脚本；②**P4b 端点契约**：test_api_contract.py(87)——以 app.openapi() 38 操作做路由清点，本地端点全探（公开可达/受保护 401/带 key 200 信封）、外网 IO 端点只验认证分类不打网络、Pydantic POST 验 422、dict POST（有副作用）只验 401；双护栏（分类表全覆盖 + 总数锁定）防新增路由漏测；③**P4c 覆盖率门禁**：ci.yml 两个 pytest 步骤加 `--cov-fail-under`——根级 backend 40%（当前 48.75%）、vc 25%（当前 32.11%，vc pyproject 新增 `[tool.coverage.run] omit tests/*` 使覆盖率只度量生产代码，原 42% 含水）；④顺带清 18 个 F401（backend 6 文件 + tests 3 文件），base_strategy 的 pandas_ta 为 `.ta` 访问器注册的副作用导入加 noqa 注明 | 阈值留 7-9 个百分点安全边际（CI 跨 ubuntu/windows × py3.12/3.13）；先补测试再动代码的顺序保护兑现；六门禁全绿（compileall / flake8 0+0 / vc 119 passed+4 skipped / 根级 146 passed / import chain / smoke） |
| **P5** | 工作流治理收敛 | 按 §3.2 删 ~51 个；ci-cd 去自动发布（改 rel-tag 手动体系）；publish.yml 重建或删；补 labeler.yml；mon-*/q-* 合并为 gov-metrics.yml | 删一个跑一批，观察 3 天无回归再删下一批 |
| **P5a 执行记录（2026-10-16）** | 第一批删除 33 个（73→40） | 逐文件内容验证后删除：①**echo 纯桩 18**（deploy-canary/preview/rollback、rel-archive/docker/notify/pages/pypi/rollback/snapshot/validate、auto-assign/benchmark/changelog/dependabot/docs-sync/pr-lint/release-draft——均 checkout+echo 即退出）；②**失效/重复 CI 变体 9**（ci-build=import smoke 被 ci-smoke 的真实 uvicorn 覆盖、ci-test=`pytest \|\| true` 永不失败且与 ci.yml test job 双跑、ci-lint/format/typecheck=信息性检查永不失败、ci-matrix=import fastapi 被 ci.yml 4 矩阵真测试覆盖、ci-integration=指标 import 测试被 146 用例覆盖、ci-nightly=app import+flake8 与 ci.yml 逐字重复、ci-docker=`docker build \|\| echo` 永不失败且动态生成临时 Dockerfile 有污染）；③**重复安全 5**（sec-audit=`pip-audit \|\| echo` 永不失败且 audit.yml 已覆盖、sec-trivy=与 ci.yml Trivy 重复、sec-scorecard=结果不上传、sec-license=P1 已补 LICENSE、sec-zipslip=grep 启发式永不失败且被 P4a 的 23 个真实路径遍历测试取代）；④**损坏 1**（publish.yml=twine 用 GITHUB_TOKEN 当 PyPI 密码必 403，P1 已用无 build-system 防触发，删除后 P5 计划项"重建或删"以删结案）。计划未列的 deploy-production.yml（带 DEPLOY 确认门槛的构建验证）与 okx-scanner.yml（定时跑 scripts/okx_scanner.py 真实功能）不属删除清单，第一批不动。交叉引用扫描零命中（meta-evolve 动态查 API 不硬编码工作流名）；40 个保留工作流 YAML 语法批量校验通过；README/architecture 三处口径 73→40 | 六门禁全绿（compileall / flake8 0 / vc 119+4 skipped cov 32.11% / 根级 146 passed cov 48.75% / import chain / smoke）；CI 8/8 success 且 ci.yml 矩阵 7/7 绿，per-push 触发从 17 降至 9（负载 -47%）；mon-*/q-* 20 个留 P6 建 gov-metrics.yml 时合并删除（第二批） |
| **P5b+P5c 执行记录（2026-10-16）** | 去自动发布 + 补 labeler.yml | ①**ci-cd.yml 去自动发布**：原 build job 用 softprops/action-gh-release 在每次 push（backend/frontend/config/requirements 路径）时创建 `v时间戳-sha` Release——删该步并 `contents: write` 降为 `read`（现全 workflow 无 GITHUB_TOKEN 依赖），构建产物/部署包仍以 artifact 上传、deploy.sh 与 rollback.sh 照常可用；发布权收归 rel-tag.yml（手动打 tag）→ rel-publish.yml（tag 触发构建）的手动体系。②**.github/labeler.yml 新建**（P5c）：此前该配置不存在，auto-label.yml 的 actions/labeler@v5 因 continue-on-error 静默失效，路径维度标签从未生效，实际只有 Fallback 的标题关键词打标在工作；新配置 5 类（python/vc/ci/documentation/dependencies），**只引用仓库已存在的 22 个标签**（labeler 对不存在的标签会忽略），并注明 actions/labeler 仅对 pull_request 有效、issues 走 Fallback 的分工 | 40 个工作流 YAML 语法复检通过 + labeler.yml 结构校验通过；Dependabot 与 code-scanning 双-zero 确认（任务清单里"14 个 Dependabot 告警"为历史陈旧项，当前 state=all 查询为 0，依赖图刷新后已消解） |
| **P5d 执行记录（2026-10-16）** | mon-*/q-* 20 个合并为 gov-metrics.yml（40→21） | ①**先建承接再删**：新建 `scripts/gov/metrics.py`（9 个度量：code_stats/todo_scan/header_check/docs_existence/repo_size/yaml_lint/complexity(radon)/spellcheck(codespell)/github_api）——单个度量独立 try/except 隔离失败、外部工具缺失降级为 skipped 而非 failed、结果序列化 JSON 持久化；②**gov-metrics.yml** 每日 03:00 CST + dispatch + 自路径变更触发，装 radon/codespell 后采集，以 artifact 保留 90 天（原 20 个工作流的输出散落日志、次日不可查）；有意**不收编 pytest 覆盖率**（ci.yml 的 --cov-fail-under 是更严真门禁，不重复跑）、不收编 linkchecker（外网依赖噪声高）；③查明 20 个里约半数是 echo 纯桩（mon-health 只输出三行"✅ xxx is operational"），其余装真工具但一律 `|| echo` 兜底 → 度量永不失败且无持久化；④labeler.yml 顺带修掉一条哑规则（根级 CONTRIBUTING.md 不存在，实际只在 .github/ 下）| 新测试 14 个（合成仓库验证真数据、工具缺失降级、损坏 YAML 检出、**单度量异常隔离**、--fail-on-failed 退出码）；测试反抓出脚本自身缺陷：传 `--out` 时不落盘（只在缺省分支写文件）已修 + `_dump` 抽函数去重；并抓出测试用例自身行数算错一处（实为 5 行）。交叉引用扫描零功能命中（仅注释里的历史说明）；README/architecture 口径 40→21 |
| **P5e 执行记录（2026-10-16）** | P5d 上线后 CI 转红的根因修复 | **首次出现"本地全绿、CI 全红"**：P5d 推送后 ci.yml 4 个 Unit Tests 矩阵作业全部 failure（linux/windows × 3.12/3.13），而本地六门禁全绿。拉日志定位到唯一失败用例 `test_yaml_lint_detects_broken`（expected ok, got skipped）——根因是 **PyYAML 不在 CI 环境**：requirements.txt 是应用运行时依赖且全仓库生产代码从不 import yaml，只有新采集器 `m_yaml_lint` 用到；CI 缺失 → 度量按设计降级 skipped → 断言 ok 落空。修复三处：①新增 **`requirements-gov.txt`**（PyYAML 6.0.3 / radon 6.0.1 / codespell 2.4.3），把治理工具链依赖从工作流里的临时 pip 行收敛为可复现清单，且不污染生产镜像（Docker 仍只用 requirements.txt）；②**ci.yml test job 显式安装 `requirements-gov.txt`**——关键取舍：不装也能"绿"（用例会 skip），但那等于让"缺依赖即降级"变成"缺依赖无人发现"，正是本仓库一路在清的静默失效；③用例加 `pytest.importorskip("yaml")` 说明可选依赖语义，并补 `test_yaml_lint_skipped_without_pyyaml` 反向锁定降级路径。**验证方式**：用 meta_path finder 注入真实 `ModuleNotFoundError(name='yaml')` 模拟干净环境 → 14 passed 1 skipped（无误报失败）；装了则是 15 passed（真验证）| 六门禁全绿（compileall / flake8 0 / 根级 161 passed cov 48.75% / vc 119 passed 4 skipped cov 32.13% / import chain / smoke） |
| **P6a 执行记录（2026-10-16）** | 治理核心层骨架：配置 / 契约 / 落盘 / API | ①**`gov/config.yml`**（唯一参数来源）：3 域（quant/ai_agent/eng_infra）关键词+topics、发现过滤、7 维评分权重与 A/B/C 分层、黑白名单、3 个 watched 上游仓库、自身 requirements 清单、告警阈值、知识库路径。**`gov/config.py` 拒绝静默取默认值**——缺字段/类型错必须报出字段名与期望类型（`scoring: 缺失（期望 dict）`），这条路子是 labeler.yml 给的教训；另设硬性安全闸：`analysis.never_execute` 一旦不为 true 立即校验失败（治理系统对候选代码只读，边界不能靠自觉）；CLI `python scripts/gov/config.py` 可单独校验，退出码 0/1/2 区分"OK/有问题/文件都不存在"。②**`gov/schemas.py`**（对应 §5.3 数据契约）：candidate / project_card / metric_record / decision_record 四类，自带最小模式校验（类型、enum、owner/repo 式 full_name 正则、未知字段），`new_record()` 按契约为可选字段补默认值 → 生产者不会漏写字段导致下游读 None 当 0 用；写库前一律 `validate`，脏记忆比没记忆更糟。③**`gov/store.py`**：区分两类落盘——`reports/<date>/`（运行时产物，本次补进 .gitignore）与 `vigilant-couscous/memory/knowledge/`（随仓库版本化的长期记忆：项目卡 `<owner>__<repo>.json` + `decisions.jsonl` 追加式决策轨迹），坏文件跳过但打印 warning，不牵连整目录。④**`gov/github_api.py`**：统一鉴权/重试/配额可见——无凭据抛 `NoCredentials`（调用方决定跳过还是失败，不允许假装成功）、429/5xx/网络异常才退避重试而其余 4xx 直接失败、403 且配额耗尽时把 `x-ratelimit-reset` 带进报错、每次请求回传 `x-ratelimit-remaining` 给监控层提前收手。**两个当场自抓的缺陷**：一是 `new_record` 里 `default=dict` 被当成值而非工厂，所有卡共享同一个可变对象（改一张串一片），改为 callable 即调用；二是模块最初命名 `http.py`，导致 `python scripts/gov/metrics.py` 时 stdlib `http` 被遮蔽、urllib 里 `import http.client` 直接 ModuleNotFoundError——更名 `github_api.py` 并把原因写进模块 docstring | 新测试 36 个（配置：缺文件名路径/炸类型/炸 bool/炸 schema 版本/炸 watched 结构/点号取值/CLI 三个退出码；契约：可变默认值隔离/必需字段一次性全报/未知字段/enum/正则/int 冒充实数；存储：拒绝脏数据落盘、坏卡不牵连好卡、jsonl 追加与 limit、路径分隔符防护；API：500 重试后成功、429 遵守 Retry-After、404 只打一次不浪费配额、403 报出 reset、网络异常耗尽重试、配额解析）；六门禁全绿（compileall / flake8 0 / 根级 197 passed cov 48.75% / vc 119 passed 4 skipped cov 32.11% / import chain / smoke） |
| **P6b 执行记录（2026-10-16）** | ①发现 `gov/discover.py` | Search API → `reports/<date>/discovery.json`。四条硬约束：①**配额是第一约束**——按 `max_requests_per_run` 发请求，用完即停并把 `truncated=true` 写进产物（search 配额只有 30/分钟，打穿会让后续监控也 403）；②**单查询故障隔离**——某关键词报错（二级限流/网络抖动）只进 `report.errors` 且整体降级为 `partial`，其余照常；③**过滤放客户端**——GitHub 的 `fork:false` 之类限定符语义随版本漂移，改用 item 里确定的 `fork/archived/pushed_at/stars` 本地判定，宁可多取一点回来筛；④**增量去重**——跨关键词同仓库只留 star 更高的那条，知识库里已有项目卡的直接跳过并计数。**无凭据视为失败而非静默**：`NoCredentials` 时第一条查询就停（及时止损，不再浪费配额）并把 status 标 failed。真机验证（非仅 mock）：用真实 token 以 `--max-requests 3` 试跑，plan 19/used 3、truncated=true、29 条候选（含跨关键词合并 1 条），从 ai_agent 域捞回 crewAI/TradingAgents/ruflo 等真实仓库，证明 API 形状与过滤逻辑在真实数据上成立 | 新测试 15 个（查询计划展开与禁用域跳过、fork/archived/低星三类过滤、跨关键词去重取高星、已知卡跳过与计数、黑名单、配额预算与截断标记、单查询报错隔离、无凭据即 failed 且只打一次、候选全部过 candidate 契约、产物落盘可读、CLI 三个退出码与 dry-run 不落盘）；六门禁全绿（compileall / flake8 0 / 根级 212 passed cov 48.75% / vc 119 passed 4 skipped cov 32.13% / import chain / smoke）。**踩坑**：直接 `python scripts/gov/discover.py` 会 ModuleNotFoundError（脚本 import 了 `scripts.gov` 包，根不在 path 上），统一改用 `python -m scripts.gov.<mod>` 并写进用法注释 |
| **P6c 执行记录（2026-10-16）** | ②筛选 `gov/score.py`（discovery → shortlist） | 7 维加权评分（star_trend 20 / commit_freshness 20 / issue_response 15 / dependency_health 15 / license 10 / language_fit 10 / maintenance 10，内部按权重和归一）→ A≥75 / B≥55 / C 只留档。设计取舍：①**issue_response 用"未关闭 issue 密度"代理**（REST 拿不到真实首响应时长）、**dependency_health 暂记中性 50 并在 notes 显式标注待监控层数据接入**——评分宁可承认不知道，也不编造数据；②star 趋势与上一份 shortlist 差分，无历史则中性、次日生效——短期增长只有在有记忆的坐标系里才有意义；③白名单强制 tier A 直通、黑名单双保险（discover 滤一次、score 再滤一次，含自我镜像）；④**全离线模块**（不发任何请求，只读 discovery.json），`python -m scripts.gov.score --dry-run` 冒烟 | 新测试 26 个（公式边界、权重归一、分档线、白/黑名单、趋势差分、数据不足留痕、产物落盘、三个退出码）；六门禁全绿（根级 238 passed） |
| **P6d 执行记录（2026-10-16）** | ③监控 `gov/monitor.py`（watched + 依赖 + CI → Issue 告警） | 职责：watched 上游（config 3 个 + 知识库 analyzed/approved/integrated 项目卡）release 跟踪、自身 requirements vs PyPI 分类（outdated / held〔范围约束越出上界，按策略持有不催升级〕/ unpinned / up_to_date / ahead〔锁定高于最新，疑 yanked 人工复核〕/ unknown）、自身 CI 成功率与平均时长（Actions runs 样本，阈值 `monitoring.alerts`）。四条硬约束：①**跨运行记忆放知识库**（`memory/knowledge/monitor_state.json` 随仓库版本化；reports/ 会被 gitignore 过期，担不起差分职责）——`alerted_tag`/`ci.last_rate` 只在告警**成功落地**后才前进，disabled/error 保持旧值下轮自动重试（没送达的告警不算已送达）；首次见或状态丢失只记基线不告警（宁缺毋滥，不制造无法验证的"新版本"）；版本数字回退不告警只留 note；②**去重与防洪**——按标题事件指纹去重，开放告警数达 max_open_alerts 后只向最近一条追加评论；**拿不到开放 Issue 列表则本轮零变更**（宁可晚一轮，不可重复洪泛）；label 仅是样式、逻辑不依赖（label 不存在时 GitHub 会静默丢弃，防洪不能押在上面）；③**PyPI 请求不走 github_api**（那里是 GitHub 令牌注入点，绝不把 Authorization 头带出给第三方域名），裸 urllib + `_urlopen` 可注入离线测试；④**显式留白**——覆盖率（ci.yml 门禁直接拦、无数据源）与 CVE 扫描（待 P8 的 OSV/pip-audit 通道）都输出 skipped 及原因，不假装有数；另收口审计 §8.3 遗留项：每轮扫描 `.git/config` 与 `.github/workflows/*.yml` 明文令牌前缀（ghp_/github_pat_/gho_/ghs_），命中即 error（真机扫描 22 个文件，干净）。月度 `--deps-issue` 出《依赖健康报告 Issue》（outdated 全量 + 低风险优先升级顺序，按月标题去重）。**真实冒烟（非仅 mock）抓到真 bug**：`_urlopen(req, timeout)` 位置传参把 timeout 传成了 urlopen 的 data 参数，本机 PyPI 请求全部以 `message_body should be a bytes-like object...got <class 'int'>` 失败——改关键字传参并补回归测试（附"绝不携带 Authorization 头"性质断言）。本机网络对 pypi.org 直连极慢（numpy 3.7MB JSON 8 秒仅下 300KB），冒烟用轻量配置（requirements-gov.txt 3 小包）；CI 环境无此问题 | 新测试 25 个；六门禁全绿（compileall / flake8 0 / 根级 263 passed / vc 119 passed 4 skipped / import chain / 真机 dry-run 冒烟 status=ok） |
| **P6e 执行记录（2026-10-16）** | ⑤学习 `gov/analyze.py`（shortlist A/B → 浅克隆只读分析 → 项目卡） | 职责：消费 ②筛选的 shortlist（仅 A/B 级增量），浅克隆（`depth=config.analysis.clone_depth`）→ 只读静态分析 → 项目卡 `memory/knowledge/projects/<owner>__<repo>.json`（长期记忆，随仓库版本化）+ `reports/<date>/analysis.json` 运行报告。提取：依赖清单（根级 `requirements*.txt` 复用 ③monitor 解析口径 + pyproject PEP 621，去重保序）、公共 API 面（ast 只解析不求值：顶层公共 def/class 与 `__all__` 字面量；**测试文件不算公共面**——它是自证材料不是可整合目标）、架构信号（tests/CI/docs/打包/顶层结构）、质量摘要（文件数/非空行数/AST 计数/readme 字数）、许可证文件（只记文件名，分类交 ② 的 license 维度）。四条硬约束：①**绝不执行候选代码**——`never_execute` 双重校验（config.py 一道 + run() 启动复核一道），全程仅 `read_text` 与 `ast.parse`；性质测试把"模块级 open() 写文件"的源码放进仓库树，验证整条流水线不触发副作用；②**增量 + 单轮封顶**——已有项目卡（任意状态）直接跳过（⑤是"认识新朋友"），新增 config `analysis.max_projects_per_run`（默认 3，spec 同步）+ CLI `--limit`，超出显式记 `skipped_limit` 留给下一轮；③**浅克隆克制**——`--depth=1 --single-branch --no-tags` + `credential.helper=` 置空（不弹 GCM、令牌不进克隆）+ 低速保护（<1KB/s 持续 60s 放弃）+ 临时目录整目录清理 + 300s 超时；单项失败隔离记 error，status ok/partial/failed/skipped 显式分级；④**显式留白**——poetry 布局 / setup.py / `requirements/` 子目录解析不了就写进 `quality.caveats` 点名，`version_watched` 留空（版本跟踪归 ③monitor：首轮监控建基线）。**真机冒烟（非仅 mock，真实克隆全链路）**：ranaroussi/quantstats → 26 文件/12624 行/依赖 8 条（pyproject+requirements 双源去重）/API 面 12 模块 148 函数/测试·CI·文档信号齐全/卡片过 project_card 契约落盘；二跑按"已有项目卡"增量跳过；冒烟后两处打磨落地：`structure` 剔除克隆机制产物 `.git/`、API 面剔除测试文件 | 新测试 24 个（信号提取/不执行性质/语法错误与 poetry 留白/截断与上限/增量跳过/封顶/失败隔离/dry-run 零落盘/报告与卡片落盘/CLI 三退出码）；六门禁全绿（compileall / flake8 0 / 根级 287 passed / vc 119 passed 4 skipped / import chain / 真机冒烟 status=ok） |
| **P6f 执行记录（2026-10-16）** | ⑥编排 `gov/run.py` + 知识库回写 `gov/memory_branch.py`（`gov-run.yml` 每日编排；auto-search / okx-scanner 退休） | 职责：`daily` = ①discover → ②score → ⑤analyze → ③monitor 串行（子进程 `python -m scripts.gov.*`，退出码语义沿用 0=ok/partial/skipped、1=failed、2=config 错），任一阶段非零退出即停（fail-fast）；`deps` = 月度 `monitor --deps-issue` 依赖健康报告；摘要与逐阶段证据落 `reports/<date>/run.json`（artifact 90 天）。四条硬约束：①**失败必须显式落地**——失败即停后自动建 `[gov-run] 编排失败 <date>` Issue：标题指纹去重（同日重复→追加评论）、开放 `[gov-run]` 达 `max_open_alerts` 只追加最近一条、**拿不到开放列表则零变更**（与 monitor 同一纪律）、输出尾部截断 3000 字符随 Issue 便于定位、label 仅装饰；②**知识库回写零新增密钥（方案 B）**——main 有分支保护（require PR；`enforce_admins=false` 只豁免管理员），Actions 的 `GITHUB_TOKEN` 直推被拒、造的 PR 又不触发 CI（递归抑制）→ 知识库改经**不受保护的 `gov-memory` 分支**往返：restore（`ls-remote --exit-code` 探测→`fetch --depth=1`→`ls-tree` 查目录→`rm -rf` + `checkout FETCH_HEAD` 整体替换；分支/目录缺失=首次运行不算失败）与 persist（临时 `GIT_INDEX_FILE` + `read-tree` 基树→`add -A` 仅知识库→`write-tree` 与基树相同则**不产生空提交**→`commit-tree [-p FETCH_HEAD]` 作者 github-actions[bot]→`push <sha>:refs/heads/gov-memory`）；**restore 失败时放弃 persist**（否则未恢复的工作区会把分支记忆覆盖成空——网关有专门测试）；③**星标趋势桥接**——CI 里 reports/ 不跨运行留存会让 score 的 star_trend 永远冷启动：运行前把知识库快照 `state/prev_shortlist.json` 装回 `reports/<snapdate>/shortlist.json`（同日不重装/目标已存在不覆盖/坏快照跳过不猜），score 之后写回本期快照随知识库进 gov-memory 分支；④**编排器 --dry-run 只关自身副作用**（不动分支/不建 Issue/不写 run.json），阶段照常执行——本地冒烟用临时配置把知识库移出仓库、依赖换轻量清单。**退休三件套**：auto-search.yml（13 关键词每小时建 Issue）+ okx-scanner.yml（5 关键词只存 artifact）删除，能力并入 ① + `config.yml` 检索面（quant 域补 OKX 关键词 3 个，预算 22/24、发现计划 19→22），`scripts/okx_scanner.py` 一并删除；`gov-run.yml`：cron 每日 02:30 CST + 每月 1 日 deps + `workflow_dispatch(mode)`、permissions contents:write（推 gov-memory）issues:write actions:read、concurrency 不取消、装 `requirements-gov.txt`（config.py 解析 config.yml 实为 PyYAML 硬依赖——首轮 dispatch 被漏装拦在 exit 2，补装后复跑绿）；文档口径修正（README/architecture/wiki/deployment-guide 工作流 21→20、陈旧 73/65 归位、architecture.md "okx 官方 SDK" 改为社区包（pyted/okx）） | 新测试 27 个（memory_branch 8 个直接对**临时真实 git 仓库**验收：首轮孤儿分支只含知识库/无变化不产生空提交/变更与删除传播/FF 父提交/absent 不算错/分支无知识库目录 no-kb/工作区整体替换/无目录 skipped；run.py 19 个：阶段顺序与参数透传、fail-fast、deps 模式、失败 Issue 建/同日追加/防洪上限/拿不到列表零变更、dry-run 零副作用、restore 失败阻断阶段与 persist、知识库越界拒绝运行、桥接 install/save 全分支、阶段超时 124、CLI 退出码）；六门禁全绿（compileall / flake8 0 / 根级 314 passed / vc 119 passed 4 skipped / import chain / 真机全链路冒烟 status=ok：discover 22/22 预算用满 → 141 候选；score A85/B50/C6；analyze 本机网络抖动致 2 个克隆失败被隔离为 partial、TradingAgents 建卡并被同轮 monitor 认领跟踪；monitor 依赖 up_to_date 3、CI 100%、secret 扫描 21 文件干净、首轮建基线不告警）；**CI 端到端验收（workflow_dispatch 三次）**：①daily 首跑暴露漏装 PyYAML（exit 2——本地 venv 有、CI 干净环境无，"stdlib-only" 判断当场被证伪）→ 工作流补装 requirements-gov.txt（ffa7bc8，push 8 个 workflow + Gov Run 全绿）；②daily 复跑：四阶段 exit 0、restore=absent→persist=pushed 创建 gov-memory 分支（8f515c2，孤儿提交仅含知识库 5 blob：3 项目卡 + monitor_state + prev_shortlist 快照〔种下次日趋势差分〕）、artifact 6 文件；③deps 复跑：restore=restored(5) 跨运行记忆闭环、月报 Issue #77《依赖健康报告 2026-10》（fastapi patch + numpy minor + held 1 + up-to-date 14）落地、persist 增量提交 c4182fd；auto-search/okx-scanner 退役确认（Actions workflows 列表 0 残留；16:22 自动时段不再产出，末枚 15:22Z） |
| **OKX K1 执行记录（2026-10-17）** | SDK 换血：pyted `okx==2.1.2` → `okx-exchange==0.0.169`（OKX 集成升级 spec ②；同步解锁 urllib3 2.x） | 动机：pyted okx 上游精确锁死 `urllib3==1.26.12`（CVE 无法消解）。实现：①`okx_trade_service` 改经 `OkxSync`（内嵌 ccxt 4.5.88）11 个原始端点（orders-pending/history/archive、fills/history、bills/archive、balance、positions、order、cancel-order），方法签名与 routes 契约不变；②模拟盘=ccxt sandbox（`x-simulated-trading: 1` 头）；`OKX_API_HOST` 经 `hostname` 透传（旧版交易 REST 不读该变量，本次与 WS/数据服务口径对齐）；③`enableRateLimit` 补齐交易服务限速（P2 计划项提前切口）；私有 WS 原样保留（自实现 HMAC 登录，与 SDK 无关）。**错误契约显式记档**：ccxt 对业务错误（code!='0'）在 handle_errors 抛 `BaseError`、传输错误抛 `NetworkError`——getter 捕业务错误记 warning 落默认值（[]/{}，对齐旧版判 code 落空语义），下单/撤单尽力从异常消息恢复 OKX 原始响应 dict（失败退化 `{'code':'1','msg':...}`），NetworkError 原样上抛；既知差异：pyted 内建 50×0.1s 重试（ConnectionError/繁忙码）不复存在（ccxt 无内建重试，K4 联测按需补）、ccxt 对 POST trade/order 自动注入 clOrdId+tag（brokerId 归属）、超时由"无"变默认 10s。依赖：requirements + pyproject 同步 `okx-exchange==0.0.169` + `aiohttp==3.14.5` + `cryptography==50.0.2`（`import okx` 链硬依赖，上游元数据零声明属打包缺陷，显式补齐）+ `urllib3==2.8.0`（显式升 2.x，解除 1.26.12 约束）；`okx_data_service` 本不依赖 SDK（纯 requests/websockets 直连），仅口径注释更新 | 新测试 27 个（全离线：构造映射 / 11 端点参数透传 / 错误契约三分支 / place·cancel 校验与恢复 / 真 SDK 零网络构造锁定键名映射）；六门禁全绿（compileall / flake8 0×4 / 根级 341 passed cov 54.52% / vc 119+4 skipped cov 32.08% / import chain / smoke 16/16）；真机 k1_check：模块=okx-exchange 内嵌 ccxt、hostname/sandbox/enableRateLimit/模拟盘头全对。首轮 CI 抓出 okx-exchange 漏声明的 cryptography 硬依赖（本机 venv 恰好已装 = 本地门禁盲区），干净 venv 复现（ModuleNotFoundError）→ 补声明后 27 用例全过。**本机出口事实**：www.okx.com 当前不可达（curl HTTP 000/12s、ccxt RequestTimeout）→ K4 真机私有联测前置（出口/代理需先行；ccxt 支持 proxies 配置）；旧私钥轮换未完成（§8.1），同为 K4 前置 |
| **P6** | 治理系统核心 | 建 `scripts/gov/`（discover/score/monitor/analyze）+ `gov/config.yml` + schemas + `reports/` 持久化；gov-run.yml 每日编排 | 先只读后写；候选代码不执行 |
| **P7** | 整合与演进闭环 | `gov/integrate.py`（PR 自动化）；meta-evolve v2（真实行动+CI 结果回写）；知识库接入 `/api/vc/memory` | 合并权在人；低风险自动 PR 白名单制 |
| **P8** | 性能与可观测深化 | 指标导出（Prometheus 格式）、结构化日志、追踪面板、基准回归（deploy-pages 改名 backtest-report） | 基准数据先于优化动作 |

**每阶段出口标准**：`python -m uvicorn backend.main:app` 起服 → `/health` ok → 28 路由冒烟（含 4 个修约端点验证）→ `pytest` 全绿 → flake8 干净 → CodeQL 无新告警 → Actions 用量不超预算。

---

## 7. 风险与约束

1. **本地副本陈旧**（§2.7）：P1 第一步必须重新对齐，否则复活已删文件。
2. **vc 是运行时依赖**：backend 经 sys.path 导入 vc 6 个模块——P3 删除任何 vc 文件前必须重跑导入链验证（`scripts/verify_import_chain.py`）。
3. **行为不变量的验证手段**：P2 前先固化"契约快照"（28 路由的请求/响应样本存 `tests/fixtures/`），之后每个阶段 diff 快照。
4. **eternal_evolver 的"进化"是随机数**：对外展示过 AI 进化指标——修约时需同步改前端展示（AGI 面板），避免"假指标"继续呈现。
5. **Actions 配额**：治理系统自身也是消耗源——gov-* 全部低频化（日/周），单 job 合并多步骤。
6. **候选代码安全**：⑤学习层只浅克隆+静态分析，**不在 CI 执行候选代码**；⑥整合的依赖进主 requirements 前过 pip-audit + Trivy。

---

## 8. 安全事项（⚠️ 需立即行动）

1. **OKX API 三件套泄露**：本轮对话第三条长文本中出现了明文 `API Key: d3da6164-…` / `Secret Key: 5D0A3A9D…` / `Passphrase: aA11223344.`——**请立即到 OKX 账户删除该 Key 并重建**，同时检查近 7 天账单流水（`GET /api/v5/account/bills`）有无异常。明文出现在对话中即视为泄露。
2. **GitHub PAT 泄露**：聊天明文出现过的经典 PAT（含 delete_repo）+ 本地 `.git/config` remote URL 内嵌的 PAT——请吊销并改用 credential helper；本地配置中的 PAT 用 `git remote set-url` 清除。
3. **`.git/config` 不在 secret 扫描范围**：sec-secret-scan.yml 只扫 `*.py/*.yml/*.md`——P5 补一条 `.git/config` 检查（或迁到 gitleaks 全量）。

---

## 附：本阶段产出物清单

- 本文档（唯一交付物，未提交、未改任何代码）
- 四路只读审计原始报告（backend 12 文件 / vc 59 文件 / 前端脚本测试文档 / 74 工作流，均带文件:行号证据，可按需展开）

**下一步**：确认本计划后，从 P1 开始实施——第一阶段 action 是"重新 clone 远端 + 删死代码清障"，我会在动手前再报一次删除清单确认。
