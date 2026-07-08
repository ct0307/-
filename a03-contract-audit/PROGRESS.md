# 项目进度记录 · A03 企业合同合规审查系统

> 每完成一次完整改动（功能闭环 / 前后端联动 / 重要重构），在此追加一条改动日志（最新在上）。
> 记录格式：日期 + 改动主题 + 涉及文件 + 验证结论。
> 「完成情况总览」章节随项目推进整体刷新，不追加。

---

## 完成情况总览（截至 2026-07-08）

### 整体架构
- **前端**：Vue 3 + TS + Element Plus + ECharts，卷宗风 UI。10 个视图（登录 + 8 业务 + 双Agent协作），侧栏导航齐全。
- **后端**：FastAPI + SQLAlchemy + SQLite（开发）/PostgreSQL（生产），JWT+RBAC，Celery 异步（可切同步），LLM Adapter + RAG 检索，审计日志，LLM 调用记录，部门访问隔离，合同加密存储，字段级脱敏。
- **数据策略**：前端 `MOCK_ENABLED` 全部 false，100% 调真接口。10张数据库表，23条 API 路由。

### 模块完成度
| 模块 | 前端 | 后端 | 状态 |
|---|---|---|---|
| 登录 / RBAC（4角色：admin/legal/finance/business） | ✅ | ✅ | 闭环 |
| 合同审查（上传→加密存储→解析→LLM双Agent审查→复核→整改） | ✅ | ✅ | 核心闭环已通 |
| 双Agent协作（串行协同/冲突消解/分级分档） | ✅ | ✅ | 前后端联动完成 |
| 工作台 Dashboard | ✅ | ✅ | ✅ 真接口 |
| 多维报表 Reports（含 Excel 导出） | ✅ | ✅ | ✅ 真接口 |
| 法规知识库 Knowledge（含添加持久化） | ✅ | ✅ | ✅ 真接口 |
| 整改跟踪 Rectify（含状态流转按钮） | ✅ | ✅ | ✅ 真接口 |
| 审查记录 History（含点击行风险钻取） | ✅ | ✅ | ✅ 真接口 |
| 规则与模板 Rules | ✅ | ✅ | ✅ 真接口 |
| 权限与审计 Admin（3 Tab：矩阵/审计日志/LLM调用记录） | ✅ | ✅ | ✅ 真接口 |

### 企业交付硬约束（全部完成）
| 约束 | 实现方式 | 状态 |
|---|---|---|
| 合同文件加密存储 | Fernet AES-128-CBC+HMAC，密钥注入 `.env`，上传即加密落盘 | ✅ |
| 字段级脱敏 | 响应层按角色分级：business 看提交人首字+**，风险原文截断+[已脱敏] | ✅ |
| 部门访问隔离 | business 角色仅可见本部门合同（WHERE dept 过滤，403 跨部门） | ✅ |
| 审计日志 + IP 追踪 | 全操作留痕，login/upload 等写入真实客户端 IP（X-Forwarded-For 优先） | ✅ |
| LLM 调用可观测性 | 每次 chat 调用写入 llm_call_logs，Admin Tab 展示三种 provider 算力对比 | ✅ |
| 准确率责任边界 | 每条风险：原文引用 + 法规依据 + 置信度 + 人工复核状态 + 免责声明 | ✅ |
| 私有化模型可切换 | LLM Adapter 支持 Qwen/DeepSeek/OpenClaw，当前 DeepSeek（开发用） | ✅ |

### 待办（仅剩 P3）
1. **P3** 生产 PostgreSQL alembic 迁移脚本（当前 SQLite 开发期补列兜底）
2. **P3** 生产切私有化 Qwen（合同数据出公网，DeepSeek 仅开发/演示用）
3. **P3** AuditView 合同文件上传后显示文件名（Vue el-upload input 响应式问题，功能本身通过 curl 验证）

---

## 2026-07-08 · Playwright 全流程浏览器自动化测试（✅ 已完成）

### 测试目标
用 Playwright MCP 驱动浏览器，对全部10个模块做端到端验证，重点覆盖本轮四项断点修复。

### 测试结果

| 模块 | 结果 | 关键验证点 |
|---|---|---|
| 登录 | ✅ | legal/admin 两账号均正常登录，路由守卫有效 |
| 工作台 Dashboard | ✅ | KPI：16份/4整改/43风险/23.3%通过率；DemoBadge 绿色"实时数据" |
| 合同审查 AuditView | ✅ | 上传区/维度开关/步骤流程结构正常（文件上传需真实用户交互，功能已由 curl 验证） |
| 双Agent协作 | ✅ | 法务/财务 Agent 卡片和协作时间线均正常渲染 |
| **整改跟踪 RectifyView** | ✅ | 6条整改项加载，三类流转按钮（开始处理/标记闭环/重新开启）正确；RC006 点"开始处理"实时变为"处理中" |
| **多维报表 ReportsView** | ✅ | 点击"导出台账"→下载 `风险台账_2026-07-08.xlsx`，toast"风险台账已导出" |
| **法规知识库 KnowledgeView** | ✅ | 添加知识弹窗正常，点"入库"→后端持久化→toast"已入库" |
| **审查记录 HistoryView** | ✅ | 点击行打开抽屉，"员工商业保险采购合同"显示1条"理赔条款"风险（等级/原文/依据/建议/复核状态全部展示） |
| 规则与模板 RulesView | ✅ | 6条规则/模板区/新增按钮齐全 |
| 权限与审计 AdminView | ✅ | 3个Tab正常切换；权限矩阵7×4；LLM调用记录14条，OpenClaw/DeepSeek/Qwen三个统计卡 |

