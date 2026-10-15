# 基线记录

日期：2026-10-16（P1 对齐与清障轮次后更新；P0 审计文档见 docs/AUDIT_AND_REFACTOR_PLAN.md）

## Git
- 提交数：35+
- 分支数：2 (main + you200109-patch-1 自动补丁分支)
- 标签数：1 (v1.0.0)
- 仓库大小：~2 MB
- 开放 PR：0

## 代码
- Python 文件：61（backend 11 + vigilant-couscous 42 + scripts 7 + tests 1；P1 删除死代码前为 88 / 19,246 行，删除 6,706 行）
- 依赖数量：14 (requirements.txt，已固定版本)
- vigilant-couscous 依赖：12（原为 257 个包的开发机 freeze，已按 pyproject 精简；
  实测 vc_routes 导入的全部模块在根依赖下完整工作，AGI/风控端点冒烟通过）

## 测试
- 覆盖率：低（tests/ 存在 1 个测试文件 + vc/tests 2 个文件共 55 用例，全部通过；
  端点契约测试与覆盖率下限为 P4 阶段目标）
- 冒烟验证（2026-10-15 本地，API_AUTH_KEY 认证后）：508 指标加载、12 个常用指标计算、
  ma_cross 回测（17 笔交易）、认证中间件 401 拦截（无 key）/ 放行（有 key）、
  健康检查 ok、AGI 状态接口真实出数（total_decisions/knowledge_entries）、
  风控状态接口、82 策略加载
- 本轮新增安全测试（全部通过）：
  - scripts/test_path_traversal.py：21/21（nexus 文件名攻击面：遍历/编码/绝对路径/UNC/点文件/NUL）
  - scripts/test_nexus_endpoint_e2e.py：7/7（真实路由函数端到端）
  - scripts/test_vc_data_paths.py：15/15（cache_manager/fetcher 路径构造 + 收敛 containment 断言）
  - scripts/verify_import_chain.py：服务导入链不触及 vc/data 四模块，已删模块零复活（13 项不变量）
  - scripts/smoke_routes.py：16/16（真实 uvicorn 起服；公开端点 / 认证矩阵 401+503 /
    nexus 路径遍历拒绝 / openapi 38 paths / 无 5xx）

## CI（两轮全量修复，main 全线绿）
- 工作流数量：73（删除重复的 auto-search-okx.yml 与 sec-codeql.yml，各保留一个同名工作流）
- 第一轮修复清单：
  1. CI 矩阵 3.11 → 3.12/3.13（pandas-ta 0.4.71b0 要求 ≥3.12）
  2. CI Smoke Test 依赖不全 → 全量 requirements + 30 次重试健康检查
  3. Post-Merge Check 崩溃 → post_merge_check.py 硬编码 chdir Windows 路径改为条件化，
     vc 目录缺失时容错；依赖比较改为范围满足判断（pandas==2.3.3 vs >=2.3.3,<3.0 不再误报）
  4. CI/CD Build tar 打包不存在的 config/ → 改为存在才打包（三处：archive/deploy/deploy.sh）
  5. CodeQL 失败 → 仓库默认 CodeQL 配置与高级工作流冲突，已将 default setup 关闭
  6. meta-evolve / auto-search-okx YAML 非法 → Python f-string 裸换行截断 YAML 块标量，
     全部改为 \n 转义；auto-search-okx 因与 auto-search.yml 同名同功能且壳引号有缺陷，已删除
  7. Codespaces 预构建失败 → docker-outside-of-docker 特性 moby 选项在 debian trixie
     无系统包，设 moby=false（预构建已验证成功）
  8. 7 个工作流补齐 permissions 最小权限声明
- 第二轮（安全收尾）：删除重复的 sec-codeql.yml（09:52 扫描即残留告警来源），
  codeql.yml 保留 push + 每周触发；三次推送均触发全新分析，main @ 24326f5 上
  CodeQL 零发现
- Dependabot PR：14 个全部关闭（均基于已删除的 257 包 freeze，附说明评论）

