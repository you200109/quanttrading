# 治理系统架构规格（Governance Architecture）

> **定位**：量化工作台的"生态系统引擎"。基于当前仓库与 GitHub 全量 API 面（REST / GraphQL / Actions / Webhooks / Apps，含 Rate limit 治理，下称 "RAT"），持续发现、筛选并整合金融 / AI Agent / 量化交易领域的热门项目与库，覆盖 **发现筛选、版本监控升级、依赖迭代管理、代码学习分析、特性吸收整合、持续性能优化** 六项能力，形成可自我演进的量化金融开源工具生态与智能体工作流。
>
> **文档关系**：本文是 `docs/AUDIT_AND_REFACTOR_PLAN.md` §5 的**操作化规范**——把"目标架构"落成可验收的模块清单、数据契约与运行节奏；两者口径冲突时，修正文档并随同一 PR 对齐（P1"文档口径分裂"教训）。`docs/architecture.md` 描述量化工作台本体，不在本文范围。

---

## 0. 设计立场（五条硬约束）

1. **配置唯一来源** `scripts/gov/config.yml`——阈值 / 权重 / 名单不得硬编码；缺字段报错退出，不静默取默认值（labeler.yml 教训）。
2. **数据不足不许假装**——代理指标、中性分、skipped 降级一律显式标注进产物；宁可分数丑，不可数字假（P3b"假度量清零"同款立场）。
3. **配额是第一约束（RAT）**——请求预算写进产物（`truncated` / `requests_used`），用完即停；单查询故障隔离并显式报错。
4. **只读边界**——候选代码只浅克隆 + 静态分析，**绝不执行**（`analysis.never_execute` 配置硬闸）；一切整合变更走 PR，合并权在人。
5. **每阶段 1 commit**——过六门禁（compileall / flake8 / pytest 根级+vc / import chain / smoke）才推送；本系统自身服从仓库同一套 CI harness。

---

## 1. 整体架构（七层闭环）

```
        ┌────────────────────────────────────────────────┐
        │            知识库 memory/knowledge/             │
        │   projects(项目卡) · decisions(决策轨迹) · 评分史 │
        └──────┬───────────────────────────────┬─────────┘
               │ 读写                          │ 反馈（CI 结果回写）
   ┌───────────▼──────────┐          ┌─────────▼─────────┐
   │ ①发现 Discovery       │          │ ⑦演进 Evolution   │
   │  gov/discover.py     │          │  gov/evolve.py    │
   │  Search API · 3 域    │          │  meta-evolve v2   │
   └───────────┬──────────┘          └─────────▲─────────┘
               │ candidates.json               │ proposals
   ┌───────────▼──────────┐          ┌─────────┴─────────┐
   │ ②筛选 Scoring         │          │ ⑥整合 Integration │
   │  gov/score.py        │          │  gov/integrate.py │
   │  7 维评分 → A/B/C     │          │  依赖/适配器/移植   │
   └───────────┬──────────┘          └─────────▲─────────┘
               │ shortlist.json                │ 已批准事项
   ┌───────────▼──────────┐          ┌─────────┴─────────┐
   │ ③监控 Monitor        │          │ ⑤学习 Learning    │
   │  gov/monitor.py      │──────────▶ gov/analyze.py    │
   │  版本/依赖健康/Issue   │ 版本动态  │  浅克隆只读分析     │
   └───────────┬──────────┘          └─────────▲─────────┘
               │                                 │ 项目卡
               ▼                                 │
        ┌──────────────────────────┐             │
        │ ④度量 Metrics            │─────────────┘
        │  gov/metrics.py（CI/覆盖率）│  质量证据
        └──────────────────────────┘
```

图例：①→②→③/④→⑤→⑥→⑦ 顺次咬合；⑦产出回写知识库、经 CI 验证后影响下一轮 ①② 的输入与排序。

**GitHub API 面使用矩阵**（现状 / 规划）：

| API 面 | 用途 | 现状 |
| --- | --- | --- |
| REST（search / repos / releases / contents） | 发现与监控主通道 | ✅ P6a `github_api.py` |
| Actions API | CI 度量、`repository_dispatch` 触发 | ✅ 度量（P5d）；触发 🔜 P7 |
| GraphQL | 批量仓库详情（省配额） | 🔜 P7 评估 |
| Webhooks / dispatch | backtest 已有外部触发先例 | ✅ 先例；治理编排 🔜 P6f |
| Contents / Trees | 浅克隆后的只读文件获取 | ✅ `github_api.get_file`（P5 已用） |

## 2. 配额（RAT）治理