### 测试中发现并修复的两个 Bug

| Bug | 根因 | 修复文件 |
|---|---|---|
| ReportsView 整个模块500崩溃 | Edit 操作留下CSS 碎片（孤立的 `align-items: center; margin-bottom: 16px; }`） | `ReportsView.vue` 删除3行无效CSS |
| KnowledgeView 添加知识503失败 | `/knowledge/import` 端点在 embedding 不可用时直接抛503，无降级逻辑 | `knowledge.py` 改为 embedding 失败时写空向量降级（与 seed 脚本一致），RAG 走关键词检索 |

---

## 2026-07-08 · 字段级脱敏（✅ 已完成）

### 规则（响应层按角色分级，不改数据库存储）
| 角色 | 提交人姓名 | 风险原文 |
|---|---|---|
| admin / legal / finance | 完整显示 | 完整显示 |
| business | `曾庆豪 → 曾**` | > 80字时截断 + `…[已脱敏]` |

### 改动
| 文件 | 内容 |
|---|---|
| `app/services/masking.py`（新建） | `mask_name()` / `mask_original_text()` / `apply_history_row_masking()` / `apply_risk_masking()` |
| `app/api/v1/endpoints/contracts.py` | `GET /contracts` submitter 按角色脱敏；`GET /{id}/risks` business 角色 original_text 截断 |
| `app/db/init_db.py` | 补 finance / business 种子账号（4账号：admin/legal/finance/business） |

### 验证结论
- legal 视角：`legal`；business 视角：`l****` ✅
- 长文本（93字）截断 + `…[已脱敏]`；短文本（22字）原样返回 ✅

---

## 2026-07-08 · 合同文件加密存储（✅ 已完成）

### 方案
Fernet（AES-128-CBC + HMAC-SHA256），密钥通过 `.env FILE_ENCRYPT_KEY` 注入。密钥为空时透传明文（向后兼容，开发快速启动）。

### 改动
| 文件 | 内容 |
|---|---|
| `requirements.txt` | 加 `cryptography==44.0.2` |
| `app/core/config.py` | 加 `FILE_ENCRYPT_KEY: str = ""`（空=不加密） |
| `app/core/crypto.py`（新建） | `encrypt_bytes` / `decrypt_bytes` / `is_encryption_enabled`；密钥懒加载，错误不阻断主链路 |
| `app/services/parser/extractor.py` | `_read_decrypted()` 读文件并解密；PDF/DOCX 改用 BytesIO，调用方无感知 |
| `app/api/v1/endpoints/contracts.py` | 上传时调 `encrypt_bytes()` 再落盘；审计日志记录 `encrypted=True/False` |
| `.env` / `.env.example` | 写入演示密钥 + 生成命令说明 |

### 验证结论
- 磁盘文件首字节 `gAA`（Fernet魔数），中文关键词不可读：`plaintext_keywords_found: []` ✅
- 上传→解析全流程：`party_a=测试科技有限公司` 正确提取，解密对调用方透明 ✅

---

## 2026-07-08 · AdminView LLM 调用记录 Tab（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `frontend/src/mock/admin.ts` | 新增 `LlmCallRow` 接口 + 12条演示数据（3种 provider 算力对比） |
| `frontend/src/api/admin.ts` | 新增 `getLlmCalls()`；mock 关时走 `GET /admin/llm-calls` |
| `frontend/src/views/AdminView.vue` | 重构为 `el-tabs` 三栏：权限矩阵 / 审计日志 / LLM调用记录；LLM tab 含三种算力统计卡 + 明细表，延迟色码（OpenClaw绿/Qwen黄/DeepSeek橙） |
| `backend/scripts/seed_demo.py` | 新增 14条 LLM 调用演示数据（OpenClaw 4 / Qwen 4 / DeepSeek 6） |

### 验证结论
- `GET /admin/llm-calls`：14条 ✅
- 算力对比：**OpenClaw avg 1,452ms**，Qwen avg 4,155ms，DeepSeek avg 6,693ms ✅（演示效果显著）

---

## 2026-07-08 · PM 评估驱动的四项演示断点修复（✅ 已完成）

### 背景
PM 视角全量评估（代码扫描10个视图）发现4个 P1/P2 演示断点：整改无法流转、Excel 导出缺失、知识库入库不持久化、历史记录无法钻取。

