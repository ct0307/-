# A03 企业合同合规审查系统

企业级合同合规审查与多维报表生成智能体。面向企业法务、财务、管理层，提供合同风险体检、可解释审查结论、人工复核闭环与多维报表，支持私有化部署。

> 目标优先级：**企业真实交付第一，参赛演示第二**。详见项目根 `../CLAUDE.md`。

## 架构总览

```
a03-contract-audit/
├── backend/          # FastAPI 后端
│   ├── app/
│   │   ├── core/         # 配置、安全、日志、依赖注入
│   │   ├── api/v1/       # 路由与端点
│   │   ├── models/       # SQLAlchemy ORM 模型
│   │   ├── schemas/      # Pydantic 请求/响应模型
│   │   ├── services/     # 业务逻辑
│   │   │   ├── parser/       # PDF/Word 文本+要素抽取
│   │   │   ├── rag/          # 向量检索 (pgvector)
│   │   │   ├── audit/        # 合规审查、风险分级、可解释结论
│   │   │   └── report/       # Excel 台账 / 看板数据
│   │   ├── llm/         # 统一 LLM Adapter（可切私有化模型/OpenClaw）
│   │   ├── db/          # 数据库会话、初始化
│   │   ├── tasks/       # Celery 异步任务（批量审查）
│   │   └── utils/       # 通用工具
│   ├── alembic/      # 数据库迁移
│   └── tests/
├── frontend/         # Vue3 + TypeScript + Element Plus + Vite
│   └── src/
│       ├── router/      # 路由
│       ├── stores/      # Pinia 状态
│       ├── api/         # 后端接口封装
│       ├── views/       # 页面
│       └── components/  # 组件
├── docs/             # 设计文档
├── storage/          # 合同文件私有化存储（gitignore）
└── docker-compose.yml
```

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + ECharts(≥6.1) + Pinia |
| 后端 | Python 3.11 + FastAPI |
| 数据库 | PostgreSQL 16 |
| 向量库 | pgvector（统一一套，不用 Chroma） |
| 异步任务 | Celery + Redis |
| 文档解析 | pdfplumber / pypdf / python-docx |
| 报表 | openpyxl |
| AI 模型 | 统一 LLM Adapter（私有化 Qwen/DeepSeek / OpenClaw） |
| 权限 | JWT + RBAC + 审计日志 |
| 部署 | Docker Compose |

## 本地启动

```bash
# 1. 起基础设施（PostgreSQL + pgvector + Redis）
docker compose up -d db redis

# 2. 后端
cd backend
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env        # 按需修改
uvicorn app.main:app --reload

# 3. 前端
cd frontend
npm install
npm run dev
```

## 当前状态

**架构骨架阶段**：目录结构、配置、可运行占位已就位，业务逻辑待实现（均为 `NotImplementedError` 占位）。
依赖已完成安全审计并安装，前后端 **0 已知漏洞**（审计结论见项目根 `../CLAUDE.md` 安全禁用清单）。前后端均已实测可启动：后端 `/health`、`/docs` 正常，前端首页与 TS 类型检查通过。
