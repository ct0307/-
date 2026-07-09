# 部署指南

## 目录

- [Docker Compose 部署（推荐）](#docker-compose-部署推荐)
- [本地开发环境](#本地开发环境)
- [环境变量详解](#环境变量详解)
- [数据初始化](#数据初始化)
- [生产环境注意事项](#生产环境注意事项)

---

## Docker Compose 部署（推荐）

### 前置条件

- Docker Desktop ≥ 24.0（含 Docker Compose v2）
- 至少 2GB 可用内存（embedding 模型需约 500MB）

### 步骤

```bash
# 1. 克隆仓库
git clone <repo-url>
cd a03-contract-audit

# 2. 配置环境变量
cp backend/.env.example backend/.env
vim backend/.env   # 最少设置 LLM_API_KEY 和 JWT_SECRET

# 3. 启动
docker compose up -d

# 4. 查看状态
docker compose ps
docker compose logs backend --tail=50

# 5. 灌演示数据（首次部署执行一次，幂等）
docker compose exec backend python -m scripts.seed_demo
```

### 访问

| 地址 | 说明 |
|---|---|
| `http://localhost` | 前端应用 |
| `http://localhost:8000/docs` | 后端 Swagger UI |
| `http://localhost:8000/api/v1/` | REST API 根路径 |

### 服务说明

| 服务 | 镜像基础 | 端口 | 数据持久化 |
|---|---|---|---|
| `a03_backend` | python:3.11-slim | 8000 | `contract_storage` volume（合同文件 + SQLite DB）|
| `a03_frontend` | nginx:alpine | 80 | 无（静态文件由镜像打包）|

### 常用命令

```bash
# 停止
docker compose down

# 重建镜像（代码更新后）
docker compose up -d --build

# 查看后端日志
docker compose logs -f backend

# 进入后端容器
docker compose exec backend bash

# 备份数据
docker cp a03_backend:/app/storage ./backup_$(date +%Y%m%d)
```

---

## 本地开发环境

### 后端

```bash
cd backend

# 创建虚拟环境（Python 3.11+）
python -m venv .venv

# 激活（Windows Git Bash）
./.venv/Scripts/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，设置 LLM_API_KEY 等

# 启动（开发模式，自动热重载）
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# API 文档：http://127.0.0.1:8000/docs
```

### 前端

```bash
cd frontend

# 安装依赖
npm install

# 开发服务器（自动代理 /api 到后端 :8000）
npm run dev
# 访问：http://localhost:5173

# 类型检查
npx vue-tsc --noEmit

# 生产构建
npm run build
```

---

## 环境变量详解

完整变量列表见 `backend/.env.example`，重点说明如下：

### LLM 配置

```env
LLM_PROVIDER=deepseek       # qwen / deepseek / openclaw
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-xxxxx
LLM_MODEL=deepseek-chat
LLM_TIMEOUT=120
```

**私有化模型（企业推荐）：**

```env
LLM_PROVIDER=qwen
LLM_BASE_URL=http://10.x.x.x:11434/v1   # 内网 Ollama 地址
LLM_API_KEY=                              # 内网无需 Key
LLM_MODEL=qwen2.5:14b
```

### 安全配置

```env
# 生产必须修改，不能使用默认值
JWT_SECRET=your-strong-secret-here

# 合同文件加密密钥（留空则明文存储，生产建议开启）
FILE_ENCRYPT_KEY=

# 生成命令：
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 数据库配置

```env
# 开发期 SQLite（无需额外安装）
DB_BACKEND=sqlite
SQLITE_PATH=storage/a03_dev.db

# 生产 PostgreSQL
DB_BACKEND=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=a03
POSTGRES_PASSWORD=a03pass
POSTGRES_DB=a03_contract
```

---

## 数据初始化

### 演示数据（开发/竞赛演示）

```bash
# 在 backend 目录下执行
python -m scripts.seed_demo
```

**包含内容：**
- 12份合同（4个部门，多种合同类型）
- 43条风险（覆盖 high/medium/low × legal/finance × 各复核状态）
- 41条知识库（法律法规17 / 标准条款9 / 风险规则11 / 典型案例4）
- 6条整改项（不同状态）
- 14条 LLM 调用记录（3种算力对比数据）
- 4个角色权限矩阵
- 26个下拉配置项（12部门 + 14合同类型）

脚本幂等，可重复执行。

### 仅灌知识库法规

```bash
python -m scripts.seed_knowledge_law
```

---

## 生产环境注意事项

### 1. 数据安全

```env
# 必须设置合同加密密钥
FILE_ENCRYPT_KEY=<fernet_key>

# 必须修改 JWT 密钥
JWT_SECRET=<strong_random_secret>

# 关闭调试模式
APP_ENV=prod
DEBUG=False
```

### 2. 数据库迁移（切换到 PostgreSQL）

```bash
# 当前：SQLite 开发期，支持自动补列（_DEV_COLUMNS 机制）
# 生产：使用 Alembic 迁移（路线图 P3）

# 临时方案：导出 SQLite → 导入 PostgreSQL
python -m scripts.migrate_sqlite_to_postgres  # 待实现
```

### 3. 模型私有化

```bash
# 方案：内网部署 Ollama + Qwen
# 1. 在内网服务器安装 Ollama
# 2. 拉取模型：ollama pull qwen2.5:14b
# 3. 修改 .env：
#    LLM_PROVIDER=qwen
#    LLM_BASE_URL=http://<内网IP>:11434/v1

# Embedding 模型已完全本地化（sentence-transformers），无需配置
```

### 4. Nginx 反向代理（生产）

如需在 Docker Compose 前加一层 Nginx：

```nginx
upstream a03_backend { server 127.0.0.1:8000; }
upstream a03_frontend { server 127.0.0.1:80; }

server {
    listen 443 ssl;
    # SSL 证书配置...

    location /api/ { proxy_pass http://a03_backend; }
    location / { proxy_pass http://a03_frontend; }
}
```

---

## 故障排查

| 问题 | 排查步骤 |
|---|---|
| 后端启动失败 | `docker compose logs backend` 查看具体错误 |
| embedding 模型下载慢 | 配置 HuggingFace 镜像：`HF_ENDPOINT=https://hf-mirror.com` |
| LLM 调用超时 | 调大 `LLM_TIMEOUT`；检查 API Key 和网络连通性 |
| 前端 502 | 确认 backend 服务已启动：`curl http://localhost:8000/api/v1/dashboard/summary` |
| 合同解析为空 | 扫描件 PDF 无文本层，需接入 OCR（路线图 P2）|
