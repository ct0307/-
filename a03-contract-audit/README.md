# 契鉴 · 企业合同合规审查系统

> 浙江省职业技能大赛 · 外包赛道 · A03 赛题 · 海康-南湖研究院命题

企业级合同合规审查工作台。面向法务、财务、管理层，将 AI 审查能力包装为**双 Agent 协同 + 可解释 RAG + 人工复核闭环 + 多维报表**。系统支持私有化部署，本地 Embedding 全程离线运行；使用私有化 LLM 时，合同数据无需离开企业环境。

## 当前进度

> 更新于 2026-09-01。详细改动与验证记录见 [PROGRESS.md](./PROGRESS.md)。

| 范围 | 状态 | 最新结果 |
|---|---|---|
| 核心业务闭环 | ✅ 已完成 | 上传、加密、解析、双 Agent 审查、人工复核、整改与报表已贯通 |
| RAG 证据链 | ✅ 已加固 | 逐风险检索可靠依据，无可靠来源时转人工复核并将置信度封顶 50 |
| 知识库 | ✅ 能力已验证 | 本机演示库曾验证 973 条、512 维向量；数据库不随源码分发，新环境需运行种子与法规导入脚本 |
| 自动化验证 | ✅ 本轮通过 | 后端 142 passed/1 skipped；前端 19 passed/0 skipped；类型检查与生产构建通过 |
| 前端质量 | ✅ 已验证 | 浏览器走查覆盖 9 个业务页，完成 1440×900 桌面端及 390×844 移动端重点验收 |
| 参赛交付材料 | 🚧 核心文档完成 | 重构版详细方案和 9 页项目概要已完成；PPT、测试报告/用例、团队过程材料和演示视频待制作 |

## 当前交付材料

仓库级统一入口见 [参赛交付物索引](../deliverables/README.md)。当前推荐使用两份重构版 DOCX；原 17 章和 12 页材料作为历史版本保留。

| 材料 | 状态 | 说明 |
|---|---|---|
| [项目详细方案重构版（Word）](./契鉴_项目详细方案_重构版.docx) | ✅ 推荐 | 7 章往届式版本，已完成 Word 分页、结构、事实、语言和逐页视觉验收 |
| [项目概要介绍重构版（Word）](./docs/project-overview/契鉴_项目概要介绍_重构版.docx) | ✅ 推荐 | 9 页往届式版本，已完成结构、事实、语言和逐页视觉验收 |
| [原项目详细方案（Word）](./docs/contract-solution/契鉴_项目详细方案.docx) | 历史版本 | 49 页、17 章，保留用于回归和内容追溯 |
| [原项目详细方案（PDF）](./docs/contract-solution/契鉴_项目详细方案.pdf) | 历史版本 | 原 17 章方案的同步预览版 |
| [原项目概要介绍（Word）](./docs/project-overview/契鉴_项目概要介绍.docx) | 历史版本 | 原 12 页材料，保留用于回归和内容追溯 |
| [原项目概要介绍（PDF）](./docs/project-overview/契鉴_项目概要介绍.pdf) | 历史版本 | 原 12 页概要的同步预览版 |
| 项目简介 PPT | ⏳ 待制作 | 用于进度汇报与答辩展示 |
| 测试报告与测试用例 | ⏳ 待整理 | 汇总已有自动化测试、端到端验证和准确率证据 |
| 演示视频 | ⏳ 待制作 | 录制 3～5 分钟核心业务闭环 |

---

## 核心功能

| 模块 | 说明 |
|---|---|
| **合同审查** | 上传→加密存储→文本解析→双 Agent（法务+财务）协同审查→风险清单 |
| **可解释风险** | 每条风险独立检索：原文引用 + 可靠法规来源 + 置信度 + 人工复核状态；证据缺失时强制复核 |
| **多维报表** | KPI 看板 + 趋势图 + 风险分布 + 合同要素汇总（甲方/合同标的/收付款节点）+ Excel 台账导出 |
| **RAG 知识库** | 本地 Embedding + BM25 混合检索与 RRF 融合；本机演示库曾验证 973 条，支持批量导入、适用性过滤和版本治理 |
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
| RAG 检索 | sentence-transformers（BAAI/bge-small-zh-v1.5，本地离线）+ BM25 + RRF 融合 |
| 文档解析 | pdfplumber · PyMuPDF · python-docx · RapidOCR · ONNX Runtime · 正则与 LLM 要素精抽 |
| 报表 | openpyxl（Excel 台账） |
| AI 接入 | 统一 LLM Adapter，可切 DeepSeek / Qwen / OpenClaw |
| 权限 | PyJWT + RBAC + 审计日志 |
| 部署与迁移 | Docker Compose（PostgreSQL + Redis + FastAPI + Celery worker/beat + Nginx）· Alembic |

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
│   │   ├── api/v1/endpoints/  # 40条 /api/ 路由
│   │   ├── core/              # 配置、安全、加密、日志
│   │   ├── db/                # 初始化、SQLite启动补列、会话
│   │   ├── llm/               # LLM Adapter（qwen/deepseek/openclaw）
│   │   ├── models/            # 13张数据库表
│   │   ├── schemas/           # Pydantic 请求/响应类型
│   │   └── services/
│   │       ├── audit/         # 双Agent审查、冲突消解、风险分级
│   │       ├── parser/        # PDF/Word 解析 + OCR + 正则/LLM 要素提取
│   │       ├── batch/         # 批次状态机、进度、租约与重试
│   │       ├── rag/           # 本地向量 + BM25 + RRF 混合检索
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
│   ├── contract-solution/     # 项目详细方案源稿、DOCX/PDF与构建脚本
│   └── deployment.md          # 部署详细文档
├── docker-compose.yml
├── README.md                  # 项目说明与交付材料索引
└── PROGRESS.md                # 开发与交付进度日志
```

---

## 本地一键质量门禁

在 Windows PowerShell 中从项目根目录运行：

```powershell
.\scripts\quality_gate.ps1
```

默认按顺序执行评测专项、后端全量测试、前端 Playwright 测试、TypeScript 类型检查和生产构建。任一阶段失败会立即停止并返回非零退出码；汇总写入 `.quality-gate/summary.json`。默认模式主动清除测试子进程中的 `E2E_BASE_URL`，因此需要本地服务的现有 E2E 会按测试约定如实跳过。

需要连同本地服务型 E2E 一起验证时运行：

```powershell
.\scripts\quality_gate.ps1 -IncludeE2E
```

该模式要求 `127.0.0.1:8000` 和 `127.0.0.1:5173` 未被占用。脚本只启动并回收自己创建的 uvicorn 与 Vite 进程，不终止已有服务。依赖或工具缺失时脚本直接失败，不会自动安装软件。

本地质量门禁用于防止开发回归，**不等于真实硬指标验收**。它不会替代真实 52 份文件、PostgreSQL 16、Docker Compose、OpenClaw、GPU 或功率数据的实机证据，也不会自动提交、推送或部署代码。


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
