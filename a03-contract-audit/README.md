# 契鉴 · 企业合同合规审查系统

> 浙江省职业技能大赛 · 外包赛道 · A03 赛题 · 海康-南湖研究院命题

企业级合同合规审查工作台。面向法务、财务、管理层，将 AI 审查能力包装为**双 Agent 协同 + 可解释 RAG + 人工复核闭环 + 多维报表**，支持私有化部署，合同数据不出企业。

---

## 核心功能

| 模块 | 说明 |
|---|---|
| **合同审查** | 上传→加密存储→文本解析→双 Agent（法务+财务）协同审查→风险清单 |
| **可解释风险** | 每条风险独立检索：原文引用 + 法规来源 + 置信度 + 人工复核状态；证据缺失时强制复核 |
| **多维报表** | KPI 看板 + 趋势图 + 风险分布 + 合同要素汇总（甲方/合同标的/收付款节点）+ Excel 台账导出 |
| **RAG 知识库** | 本地 embedding（BAAI/bge-small-zh），41 条预置法规，支持批量文件导入 |
| **批量处理** | 服务端持久化批次及审查维度，单批 1~200 份，支持幂等提交、失败隔离、启动补投、租约去重和失败项重试 |
| **智能协同审查** | 法务先行→共享上下文→财务交叉验证→冲突消解→风险分级（绿/黄/红档）|
| **风险追问 AI** | 绑定合同上下文，对话历史管理，可追问具体条款的谈判空间、行业常规 |
| **人工审核闭环** | 待复核/已确认/已忽略/需修改→自动生成整改跟踪项 |
| **RBAC + 审计** | 4角色：admin/legal/finance/business，操作审计日志 + IP 追踪 + LLM 调用记录 |
| **数据安全** | Fernet 加密存储 + 字段级脱敏 + 部门访问隔离 + TLS 就绪 |
| **基础配置** | 管理员可增删业务部门、合同类型下拉选项 |

---

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 · TypeScript · Vite · Element Plus · ECharts ≥ 6.1 · Pinia |
| 后端 | Python 3.11 · FastAPI · SQLAlchemy · pydantic-settings |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| 向量检索 | sentence-transformers（BAAI/bge-small-zh-v1.5，本地离线） |
| 文档解析 | pdfplumber · PyMuPDF · python-docx · RapidOCR · ONNX Runtime |
| 报表 | openpyxl（Excel 台账） |
| AI 接入 | 统一 LLM Adapter，可切 DeepSeek / Qwen / OpenClaw |
| 权限 | PyJWT + RBAC + 审计日志 |
| 部署 | Docker Compose（PostgreSQL + Redis + FastAPI + Celery worker/beat + Nginx）|

---

## 快速启动

### 方式一：Docker Compose（推荐）

```bash
# 1. 克隆仓库
git clone <repo-url>
cd a03-contract-audit

# 2. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 .env，至少设置 LLM_API_KEY

# 3. 一键启动（backend 会先执行 alembic upgrade head）
docker compose up -d

# 前端：http://localhost
# 后端 API 文档：http://localhost:8000/docs
```

> embedding 模型在镜像构建阶段下载并固化。OCR 引擎模型随 RapidOCR wheel 交付；真实引擎冒烟和准确率边界见 `docs/evaluation/hard-indicator-matrix.md`。

### 方式二：本地开发

```bash
# 后端（backend 目录）
python -m venv .venv
./.venv/Scripts/activate          # Windows
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（frontend 目录）
npm install
npm run dev                        # http://localhost:5173

# 灌演示数据（可选，幂等可重跑）
cd backend
python -m scripts.seed_demo
```

---

## 演示账号

| 账号 | 密码 | 角色 | 可访问模块 |
|---|---|---|---|
| admin | admin123 | 系统管理员 | 全部 |
| legal | legal123 | 法务主管 | 全部（除规则/审计管理）|
| finance | finance123 | 财务主管 | 全部（除规则/审计管理）|
| business | business123 | 业务人员 | 工作台/审查/整改/报表/知识库/历史 |

