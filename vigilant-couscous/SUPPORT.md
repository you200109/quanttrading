# 支持指南

## 获取帮助

### 文档
- [运维 Runbook](https://github.com/you200109/quanttrading/wiki)
- [API 文档](https://github.com/you200109/quanttrading/wiki/API)
- [架构文档](https://github.com/you200109/quanttrading/wiki/Architecture)

### 问题反馈
- [提交 Bug](https://github.com/you200109/quanttrading/issues/new?template=bug_report.yml)
- [功能请求](https://github.com/you200109/quanttrading/issues/new?template=feature_request.yml)
- [安全漏洞](https://github.com/you200109/quanttrading/security/advisories/new)

### 社区
- [GitHub Discussions](https://github.com/you200109/quanttrading/discussions)

### 常见问题

**Q: 如何启动系统？**
```bash
# 在仓库根目录执行（主服务：FastAPI，端口 8000）
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

**Q: 如何启动自动进化调度器？**
```bash
# 在 vigilant-couscous/ 目录执行
python auto_evolve_scheduler.py --interval 15
```

**Q: 如何配置 API 凭证？**
设置环境变量：`OKX_API_KEY`、`OKX_SECRET_KEY`、`OKX_PASSPHRASE`、`GITHUB_TOKEN`；
服务认证另需 `API_AUTH_KEY`（见 .env.example）。

**Q: 系统支持哪些币种？**
BTC/USDT、ETH/USDT、SOL/USDT，可通过 config.py 扩展
