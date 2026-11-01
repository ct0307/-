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
- 至少 8GB 可用内存；模型推理资源按所选模型另行评估

### 步骤

```bash
# 1. 克隆仓库
git clone <repo-url>
cd a03-contract-audit

# 2. 配置环境变量
cp backend/.env.example backend/.env
vim backend/.env   # 至少设置数据库密码、JWT_SECRET、FILE_ENCRYPT_KEY 和模型端点

# 3. 构建并启动；backend 启动前自动执行 alembic upgrade head
docker compose up -d --build

# 4. 查看状态
docker compose ps
docker compose logs backend --tail=50

# 5. 生产空库创建首个管理员（隐藏输入密码两次）
docker compose exec backend python -m scripts.bootstrap_admin --username ops-admin
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
| `postgres` | postgres:16-alpine | 内网 | `postgres_data` |
| `redis` | redis:7-alpine | 内网 | `redis_data`（AOF）|
| `backend` | python:3.11-slim | 8000 | `contract_storage`（加密合同文件）|
| `worker` | 与 backend 相同 | 无 | 共享 `contract_storage` |
| `scheduler` | 与 backend 相同 | 无 | Celery Beat，每 60 秒触发孤儿任务恢复 |
| `frontend` | nginx:alpine | 80 | 无 |

### 常用命令

```bash
# 停止
docker compose down

# 重建镜像（代码更新后）
docker compose up -d --build

# 查看后端日志
docker compose logs -f backend

# 查看 worker 日志
docker compose logs -f worker

# 查看周期恢复调度日志
docker compose logs -f scheduler

# 进入后端容器
docker compose exec backend bash

# 备份 PostgreSQL（示例文件名按实际日期填写）
docker compose exec -T postgres pg_dump -U a03 -d a03_contract > backup.sql

# 验证迁移状态
docker compose exec backend alembic current
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
LLM_BASE_URL=https://yorhamc.com/v1
LLM_API_KEY=sk-xxxxx
LLM_MODEL=deepseek-v4-flash
LLM_MAX_OUTPUT_TOKENS=3200
LLM_TIMEOUT=120
```

**私有化模型（企业推荐）：**

```env
LLM_PROVIDER=qwen
LLM_BASE_URL=http://10.x.x.x:11434/v1   # 内网 Ollama 地址
LLM_API_KEY=                              # 内网无需 Key
LLM_MODEL=qwen2.5:14b
LLM_MAX_OUTPUT_TOKENS=3200
```

### 安全配置

```env
# 生产必须修改，不能使用默认值
JWT_SECRET=your-strong-secret-here

# 合同文件加密密钥（生产强制，空值或无效值会拒绝启动）
FILE_ENCRYPT_KEY=<fernet_key>

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
POSTGRES_PASSWORD=<至少12位独立数据库密码>
POSTGRES_DB=a03_contract

# 异步批次
REDIS_URL=redis://redis:6379/0
AUDIT_ASYNC=true