---

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_PROVIDER` | `qwen` | `qwen` / `deepseek` / `openclaw` |
| `LLM_API_KEY` | _(必填)_ | 对应 LLM 服务的 API Key |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | 私有化模型端点 |
| `FILE_ENCRYPT_KEY` | _(空=不加密)_ | Fernet 密钥；生产为空或格式错误时拒绝启动 |
| `DB_BACKEND` | `sqlite` | `sqlite` / `postgres` |
| `JWT_SECRET` | `CHANGE_ME` | 生产必须替换为至少 32 位独立密钥 |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker/result backend |
| `AUDIT_ASYNC` | `false` | 交付环境必须为 `true` |
| `OCR_MAX_PAGES` | `100` | 单次 OCR 最大页数 |
| `OCR_MAX_PAGE_PIXELS` | `16000000` | 单页渲染像素上限 |
| `OCR_TIMEOUT_SECONDS` | `120` | 单份 PDF OCR 总超时 |
| `OCR_MIN_CONFIDENCE` | `0.75` | 低于此值标记人工复核 |

生产环境会在进程启动时校验 `DEBUG=false`、PostgreSQL、异步任务、数据库密码、JWT 密钥和 Fernet 密钥；任一项仍为弱默认值时 backend、worker 和迁移命令都会直接失败。

生成加密密钥：
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## 项目结构

```
a03-contract-audit/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/  # 25条路由端点
│   │   ├── core/              # 配置、安全、加密、日志
│   │   ├── db/                # 初始化、热迁移、会话
│   │   ├── llm/               # LLM Adapter（qwen/deepseek/openclaw）
│   │   ├── models/            # 13张数据库表
│   │   ├── schemas/           # Pydantic 请求/响应类型
│   │   └── services/
│   │       ├── audit/         # 双Agent审查、冲突消解、风险分级
│   │       ├── parser/        # PDF/Word 解析 + OCR 适配 + 要素提取
│   │       ├── batch/         # 批次状态机、进度、租约与重试
│   │       ├── rag/           # 向量检索（本地embedding）
│   │       └── report/        # Excel 台账 + 看板聚合
│   ├── alembic/               # PostgreSQL 全量可回滚迁移
│   ├── evaluation/            # 要素准确率与算力基准工具
│   ├── scripts/
│   │   ├── seed_demo.py       # 演示数据（幂等）
│   │   └── seed_knowledge_law.py  # 预置法规知识库
│   ├── .env.example
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/               # 后端接口封装（含 mock 开关）
│       ├── components/        # 公共组件、图表、布局
│       ├── stores/            # Pinia（auth/audit-session/notify/rectify）
│       └── views/             # 10个页面视图
├── docs/
│   └── deployment.md          # 部署详细文档
├── docker-compose.yml
└── PROGRESS.md                # 开发进度日志
```

---

## 验收指标

| 指标 | 目标 | 状态 |
|---|---|---|
| 合同要素抽取准确率 | ≥ 90% | 评测工具已就绪；待人工冻结金标准实测 |
| 批量处理能力 | 50 份以上 | 代码与自动化契约已验证；待 50+2 真实文件验收 |
| 风险可解释性 | 原文+依据+建议 | 风险级独立证据绑定测试通过 |
| 人工审核状态流转 | 4态+操作日志 | 已实现并有回归测试 |
| 私有化部署 | 本地/企业内网 | Compose 配置与迁移烟雾测试通过；本机无 Docker，容器未实测 |
| 算力对比 | OpenClaw vs GPU | 同口径统计工具已就绪；缺两套真实硬件和功率数据，未出结论 |

详细证据、复现命令和阻塞项见 [`docs/evaluation/hard-indicator-matrix.md`](docs/evaluation/hard-indicator-matrix.md)。
