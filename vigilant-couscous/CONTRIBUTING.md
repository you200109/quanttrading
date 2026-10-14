# 贡献指南

感谢您对自进化交易系统的关注！

## 开发环境

```bash
git clone https://github.com/you200109/-.git
cd self-evolution-trading
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

## 代码规范

- Python 3.12+
- 使用 black 格式化（行宽 100）
- 使用 ruff 进行代码检查
- 使用 mypy 进行类型检查
- 所有新功能需包含单元测试

## 提交规范

使用 Conventional Commits：

- `feat:` 新功能
- `fix:` Bug 修复
- `docs:` 文档更新
- `ci:` CI/CD 变更
- `refactor:` 代码重构
- `test:` 测试相关
- `chore:` 维护任务

## PR 流程

1. Fork 仓库并创建分支
2. 编写代码和测试
3. 运行 `pytest` 确保测试通过
4. 运行 `ruff check . && black --check .` 确保代码规范
5. 提交 PR 并填写模板
6. 等待 CI 检查和 Code Review

## 行为准则

请参阅 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
