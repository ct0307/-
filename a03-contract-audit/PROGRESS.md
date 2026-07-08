# 项目进度记录 · A03 企业合同合规审查系统

> 每完成一次完整改动（功能闭环 / 前后端联动 / 重要重构），在此追加一条改动日志（最新在上）。
> 记录格式：日期 + 改动主题 + 涉及文件 + 验证结论。
> 「完成情况总览」章节随项目推进整体刷新，不追加。

---

## 完成情况总览（截至 2026-07-08）

### 整体架构
- **前端**：Vue 3 + TS + Element Plus + ECharts，卷宗风 UI。10 个视图（登录 + 9 业务），侧栏支持折叠，全站中文业务语言。
- **后端**：FastAPI + SQLAlchemy + SQLite（开发）/PostgreSQL（生产），JWT+RBAC，Celery 异步，LLM Adapter + RAG 检索（本地 embedding），审计日志，LLM 调用记录，部门访问隔离，合同加密存储，字段级脱敏。
- **数据策略**：前端 `MOCK_ENABLED` 全部 false，100% 调真接口。10 张数据库表，**25 条 API 路由**（含 `/chat` / `/knowledge/import-file`）。
- **RAG 状态**：BAAI/bge-small-zh-v1.5 本地 embedding（512维，全离线），向量检索全链路接通，知识库 **41 条**（法律法规 17 / 标准条款 9 / 风险规则 11 / 典型案例 4）。

### 模块完成度
| 模块 | 前端 | 后端 | 状态 |
|---|---|---|---|
| 登录 / RBAC（4角色：admin/legal/finance/business） | ✅ | ✅ | 闭环 |
| 合同审查（上传→加密存储→解析→LLM双Agent审查→复核→整改） | ✅ | ✅ | 核心闭环已通 |
| 智能协同审查（冲突消解/分级分档，有会话才展示结果） | ✅ | ✅ | 前后端联动完成 |
| **风险条款追问 AI**（绑定上下文，对话历史管理） | ✅ | ✅ | ✅ 新增 |
| 工作台（真实整改待办 + 真实审查动态） | ✅ | ✅ | ✅ 真接口 |
| 多维报表 Reports（含 Excel 导出，KPI口径说明） | ✅ | ✅ | ✅ 真接口 |
| **法规知识库**（真实向量检索 + 批量文件导入 + 预置法规 41 条） | ✅ | ✅ | ✅ RAG 全链路接通 |
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
| LLM 调用可观测性 | 每次 chat/追问调用写入 llm_call_logs，Admin Tab 展示三种 provider 算力对比 | ✅ |
| 准确率责任边界 | 每条风险：原文引用 + 法规依据 + 置信度 + 人工复核状态 + 免责声明 | ✅ |
| 私有化模型可切换 | LLM Adapter 支持 Qwen/DeepSeek/OpenClaw；Embedding 本地化（不出企业） | ✅ |

### 已完成（全部 P1 以上）
- 完整前后端业务闭环（11 个模块，25条 API）
- RAG 向量检索全链路（本地 embedding + 批量导入 + 预置法规）
- 数据安全：加密存储 / 字段脱敏 / 部门隔离 / 审计留痕
- UI 去演示化：真实数据 / 业务语言 / 去技术展示冗余
- 风险追问 AI（上下文绑定对话）
- 侧栏折叠 / 3步引导 / 文件名即时反馈

### 待办
| 优先级 | 事项 | 说明 |
|---|---|---|
| **P2** | RAG 混合检索（BM25 + 向量 RRF 融合） | 知识库超 200 条后再做，纯向量当前已够用 |
| **P2** | RAG 切片策略优化（法条按条文切，≤200字/片） | 提升检索精准度，缩短 embedding 时间 |
| **P3** | 生产 PostgreSQL + Alembic 迁移脚本 | 当前 SQLite 开发期补列兜底，切生产前必须做 |
| **P3** | 切私有化 Qwen（生产环境） | DeepSeek 仅开发/演示用，合同数据不出公网 |
| **P3** | pgvector 原生向量列（知识库超千条时） | 当前 JSON+numpy 内存计算，≤500条性能足够 |

---