| 资源 | 限额 | 策略 |
| --- | --- | --- |
| Search API | 认证 30 次/分 | discover 预算 24 次/运行，`truncated` 显式标记 |
| REST core | PAT 5000/h；Actions 内 `GITHUB_TOKEN` 1000/h/仓库 | 429/5xx 退避重试；其余 4xx 不重试；403 记录 reset 时刻 |
| GraphQL | 5000 点/h | P7 批量查询时计入预算 |
| Actions 分钟 | 公共仓库免费 | gov-* 全部低频（日 / 周 / 6h）；单 workflow 多步骤合并，避免任务风暴 |

令牌分层：CI 内用 `GITHUB_TOKEN`（只读为主）；本地与降级用 read-only fine-grained PAT（`GH_TOKEN`）；**任何令牌不入库**；监控层检查 `.git/config` 与工作流明文引用（审计 §8.3 遗留项）。


---

## 3. 核心模块（`scripts/gov/` 包 + 编排）

| 层 | 模块 | 触发 | 输入 → 输出 | 要点 | 状态 |
| --- | --- | --- | --- | --- | --- |
| ① | `discover.py` | 每日（gov-run） | Search API → `reports/<date>/discovery.json` | 3 域关键词、min_stars 过滤、已知项目跳过、预算截断 | ✅ P6b |
| ② | `score.py` | 发现后同 job | discovery → `reports/<date>/shortlist.json` | 7 维加权、A/B/C 分层、白名单直通、黑名单剔除 | ✅ P6c |
| ③ | `monitor.py` | 每日 | watched + 项目卡 → `reports/metrics/` + Issue | 版本 / release 跟踪、依赖健康、CI 阈值、告警去重/防洪落地 | ✅ P6d |
| ④ | `metrics.py` | 每日 + CI 后 | Actions API → `reports/quality/` | 自查 CI 成功率 / 时长 / 覆盖率趋势 | ✅ P5d |
| ⑤ | `analyze.py` | A/B 级项目 | 浅克隆 → `memory/knowledge/projects/*.json` | 只读静态分析、项目卡、学习笔记 | 🔜 P6e |
| ⑥ | `integrate.py` | 每周 / 人工批准 | 项目卡 + 提案 → 分支 + PR | 依赖升级 / 适配器 / 特性移植，白名单制自动 PR | 🔜 P7 |
| ⑦ | `evolve.py` | 每 6 小时 | 决策轨迹 → 提案 + 复盘报告 | meta-evolve v2：反省 → 排序 → 行动 → 验证 | 🔜 P7 |

**基础设施**（P6a 已交付）：`config.yml`（唯一配置源）、`schemas.py`（四契约）、`config.py`（严格校验，不静默默认）、`store.py`（reports/ 与 knowledge/ 双存储）、`github_api.py`（预算化 REST 客户端）。

**编排**：`gov-metrics.yml` ✅（P5d）；`gov-run.yml` 🔜 P6f（每日 `discover → score → analyze` 串行，失败即停并显式报 Issue）；`auto-search.yml` / `okx-scanner.yml` 🗑 于 P6f 退休（能力已并入 ①，避免任务风暴）。

## 4. 数据契约与存储

**四契约**（`schemas.py`，`new_record` 造、`validate` 把关、未知字段拒绝）：

| 契约 | 一句话 | 关键字段 |
| --- | --- | --- |
| `candidate` | 发现候选 | full_name / stars / forks / open_issues / license / language / pushed_at / archived / topics |
| `project_card` | 长期项目档案 | status(discovered→analyzed→tracked→integrated/rejected) / quality / analysis / integration |
| `metric_record` | 单次度量 | kind / value / unit / source（CI 或本地） |
| `decision_record` | 决策轨迹 | topic / hypothesis / action / outcome(pending/merged/rejected/ci_failed/superseded) / evidence |

**双存储分工**：

- `reports/`：运行时产物（日期分目录），`.gitignore` 不入库，随 Actions artifact 保留 90 天——**可重放、可回溯，但不是记忆**；
- `vigilant-couscous/memory/knowledge/`：长期记忆（项目卡 `owner__repo.json`、`decisions.jsonl` 追加式），随仓库版本化——**治理系统跨运行认出同一个世界**。

## 5. 关键数据流与运行节奏

```
GitHub API 面（RAT 预算）
   └─① discover ─→ candidates.json ─② score─→ shortlist.json(A/B/C)
        └─⑤ analyze（A/B）─→ 项目卡 ─③ monitor─→ 版本/依赖健康 ─Issues─→ 人工批准
                                 └─⑥ integrate ─→ 分支+PR ─→ CI ─→ 结果回写 decisions
　                         ⑦ evolve（每 6h）读 decisions ─→ 提案排序 ─→ 下一轮行动
```

