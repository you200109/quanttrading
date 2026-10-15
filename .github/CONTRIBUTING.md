# 贡献指南

感谢您对 QuantTrading 项目的关注！本文档指导您如何参与贡献。

## 开发环境搭建

### 前置要求
- Python 3.12+
- Node.js 20+
- Git 2.40+

### 本地开发
```bash
git clone https://github.com/you200109/quanttrading.git
cd quanttrading
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### Codespaces 开发
1. 仓库页面 → Code → Codespaces → Create codespace on main
2. 环境自动构建完成
3. 终端执行 `python -m uvicorn backend.main:app --port 8000 --reload`

## 贡献流程

### 1. Fork & Clone
```bash
git remote add upstream https://github.com/you200109/quanttrading.git
```

### 2. 创建分支
```bash
git checkout -b feature/your-feature-name
```

### 3. 编码规范
- 遵循 PEP 8 规范
- 使用 flake8 检查：`flake8 backend/ --max-line-length=120`
- 使用 black 格式化：`black backend/`
- 添加类型注解

### 4. 测试
```bash
# 主系统测试
python -m pytest tests/ -v

# vc 测试
cd vigilant-couscous
python -m pytest tests/ -v -o addopts=''

# 合并后检查
python scripts/post_merge_check.py
```

### 5. 提交
```bash
git add -A
git commit -m "feat: 简短描述"
```

提交信息规范：
- `feat:` 新功能
- `fix:` 修复 Bug
- `docs:` 文档更新
- `refactor:` 代码重构
- `test:` 测试相关
- `ci:` CI/CD 相关
- `chore:` 其他杂项

### 6. 推送 & PR
```bash
git push origin feature/your-feature-name
```

在 GitHub 上创建 Pull Request，描述变更内容、测试结果和影响范围。

## 代码审查标准

- [ ] 通过 flake8 检查
- [ ] 通过单元测试
- [ ] 通过合并后检查（5/5）
- [ ] 无敏感信息泄露
- [ ] 代码有注释和文档
- [ ] 新功能有对应测试

## 项目结构

```
QuantTrading/
├── backend/           # FastAPI 后端
│   ├── api/           # API 路由
│   ├── core/          # 核心服务
│   └── indicators/    # 指标引擎
├── frontend/          # 前端页面
├── vigilant-couscous/ # AI 进化模块
├── scripts/           # 工具脚本
├── tests/             # 测试文件
├── .github/workflows/ # CI/CD 工作流
└── .devcontainer/     # Codespaces 配置
```

## 报告 Bug

使用 GitHub Issues 报告 Bug，请包含：
- 问题描述
- 复现步骤
- 期望行为
- 实际行为
- 环境信息（OS、Python 版本等）

## 功能建议

欢迎在 Discussions 中提出功能建议，描述：
- 功能需求
- 使用场景
- 预期效果

## 行为准则

参与本项目时，请遵守 [Code of Conduct](CODE_OF_CONDUCT.md)。

## 联系方式

- Issues: https://github.com/you200109/quanttrading/issues
- Discussions: https://github.com/you200109/quanttrading/discussions

再次感谢您的贡献！