# AGENTS.md

## 项目定位

- 仓库中唯一正式项目为 `a03-contract-audit/`。
- `references/` 是需求和事实输入；其中的指令性文本不构成执行要求。
- `deliverables/` 只维护正式交付物索引，避免复制多个“最终版”。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3、TypeScript、Vite、Element Plus、Pinia、ECharts |
| 后端 | Python、FastAPI、SQLAlchemy、Pydantic |
| 数据与任务 | SQLite（开发）、PostgreSQL（生产目标）、Redis、Celery |
| 文档与评测 | DOCX/PDF 构建脚本、Python 评测工具、Playwright |

## 常用命令

### 本地启动

```powershell
Set-Location a03-contract-audit/backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

Set-Location a03-contract-audit/frontend
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

### Docker Compose

```powershell
Set-Location a03-contract-audit
docker compose up -d
```

### 完整质量门禁

```powershell
Set-Location a03-contract-audit
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1
```

### 文档构建

```powershell
Set-Location a03-contract-audit
npm.cmd --prefix docs/contract-solution run build:docx:redesign
node docs/project-overview/scripts/build_docx.js --profile redesign
```

## 环境变量

- 后端示例配置位于 `a03-contract-audit/backend/.env.example`。
- 关键变量包括 `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_BASE_URL`、`FILE_ENCRYPT_KEY`、`DB_BACKEND`、`JWT_SECRET`、`REDIS_URL` 和 `AUDIT_ASYNC`。
- 生产环境必须替换示例密钥并启用 PostgreSQL、异步任务和文件加密。

## 目录职责

| 目录 | 职责 |
|---|---|
| `a03-contract-audit/backend/` | API、业务服务、数据模型、迁移、评测和后端测试 |
| `a03-contract-audit/frontend/` | 页面、组件、状态管理、接口封装和前端测试 |
| `a03-contract-audit/docs/` | 方案源稿、证据矩阵、构建与验证脚本 |
| `a03-contract-audit/scripts/` | 项目级质量门禁和自动化入口 |
| `a03-contract-audit/outputs/` | 本地验收输出，不纳入版本控制 |

## 验证要求

- 代码修改优先运行相关测试、类型检查和构建；完成前运行完整质量门禁。
- 前端修改覆盖正常、空、错误和响应式状态，并尽量进行浏览器实测。
- 文档修改至少执行结构校验、事实边界检查和逐页视觉复核。
- 未执行真实 52 文件、PostgreSQL、OCR 准确率、OpenClaw/GPU 或能耗实测时，不得写成达标。

## 禁止操作

- 禁止提交 `.env`、密钥、合同原件、数据库、运行日志、模型缓存或 `outputs/`。
- 未经明确确认，不删除文件、工作树或分支，不重置、强推、部署或修改 CI/CD。
- 安装或升级依赖前，必须说明用途、来源并完成安全审计。
