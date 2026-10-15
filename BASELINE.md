# 基线记录

日期：2026-10-15（当晚安全加固后更新）

## Git
- 提交数：25+
- 分支数：1 (main)
- 标签数：1 (v1.0.0)
- 仓库大小：~2 MB

## 代码
- Python 文件：86（backend 12 + vigilant-couscous 110 目录内 + scripts/tests 等）
- 依赖数量：15 (requirements.txt，已固定版本)
- vigilant-couscous 依赖：257

## 测试
- 覆盖率：低（tests/ 存在 1 个测试文件，核心引擎经手工冒烟验证）
- 冒烟验证（2026-10-15 本地）：508 指标加载、12 个常用指标计算、ma_cross 回测（17 笔交易）、
  认证中间件 401 拦截、健康检查 200、AGI 状态接口、82 策略加载

## CI
- 工作流数量：80
- 已知失败（修复前）：CI（py3.11 矩阵与 pandas-ta 冲突）、CI Smoke Test（依赖不全）、
  CodeQL、meta-evolve、auto-search
- 本次修复：CI 矩阵改为 3.12/3.13；Smoke Test 改全量依赖 + 重试式健康检查；
  7 个工作流补齐 permissions 声明

## 安全
- 密钥告警：0 (gitleaks 通过，.env 已忽略)
- Dependabot 告警：14（urllib3 7 / chromadb 4 / werkzeug+multidict 3）
  - urllib3 无法升级：okx==2.1.2 上游精确锁定 urllib3==1.26.12，缓解=网络层出口控制
  - chromadb：仅 vigilant-couscous 使用，主服务不依赖
- 代码扫描告警：30（10 个工作流缺 permissions【已修】+ 5 处堆栈泄露【已修】+ CVE 同步项）
- 本次修复：
  1. vc_routes 路径遍历漏洞（/api/vc/memory/nexus/{filename} 可读任意文件）→ 已加白名单校验
  2. 认证中间件硬编码默认密钥 quanttrading-secret-key → 改为 API_AUTH_KEY 未配置即 503 拒绝
  3. 认证比较改为 hmac.compare_digest 防计时攻击
  4. 认证策略改为默认拒绝（/api/ 与 /ws/ 未显式放行一律需认证）
  5. vc_routes 8 处 str(e) 直接返回客户端 → 改为服务端日志 + 通用错误文案
  6. main.py 链路追踪不再记录异常详情（防 /api/system/traces 泄露）
  7. 指标引擎静默吞异常 → 全部改为 warning 日志；修复 macd/bbands/atr 因传入
     整个 DataFrame 导致静默失败/参数错误的 bug（改按函数签名传价格序列）

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