## 安全
- 密钥告警：0 (gitleaks 通过，.env 已忽略)
- Dependabot 告警：0 open（14 个全部 dismissed，均源自已删除的 vc freeze）
- 代码扫描告警：**0 open**（26 fixed + 25 dismissed，详见下）
- CodeQL py/path-injection 消毒机制（本轮读查询源码确认，PathInjectionQuery.qll +
  Concepts.qll + frameworks/Stdlib.qll）：两状态污点机——源为 NotNormalized；
  os.path.realpath/normpath/abspath 转移到 NormalizedUnchecked；**stdlib 中唯一建模的
  SafeAccessCheck 是 str.startswith**（os.path.commonpath 未被建模，写它不关闭告警）。
  因此所有路径守卫统一为：regex 白名单 → realpath 归一化 → startswith(目录 + os.sep)
  →（纵深防御）commonpath 二次校验
- 修复的文件与模式：
  1. backend/api/vc_routes.py get_nexus_file：三层校验（regex 白名单 / realpath+startswith
     守卫 / commonpath 二次校验），合法文件正常返回，遍历全部拒绝，缺失文件独立提示
  2. vigilant-couscous/data/cache_manager.py _symbol_dir：原 symbol.replace('/', '_')
     不中和 '..' 与控制字符 → 改为字符白名单 + realpath + startswith 包含检查
  3. vigilant-couscous/data/fetcher.py _cache_key/_load_cache/_save_cache：start_date/
     end_date 原本直接流入缓存路径 → 日期严格校验（YYYY-MM-DD）+ 符号白名单 +
     全部缓存路径经 _safe_cache_file（realpath + startswith）
- 25 个 dismiss 的告警均为 09:52 旧分析在 pre-fix 提交（14c569a/3d7515f/dbefb4c）上的
  残留实例；修复后提交上的实例已被 CodeQL 自动标记 fixed，main 最新分析零发现。
  每条 dismiss 均附证据评论（修复 commit + 导入链验证结论）
- 历史修复（见上一版基线）：vc_routes 路径遍历、认证硬编码密钥/计时攻击/默认公开、
  vc_routes 8 处 str(e) 泄露、main.py 追踪记录泄露、指标引擎静默吞异常与
  macd/bbands/atr 传参 bug

## 性能
- 指标引擎初始化：<0.1s（单例，508 指标）
- 回测耗时：~0.02s (300 根 K 线)
- 内存峰值：~140 MB（服务运行态实测）

## 代码质量
- flake8 (E9,F63,F7,F82)：backend/ 与 vigilant-couscous/ 通过（配置见 .flake8，与 CI 一致）

## OKX 连通性
- API 网关：www.okx.com（官方域名；文档中的第三方镜像域名已移除）
- K 线数据：实时返回（沙箱环境不可达时 REST 超时 15s，属预期）
- 盘口数据：实时返回
- WebSocket：已配置（含重连）

## P1 对齐与清障（2026-10-16，docs/AUDIT_AND_REFACTOR_PLAN.md 阶段 P1）
- 工作副本重新 clone 自远端 main @ eb555e90d1（本地旧副本为空 init 已废弃）
- 删除 39 项死代码/垃圾：backend/core/vc_adapter.py；vc core/cli/web/trading 四整包；
  vc/Dockerfile + docker-compose.yml（CMD 指向已删 web/）；strategy 3 个一次性脚本；
  frontend app.js/styles.css 孤儿；docs 前端三件重复拷贝；scripts 12 个一次性推送脚本；
  垃圾文件 " m flutter_app"；.github 大写 PR 模板（GitHub 仅识别小写，Windows checkout 冲突源）
- 保留修正：vc/data 整目录保留（portfolio_manager/live_trader 被 vc/tests 覆盖，审计曾漏列）；
  vc/tests 保留（CI 实际执行）
- 配置补齐：新增 pyproject.toml（无 build-system，发布流 P5 重建）、.flake8（与 CI 一致）、
  .dockerignore、LICENSE（MIT，与 vc 一致）；.env.example 补 API_AUTH_KEY
- 死变量清除：OKX_DEMO 全仓清零（Dockerfile/devcontainer/SECURITY.md 建议/vc config.py
  改读 OKX_SIMULATED——该键无生产消费者，'demo' 键保留以不破坏 vc 测试断言）
- 文档口径统一：README/architecture 65→73 工作流、lightweight-charts→Chart.js；
  MCP 声称删除（copilot-instructions/CONTRIBUTING/profile/wiki，模块不存在）；
  vc SUPPORT.md 修复失效命令与 you200109/- 坏链接；wiki 删死链与已删模块条目
- 门禁：compileall ✅ / flake8 0+0 ✅ / pytest 5+50 ✅ / smoke 16/16 ✅