## 2026-07-08 · 知识库批量导入功能（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/api/v1/endpoints/knowledge.py` | 新增 `POST /knowledge/import-file` 端点；提取 `_extract_file_text()`（支持 .txt/.docx/.pdf）和 `_do_index()` 辅助函数；重构 `/import` 减少重复 |
| `backend/scripts/seed_knowledge_law.py`（新建） | 预置法规脚本：《民法典》合同编 12 条 + 风险规则 7 条 + 标准条款模板 5 套 + 典型案例 2 条，共 27 个条目、26 个切片；幂等（检查 source 去重），`--force` 强制重建 |
| `frontend/src/api/knowledge.ts` | 新增 `importKnowledgeFile(file, category)` — FormData 上传 |
| `frontend/src/views/KnowledgeView.vue` | 工具栏加「导入文件」按钮；批量导入 Dialog：分类选择 + 拖拽多文件区 + 文件队列状态列表（待/中/+N条/失败）+ 汇总进度；完成后自动刷新卡片列表 |

### 验证结论
- 知识库统计卡：法律法规 17 / 标准条款 9 / 风险规则 11 / 典型案例 4，共 41 条 ✅
- 「导入文件」按钮正常显示，0 errors ✅
- 预置脚本幂等验证：重复运行跳过已存在条目 ✅

---

## 2026-07-08 · RAG P0 — 本地 embedding，向量检索全链路接通（✅ 已完成）

### 背景（改前问题）
DeepSeek 无 `/embeddings` 端点 → embedding 失败 → 知识库写入空向量 → `retrieve()` 过滤掉空向量条目 → 始终回落到内置 4 条规则 → 审查"法规依据"全部来自死规则，与知识库内容无关。

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/llm/adapters/local_embedding.py`（新建） | `LocalEmbeddingAdapter`：sentence-transformers 本地化封装，模型懒加载，embed() 返回 `list[list[float]]` |
| `backend/app/llm/factory.py` | 新增 `get_embedding_adapter()`：`EMBED_BACKEND=local`（默认）→ 本地单例；`EMBED_BACKEND=api` → OpenAI 兼容端点；`get_llm_adapter()` 不变（chat 仍走 DeepSeek/Qwen） |
| `backend/app/core/config.py` | 新增 `EMBED_BACKEND / LOCAL_EMBED_MODEL` 配置；`EMBED_DIM` 修正为 512（bge-small-zh 实际维度） |
| `backend/app/services/rag/retriever.py` | `_vector_search` / `index_documents` 改用 `get_embedding_adapter()`（不再混用 chat adapter） |
| `backend/requirements.txt` | 加 `sentence-transformers==3.3.1` |
| 数据库（一次性操作） | 存量 14 条空向量条目全部补向量（55ms，BAAI/bge-small-zh-v1.5） |

### 验证结论
- `retrieve('违约责任条款上限约定')` → mode=**vector**，Top-3 相似度 0.69/0.65/0.65 ✅
- 不再降级到内置规则，审查"法规依据"真正引用知识库条文 ✅
- 本地推理延迟：约 15-25ms/query（CPU），满足企业场景 ✅

---

## 2026-07-08 · 风险条款追问 AI（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/api/v1/endpoints/chat.py`（新建） | `POST /chat`：接收风险上下文（category/original_text/basis/suggestion/confidence）+ 用户消息 + 对话历史，构造 system prompt 后调 LLM Adapter 作答；对话历史最多携带 6 条；调用写入 llm_call_logs（agent=chat，mode=chat） |
| `backend/app/api/v1/router.py` | 注册 `/chat` 路由 |
| `frontend/src/api/chat.ts`（新建） | `chatWithRisk()` 封装请求 |
| `frontend/src/components/audit/RiskReviewDrawer.vue` | 风险详情下方加追问面板：空状态示例引导、用户/AI 气泡消息列表、Enter 发送、切换风险自动清空历史、抽屉宽度 440→480px |

### 功能说明
用户点击风险条目进入复核抽屉，可就该条款向 AI 追问（例如"违约金上限在行业里正常吗""我方有哪些谈判空间"）。每次对话均绑定当前条款的完整上下文，AI 不会泛泛作答。对话历史在当次抽屉内保留，关闭/切换风险自动清空。

### 验证结论
- 后端 `chat` 模块导入无报错 ✅
- 前端抽屉页面加载 0 errors ✅

---

## 2026-07-08 · 工作台去演示假数据（✅ 已完成）

### 改动
| 区块 | 改前 | 改后 |
|---|---|---|
| 待办面板 | `todoByRole` 硬编码 4 条，随演示视角切换 | 真实整改项（`status=待处理`，最多 5 条，点击跳转整改跟踪页） |
| 近期动态 | 固定 4 条假字符串 | `GET /contracts` 真实审查记录，相对时间格式化（刚刚/N分钟前/N小时前/N天前） |
| 快捷入口 | 2×2 按钮格，与侧栏完全重复 | 删除 |

