# GitHub Codespaces 使用指南

## 什么是 Codespaces

GitHub Codespaces 是 GitHub 提供的云端开发环境，可以直接在浏览器中或 VS Code 中运行完整的开发环境，无需本地安装任何软件。

## 启动 Codespaces

### 方法一：通过 GitHub 网页
1. 访问仓库页面：https://github.com/you200109/quanttrading
2. 点击绿色按钮 **Code** → 选择 **Codespaces** 标签
3. 点击 **Create codespace on main**
4. 等待环境构建完成（约 2-3 分钟）
5. 自动打开 VS Code Web 编辑器

### 方法二：通过 VS Code
1. 安装 VS Code 和 GitHub Codespaces 扩展
2. 按 `Ctrl+Shift+P` → 输入 `Codespaces: Create New Codespace`
3. 选择仓库 `you200109/quanttrading` → 分支 `main`
4. 选择机器类型（推荐 4-core）

## 环境配置

Codespaces 会自动执行以下操作：
- 安装 Python 3.12 + Node.js 20
- 安装项目依赖（requirements.txt）
- 安装 vc 依赖（vigilant-couscous/requirements.txt）
- 安装 VS Code 扩展（Python、flake8、Pylance、YAML、Copilot）
- 转发端口 8000（FastAPI）和 8001（WebSocket）

## 启动后端服务

```bash
# 在 Codespaces 终端中执行
cd /workspaces/quanttrading
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

浏览器会自动打开 `http://localhost:8000`，显示前端可视化界面。

## 运行测试

```bash
# 主系统测试
cd /workspaces/quanttrading
python -m pytest tests/ -v

# vc 测试
cd /workspaces/quanttrading/vigilant-couscous
python -m pytest tests/ -v -o addopts=''
```

## 运行合并后检查

```bash
cd /workspaces/quanttrading
python scripts/post_merge_check.py
```

## 配置环境变量

在 Codespaces 中设置 Secrets：
1. 仓库 Settings → Secrets and variables → Codespaces
2. 添加以下 Secrets：
   - `OKX_API_KEY` — OKX API Key
   - `OKX_SECRET_KEY` — OKX Secret Key
   - `OKX_PASSPHRASE` — OKX Passphrase
   - `GITHUB_TOKEN` — GitHub PAT

## 机器类型选择

| 类型 | CPU | 内存 | 存储 | 适用场景 |
|------|-----|------|------|----------|
| 2-core | 2 | 8GB | 32GB | 轻量开发 |
| 4-core | 4 | 16GB | 32GB | 推荐 |
| 8-core | 8 | 32GB | 64GB | 重度开发 |
| 16-core | 16 | 64GB | 128GB | 大规模计算 |

## 免费额度

- 个人账户：每月 120 core-hours（2-core）+ 15GB 存储
- PRO 账户：每月 180 core-hours + 20GB 存储

## 停止和删除

- 停止：Codespaces 列表 → 点击 ⋮ → Stop codespace
- 删除：Codespaces 列表 → 点击 ⋮ → Delete
- 建议不使用时停止，以节省额度

## 常见问题

### Q: 端口没有自动转发？
A: 在 VS Code 终端中，点击 PORTS 标签，手动转发 8000 端口。

### Q: 依赖安装失败？
A: 在终端中手动执行 `pip install -r requirements.txt`。

### Q: 如何访问数据库？
A: 项目使用 SQLite，数据存储在 `memory/nexus/` 目录下，无需额外配置。