### 修复清单
| # | 模块 | 问题 | 修复方式 |
|---|---|---|---|
| 1 | RectifyView | 整改项只读，无状态流转 | 每卡片加流转按钮（开始处理/标记闭环/重新开启），调 `PATCH /rectifications/{id}`，`changing: Set<string>` 防重复提交 |
| 2 | ReportsView | 无 Excel 导出 | `api/reports.ts` 加 `exportRiskLedger()`（arraybuffer→Blob 下载）；工具栏加"导出台账"按钮，接 `GET /reports/export` |
| 3 | KnowledgeView | 添加知识仅前端，刷新消失 | `api/knowledge.ts` 加 `importKnowledge()`，`submitAdd()` 改 async 调真接口，类别名映射（法律法规→law 等） |
| 4 | HistoryView | 点击行无操作 | `@row-click` 触发抽屉，解析合同 ID（C0001→1），拉取 `GET /contracts/{id}/risks`，展示完整风险列表 |

---

## 2026-07-08 · 数据安全隔离 + LLM 可观测性（✅ 已完成）

### 改动摘要
- **部门访问隔离**：`_dept_accessible()` + `_get_contract()` 用 user 参数，parse/audit/risks/history 全覆盖
- **LLM 调用记录**：`LLMCallLog` 模型新建，`_agent_audit()` 每次 chat 成功后写入；`GET /admin/llm-calls` 端点（admin 权限）
- **审计 IP**：`auth.py` login 真实提取客户端 IP，`audit_log.record()` 加可选 `ip` 参数

### 验证结论
- legal 用户查 contracts：全量可见（legal 角色不隔离，符合设计）✅
- business 用户查 contracts：仅本部门（采购中心3条）✅
- admin/access-matrix：7模块×4角色 ✅
- legal 访问 admin/llm-calls → 403（RBAC 守卫正确）✅

---

## 2026-07-08 · 补全四个 mock 模块后端（Rectify/History/Rules/Admin）✅ 已完成

### 新增数据库表（共 10 张）
`users` / `contracts` / `risks` / `knowledge_chunks` / `audit_logs` / `rectifications` / `audit_rules` / `contract_templates` / `access_roles` / `llm_call_logs`

### 新增 API 端点（共 23 条路由）
- `GET/POST/PATCH /rectifications` — 整改跟踪 CRUD
- `GET/POST/DELETE /rules` — 审查规则库
- `GET/POST/DELETE /templates` — 合同模板库
- `GET /admin/access-matrix` — 权限矩阵（对象包裹）
- `GET /admin/audit-logs` — 审计日志（join users）
- `GET /admin/llm-calls` — LLM 调用记录
- `GET /contracts` — 审查历史台账（HistoryRow，聚合风险等级+状态）

### 验证结论（curl + type-check + Playwright）
- type-check 零错误 ✅
- Rectify 6条 / History 15条8字段 / Rules 6条规则+3模板 / Admin 7×4权限矩阵 + 38条审计日志含 ip ✅
- MOCK_ENABLED 全部 false，前端 100% 调真接口 ✅

---

## 2026-07-07 · 修 LLM 502 + Dashboard/Reports/Knowledge 切真接口（✅ 已完成）

### 502 根因与修复
- **根因**：本机无 Ollama + 无 `.env`，默认指向空端点 → 502
- **修复**：新建 `.env` 切 DeepSeek；DeepSeek 无 embedding → seed 知识库写 `embedding=""`，RAG 走关键词降级

### 验证（Playwright 实测）
- 真实 LLM audit 跑通：法务7条+财务8条=15条风险，`mode=llm`（deepseek-chat），触发 X1/X3 双Agent交叉验证 ✅
- Dashboard/Reports/Knowledge 三端点真实数据渲染，DemoBadge 绿色 ✅

---

## 2026-07-07 · 双Agent协作深化（✅ 已完成）

将"双Agent各跑各的"升级为真协同，前后端同步落地：
- 后端：法务先行→共享上下文→财务读取法务输出再审；`detect_conflicts()` 交叉验证；`classify_tier()` 分级
- 前端：新增 CollaborationView（双Agent职责卡/协作链路/分级风险/冲突消解）

---

## 演示账号速查

| 账号 | 密码 | 角色 | 可访问模块 |
|---|---|---|---|
| admin | admin123 | 系统管理员 | 全部（含Rules/Admin） |
| legal | legal123 | 法务主管 | 全部（除Rules/Admin） |
| finance | finance123 | 财务主管 | 全部（除Rules/Admin） |
| business | business123 | 业务人员 | 工作台/合同审查/整改跟踪/报表/知识库/审查记录 |

## 启动命令

```bash
# 后端（backend 目录）
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（frontend 目录）
npm run dev

# 灌演示数据（backend 目录，幂等可重跑）
./.venv/Scripts/python.exe -m scripts.seed_demo
```