| 节奏 | 内容 |
| --- | --- |
| 每日 02:30 | `gov-run`：①→②→（A/B 增量）⑤，产物入 `reports/<date>/` |
| 每日 03:00 | `gov-metrics`：④ 自身 CI 度量 |
| 每周五 | ③ 汇总报告 Issue + ⑥ 整合提案（等人工批准） |
| 每 6 小时 | ⑦ meta-evolve v2（低配额，读多写少） |
| 事件驱动 | PR CI 结果回写 `decisions.jsonl` outcome |

---

## 6. 自我演进机制（meta-evolve v2）

五段闭环，缺一环都不构成"自我演进"：

1. **记忆**：`decisions.jsonl` + 项目卡 + 评分史跨运行积累；没有记忆的"演进"只是抖动。
2. **反省**：每轮开始先读上一轮 decisions，按失败模式归类（依赖冲突 / 测试挂 / API 漂移 / 判据过时）。
3. **决策**：候选行动以 `预期收益 × 历史成功率 × (1-风险)` 排序，取 Top-N 进提案；判据来自记忆而非直觉。
4. **行动与验证**：低风险科目（版本戳更新、度量采集器完善、文档口径修正）在白名单内可自动 PR；其余一律 Issue/提案等人工批准。CI 是验证 harness，结果回写 `outcome`。
5. **边界**：自治范围 = 只读分析 + 提案 + 低风险 PR；**合并权始终在人**。`decision_record.outcome ∈ pending / merged / rejected / ci_failed / superseded`。

## 7. 与仓库（量化工作台）的协同关系

| 治理系统产出 | 工作台收益 | 落地形态 |
| --- | --- | --- |
| 发现的热门库（shortlist A 级） | 新数据源 / 指标 / 策略 | 适配器落地 `backend/`，附来源与许可证说明 |
| ③监控的版本与依赖健康 | 依赖升得动、不腐化 | 依赖升级 PR（⑥，人工批准） |
| ④度量（CI/覆盖率/时长） | 跑得稳、坏得早发现 | 报告 Issue + P8 性能基线 |
| ⑤学习笔记与项目卡 | AI 进化侧的知识输入 | 知识库并入 `/api/vc/memory` 数据源（P7） |
| ⑦演进提案 | 系统自身的改进节奏 | 提案 Issue / 白名单 PR |

一句话：**工作台是产品，治理系统是生态引擎**——工作台的 CI、技能与知识库既是治理系统的运行底座，也是它的受益对象；两条演进线经"知识库 + PR 流"交汇，互相资粮。

## 8. 安全与合规边界

- **绝不执行候选代码**：`config.yml` 的 `analysis.never_execute` 为硬闸，任何触碰都必须显式失败。
- **只读浅克隆**：`depth=1`，文件数 / 体积上限，只读扫描（P5 已实现）。
- **名单双保险**：黑名单（含自我镜像 `you200109/quanttrading`）在 discover 与 score 各过滤一次。
- **Secret 卫生**：令牌只进环境变量 / 凭据管理器；产物脱敏；定期轮换；`.git/config` 纳入监控。
- **变更纪律**：一切整合走 PR + CI；自动 PR 仅限白名单科目；回滚优先于修复。

## 9. 实施状态与路线图

- **已成**：P0-P5（体检→CI 门禁→假度量清零→安全基线→自动化收敛）、P6a 基础设施、P6b ①发现、P6c ②筛选、P6d ③监控。
- **本年**：P6e ⑤学习 → P6f `gov-run.yml` 编排（旧 workflow 退休）→ P7 ⑥⑦整合与演进闭环 + `/api/vc/memory` 并入 → P8 可观测与性能回归。
- **出口标准**（每阶段）：六门禁全绿、Actions 用量在预算内、CodeQL 无新增告警、产物字段可被下游模块消费。

## 附录：文档关系

| 文档 | 回答什么问题 |
| --- | --- |
| `docs/AUDIT_AND_REFACTOR_PLAN.md` | 为什么要做（审计证据）、分几步做（P0-P8 战略） |
| **本文** | 做什么、长什么样（模块 / 契约 / 数据流 / 演进 / 协同的操作规范） |
| `docs/architecture.md` / `README.md` | 量化工作台本体对外说明 |
| `scripts/gov/config.yml` | 运行参数唯一来源（权重 / 分档 / 名单 / 预算） |
