# 支持指南

## 获取帮助

### 文档
- [运维 Runbook](https://github.com/you200109/-/wiki)
- [API 文档](https://github.com/you200109/-/wiki/API)
- [架构文档](https://github.com/you200109/-/wiki/Architecture)

### 问题反馈
- [提交 Bug](https://github.com/you200109/-/issues/new?template=bug_report.yml)
- [功能请求](https://github.com/you200109/-/issues/new?template=feature_request.yml)
- [安全漏洞](https://github.com/you200109/-/security/advisories/new)

### 社区
- [GitHub Discussions](https://github.com/you200109/-/discussions)

### 常见问题

**Q: 如何启动系统？**
```bash
python web_console.py  # Web 控制台
python auto_trade.py --once  # 单次交易
python auto_evolve_scheduler.py --interval 15  # 自动进化
```

**Q: 如何配置 API 凭证？**
设置环境变量：`OKX_API_KEY`、`OKX_SECRET_KEY`、`OKX_PASSPHRASE`、`GITHUB_TOKEN`

**Q: 系统支持哪些币种？**
BTC/USDT、ETH/USDT、SOL/USDT，可通过 config.py 扩展
