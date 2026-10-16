# 部署指南

## 环境要求

- Python 3.12+
- Node.js 20+ (可选，用于前端构建)
- Git

## 安装步骤

### 1. 克隆仓库
```bash
git clone https://github.com/you200109/quanttrading.git
cd quanttrading
```

### 2. 安装Python依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 填入 OKX API 凭据
```

### 4. 启动后端服务
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 5. 访问系统
- 前端界面: http://localhost:8000/
- API文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

## OKX API 配置

### 国内服务器
```
OKX_API_HOST=www.okx.com
```

### 国际服务器
```
OKX_API_HOST=www.okx.com
```

### 代理配置（如需要）
```
OKX_PROXY=http://127.0.0.1:7890
```

## GitHub Actions

仓库已配置20个自动化工作流，推送代码后自动激活。

## Docker部署

```bash
docker build -t quanttrading .
docker run -p 8000:8000 --env-file .env quanttrading
```
