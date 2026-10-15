# 基线记录

日期：2026-10-15（当晚安全加固 + CI 全量修复后更新，main @ 4b80d099a5）

## Git
- 提交数：30+
- 分支数：1 (main；Dependabot 临时分支随 PR 关闭而清理)
- 标签数：1 (v1.0.0)
- 仓库大小：~2 MB

## 代码
- Python 文件：86（backend 12 + vigilant-couscous 59 + scripts/tests 等）
- 依赖数量：14 (requirements.txt，已固定版本)
- vigilant-couscous 依赖：12（原为 257 个包的开发机 freeze，已按 pyproject 精简；
  实测 vc_routes 导入的全部模块在根依赖下完整工作，AGI/风控端点冒烟通过）

## 测试
- 覆盖率：低（tests/ 存在 1 个测试文件，核心引擎经手工冒烟验证）
- 冒烟验证（2026-10-15 本地，API_AUTH_KEY 认证后）：508 指标加载、12 个常用指标计算、
  ma_cross 回测（17 笔交易）、认证中间件 401 拦截（无 key）/ 放行（有 key）、
  健康检查 ok、AGI 状态接口真实出数（total_decisions/knowledge_entries）、
  风控状态接口、82 策略加载

## CI（本轮全部修复，main 全线绿）
- 工作流数量：79（删除重复的 auto-search-okx.yml，保留 auto-search.yml）
- 修复清单：
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
- Dependabot PR：14 个全部关闭（均基于已删除的 257 包 freeze，附说明评论）

## 安全
- 密钥告警：0 (gitleaks 通过，.env 已忽略)
- Dependabot 告警：14 → 预期收敛至 urllib3 系列（chromadb/werkzeug/multidict 源自已删除的
  vc freeze，待 Dependabot 重扫后自动关闭）
  - urllib3 无法升级：okx==2.1.2 上游精确锁定 urllib3==1.26.12，缓解=网络层出口控制
- 代码扫描告警：30（10 个工作流缺 permissions【已修】+ 5 处堆栈泄露【已修】+ CVE 同步项）
- 历史修复（见上一版基线）：vc_routes 路径遍历、认证硬编码密钥/计时攻击/默认公开、
  vc_routes 8 处 str(e) 泄露、main.py 追踪记录泄露、指标引擎静默吞异常与
  macd/bbands/atr 传参 bug

## 性能
- 指标引擎初始化：<0.1s（单例，508 指标）
- 回测耗时：~0.02s (300 根 K 线)
- 内存峰值：~140 MB（服务运行态实测）

## 代码质量
- flake8 (E9,F63,F7,F82)：backend/ 与 tests/ 通过

## OKX 连通性
- API 网关：www.okx.com（官方域名；文档中的第三方镜像域名已移除）
- K 线数据：实时返回（沙箱环境不可达时 REST 超时 15s，属预期）
- 盘口数据：实时返回
- WebSocket：已配置（含重连）