# OCR 资源门槛
OCR_MAX_PAGES=100
OCR_MAX_PAGE_PIXELS=16000000
OCR_DPI=180
OCR_TIMEOUT_SECONDS=120
OCR_MIN_CONFIDENCE=0.75
```

---

## 数据初始化

### 首个管理员（生产）

先完成迁移和生产配置：`APP_ENV=prod`、`DEBUG=false`、PostgreSQL、`AUDIT_ASYNC=true`、非默认数据库密码、至少32字符且满足配置策略的 JWT 密钥、有效 Fernet 密钥。初始化命令复用应用的生产安全校验；迁移失败或配置不满足时拒绝建号。

```powershell
# 在项目根目录执行；使用当前后端配置数据库，不创建或重置表。
Set-Location backend
.\.venv\Scripts\python.exe -m scripts.bootstrap_admin --username ops-admin
```

```bash
# 容器内方式，须保留交互终端输入密码。
docker compose exec backend python -m scripts.bootstrap_admin --username ops-admin
```

密码至少12个字符、UTF-8编码最多72字节，默认弱密码被拒绝；中文字符通常占3字节。命令不接收命令行密码参数。禁止把密码写入脚本、命令历史或日志。登录入口也拒绝超过72字节的输入（HTTP 422），不会截断密码。

同名账号或任意已有管理员都会拒绝初始化，不覆盖账号。创建账号与 `bootstrap_admin` 审计记录同事务提交，失败自动回滚；PostgreSQL使用事务咨询锁、SQLite开发环境使用写事务锁串行检查。命令成功后再次运行返回非零码；其他账号管理应走已有授权管理流程。该命令不参与服务启动，也不提供未认证建号接口。

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

上述合同、风险和调用记录均为演示数据，不是生产业务数据或模型真实评测结果。生产禁止执行 `seed_demo`。

### 上传容量与证据核验

| 配置 | 默认值 | 行为 |
|---|---|---|
| `MAX_UPLOAD_MB` | 50 | 每个文件最多50 MiB |
| `MAX_BATCH_FILES` | 200 | 每批最多200个文件，追加计入已有有效项和失败项 |
| `MAX_BATCH_MB` | 500 | 每批累计原始上传字节最多500 MiB |
| `EVIDENCE_VALIDATION_MODE` | `manual_only` | 候选资料交人工核验 |

容量配置须为正整数。前端从认证接口 `GET /api/v1/imports/limits` 读取限制；读取失败显示“上传时由服务器校验”，保留上传入口，不使用猜测值。文件数或总字节超限返回HTTP 413及 `BATCH_TOO_LARGE`；单文件超限为 `FILE_TOO_LARGE`。整批容量检查在持久化前执行，合法批次仍保留逐文件失败隔离。

追加导入按每项的原始上传大小累计，包含解析失败项，排除已删除项；新项通过同事务审计元数据记录大小。旧项读取原文或解密后计算，不按Fernet膨胀后的磁盘大小计算。旧项文件缺失、为空、解密失败或哈希不一致时返回409及 `IMPORT_BATCH_CAPACITY_UNKNOWN`，需恢复文件或新建收件箱。

项目Nginx默认 `client_max_body_size 520m`，覆盖默认500 MiB和协议开销。该值不是环境变量自动生成的模板；若增大 `MAX_BATCH_MB`，必须人工同步 `frontend/nginx.conf` 及所有外层网关限制并留协议余量，否则代理可能先返回413。外层Nginx示例也应配置同一上限。

`deterministic` 当前仅支持一个有限场景：原文精确定位、无附条件/例外/引用的限定绝对免责完整句式，且可信、适用来源为民法典506条完整限定正文。结果版本为 `support-deterministic-v1`，绑定 `LEGAL-INJURY-WAIVER-001@1.0.0`；不覆盖一般违约金高低或其他法律判断。词语重叠不构成采信依据，条件不足或验证器异常返回 `unclear`；默认 `manual_only` 保持人工接管。

核验模式、版本、失败阶段、原因码在API、追问、报告与前端贯通；当前已核验还要求原文、来源、证据编号和成功原因码完整。旧版 `rules-v2` 不计为当前已核验。人工复核保存操作人ID、带时区时间和意见，并同事务写审计记录；人工确认独立于机器核验，不把候选法条变成已验证法律结论。

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

### 2. 数据库迁移

```bash
# 在 backend 目录或 backend 容器内执行
alembic -c alembic.ini upgrade head
alembic -c alembic.ini current
```

生产应用不会执行 `create_all`，也不会自动灌入演示账号。首次上线前执行上面的 `scripts.bootstrap_admin`；`scripts.seed_demo` 仅限开发或竞赛演示环境。

生产配置采用 fail-fast：`DEBUG=true`、SQLite、同步审查、默认数据库密码、弱 JWT 密钥或无效 Fernet 密钥都会阻止 backend、worker 和 Alembic 启动，避免服务以不安全配置进入健康状态。

批次创建会持久化原始审查维度。backend 启动、Celery worker 就绪时会立即扫描，scheduler 还会每 60 秒扫描未发布的 `queued` 项及租约过期项并重新投递；数据库行锁和有效租约负责拦截重复执行。失败重试默认沿用原批次维度，避免改变审查口径。

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
    client_max_body_size 520m;
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
| 合同解析为空 | 检查日志中的 `parser.pdf_empty` / `parser.ocr_*`；未安装 OCR 引擎时会明确失败，不会静默判定无风险 |
| worker 无任务 | 检查 `REDIS_URL`、`AUDIT_ASYNC=true` 与 `docker compose logs worker` |
| 数据表缺失 | 执行 `alembic current`，确认位于 `20260726_01 (head)` |

## SQLite 迁移到 PostgreSQL

迁移必须安排维护窗口，先停止 backend、worker 和 scheduler，确保 SQLite 不再写入。保留 SQLite 文件和上传文件目录的只读备份，目标 PostgreSQL 必须是已执行 Alembic 且业务表为空的新库。

```powershell
# 1. 备份源库；按实际路径调整
Copy-Item -LiteralPath backend/storage/a03_dev.db -Destination backup/a03_dev.db

# 2. 在目标 PostgreSQL 建立最新结构
$env:DB_BACKEND = 'postgres'
alembic -c backend/alembic.ini upgrade head

# 3. 只读统计源库，不写目标库
Set-Location backend
python -m scripts.migrate_sqlite_to_postgres --sqlite-path storage/a03_dev.db

# 4. 目标 URL 通过环境变量传入，避免密码进入命令历史
$env:A03_POSTGRES_URL = 'postgresql+psycopg://user:password@host:5432/a03_contract'
python -m scripts.migrate_sqlite_to_postgres `
  --sqlite-path storage/a03_dev.db `
  --execute
```

脚本在单一目标事务中按外键依赖顺序导入，逐表输出并核对源/目标行数，同时校准 PostgreSQL 自增序列。目标表非空、结构缺失、写入失败或数量不一致时，事务整体回滚；修复原因后可对空目标库重试。成功后先以只读方式抽查合同、风险、知识库和审计日志，再恢复服务。上传文件不在数据库脚本范围内，必须单独复制并保持 `storage_path` 可解析；确认验收前不要删除 SQLite 和文件备份。

## 当前验证边界

- Alembic 已在临时 SQLite 完成空库升级和完整回滚测试。
- Compose YAML 已做结构解析，但当前开发机没有 Docker CLI，尚未完成容器级启动验证。
- Compose 不会自动搬迁旧 `storage/a03_dev.db` 数据；已有 SQLite 业务数据的环境必须先冻结写入，执行受控导出、PostgreSQL 导入、数量/哈希核对和回滚演练。
- RapidOCR 3.9.2 / ONNX Runtime 1.28.0 已完成 wheel 完整性、许可证、传递依赖漏洞审计和真实图片/PDF 冒烟；详见 `evaluation/ocr-dependency-audit.md`。
- OCR 字符准确率仍缺冻结扫描件真值集，真实引擎冒烟不能替代准确率验收。
- 生产密钥、真实模型端点、PostgreSQL 备份恢复和 TLS 需在目标环境完成验收。