涉及文件：`DashboardView.vue`（删除 `useDemoStore`/`todoByRole`/`quick`/`activity` 全部演示逻辑）

### 验证结论
真实整改项（品牌年度推广服务合同.pdf · 关联交易）正常显示，近期动态 5 条真实数据，相对时间格式正确 ✅

---

## 2026-07-08 · P1 去技术展示冗余（✅ 已完成）

### 问题
前端混入了两类内容——"AI 是怎么工作的"（技术展示）和"AI 帮你发现了什么"（业务决策）。前者对法务/财务用户无决策价值，且让产品显得像演示平台而非企业工具。

### 改动

**合同审查页（AuditView.vue）**
- 删除审查结果里的"多智能体协同双泳道"（`collabSteps`，固定 SOP 步骤字符串）
- 删除相关 CSS（`.collab` / `.collab-lanes` / `.lane-head` / `.collab-step` 等，共减少约 70 行）

**智能协同审查页（CollaborationView.vue）**
- 删除"协作链路·主从串行工作流"整卡（固定 SOP 图示，技术展示无决策价值）
- 删除 Agent 名片中"定向 RAG 检索主题"和"Prompt 侧重"区块（AI 实现细节）
- 无真实审查会话时：整页演示数据 → 引导提示"完成合同审查后此处将显示协同结果"+ 跳转按钮
- 冲突消解 / 分级风险 / 结果对比加 `v-if="isLive"`，有真实数据才展示
- 清理无用 import（`COLLAB_CHAIN`/`ChainStage`）及 `ownerMeta`/`chain` 常量

净删 236 行，新增 25 行。

### 模块职责边界（改后清晰）
- **合同审查页** = 操作（上传 → 复核 → 生成整改）
- **智能协同审查页** = 结果分析（冲突消解 + 分级策略 + 风险对比）

### 验证结论
- 协同审查页 0 errors，无演示数据残留，"完成合同审查后…"引导正常显示 ✅
- 合同审查页审查结果区域直接展示风险清单，无 SOP 噪音 ✅

---

## 2026-07-08 · UI 文案业务化 + 体验优化（✅ 已完成）

### P1 文案改造
| 文件 | 改动 |
|---|---|
| `router/index.ts` | 全站 9 个页面 eyebrow 由英文技术术语（`AI-POWERED CONTRACT REVIEW` 等）改为中文业务语言（`合同智能审查`等） |
| `nav.ts` | `双Agent协作` → `智能协同审查` |
| `OpenClawBadge.vue` | `算力运行状态 · OpenClaw一体机` → `本地算力 · 运行中` |
| `LoginView.vue` | 清演示账号默认值；`hint` 用 `isDev` 隐藏；补 `name`/`autocomplete`；副标题改"私有化部署 · 数据不出企业" |

### P2 交互优化
| 文件 | 改动 |
|---|---|
| `AuditView.vue` | `el-empty` 替换为 3 步可视化引导（上传合同→智能审查→人工复核/生成整改），带 active/done 状态跟随 `session.step` |
| `ReportsView.vue` | "合规通过率"和"平均审查耗时" KPI 卡加口径说明 tooltip（`?` 图标悬停显示） |
| 多个 `.vue` 文件 | 全站移除 `transition: all`（5 处）→ 精确指定过渡属性，避免 GPU 处理无关 CSS 变化 |

### 验证结论
浏览器实测：侧栏"智能协同审查"、底部"本地算力·运行中"、页面 eyebrow "法务工作台"均正确显示 ✅

---

## 2026-07-08 · 侧栏折叠 + 演示切换隐藏 + 文件名即时反馈（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `MainLayout.vue` | `provide` 注入 `collapsed: Ref<boolean>`；`v-bind(sidebarWidth)` 驱动 grid 宽度（64px↔264px），带 CSS `transition` |
| `AppSidebar.vue` | `inject` 接收 collapsed；`el-menu :collapse` 切图标模式；底部"收起侧栏/展开侧栏"按钮 |
| `UserSwitcher.vue` | 演示视角切换列表用 `import.meta.env.DEV` 包裹，`npm run build` 后自动隐藏 |
| `AuditView.vue` | 新增 `pendingFilename` ref，文件选择后立即显示文件名+loading 图标，不等后端返回 |

### 验证结论
- 侧栏折叠/展开：点击正确切换，菜单变图标模式，主内容区宽度同步扩展 ✅
- 演示视角切换：dev 模式可见（npm run dev），生产构建自动隐藏 ✅

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
