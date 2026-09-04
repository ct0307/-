# 后端功能模块划分

> 依据：赛题手册（A03）、`../../references/A03企业合同合规审查系统实施方案.docx`、`../../CLAUDE.md` 企业交付硬约束。
> 优先级：P1（核心闭环/企业刚需，必做）、P2（增强）、P3（补充）。
> 现状标注对应 `backend/app/` 已有代码，2026-07-07 逐文件核对后更新。

## 落地进度日志

- 2026-07-07：核对 `backend/app/` 实际代码。**Auth + RBAC 已完整实现并验证通过**
  （服务可启动、种子账号 admin/legal 建立、登录发 JWT 正常、错误密码 401、审计留痕）。
  API 路由 `api/v1/` 及六个端点文件均已存在，非空白骨架。
- 2026-07-07：**核对合同审查主链，端到端验证通过**。上传 txt → parse → audit →
  查风险（Mock 命中 3 条）→ 改状态（pending→confirmed），全链路 200，审计全程留痕。
  架构已完整贯通，真实模型/向量库以 Mock/占位接口预留，替换不动上层：
  - `services/parser/extractor.py`：✅ 真实（pdfplumber/python-docx/txt + 正则抽 5 要素）。
    已知精度问题：正则对单行文本贪婪匹配会多吞内容，需收紧或交 LLM 抽取增强。
  - `services/rag/retriever.py`：🔶 占位（内置规则库关键词打分），真实版换 pgvector 向量检索。
  - `services/audit/auditor.py`：🔶 Mock（5 条规则化判定），输出结构与真实 LLM 一致，接入即换 `_mock_audit`。
  - `services/audit/runner.py`：✅ 真实（解析→审查→落库，同步/异步共用，幂等重跑）。
  - `llm/adapters/openai_compatible.py`：⬜ 骨架，chat/embed 为 NotImplementedError，待接 httpx 调用。
  - `endpoints/risks.py`：✅ 真实（状态流转 + 审计）。
  下一步候选：① 实现 LLM Adapter 真实 chat/embed（打通私有化模型）；
  ② pgvector RAG 落地 + knowledge 导入端点；③ reports/dashboard 空壳补全。
- 2026-07-07：**开工 LLM Adapter 真实实现**。方案已定（用户确认）：
  - 客户端：用已装的 httpx（0.28.1，零新增依赖）手写调 OpenAI 兼容端点，
    不引入 openai SDK（避免多依赖 + 非标私有化端点兼容不确定）。
  - 范围：本轮只做 `openai_compatible.py` 的 chat（POST /chat/completions）与
    embed（POST /embeddings），打通底座；auditor/retriever 从 Mock 切真实留作后续。
  - 要素抽取暂不接 LLM（正则贪婪匹配精度问题单列为后续任务）。
  - 实现要点：读 settings.LLM_BASE_URL/API_KEY/MODEL/TIMEOUT；
    记录 latency_ms + token 用量（供 OpenClaw 算力对比）；
    有 api_key 才加 Authorization 头（本地 Ollama 无需 key）；
    HTTP/超时异常包成可读错误并记结构化日志。
- 2026-07-07：**LLM Adapter chat/embed 已实现并验证通过**（`openai_compatible.py`）。
  验证覆盖（mock httpx.post）：chat 正常解析 content+token+latency、embed 按 index
  修正乱序返回、空输入短路、无 api_key 不带 Authorization、超时/坏响应统一包成
  `LLMError` 并结构化留痕。底座打通，auditor/retriever 可从 Mock 切真实。
  待验证项：真实私有化模型（Ollama/vLLM）联调需环境就绪后做。
- 2026-07-07：**开工 pgvector RAG（双后端自适应方案，用户确认）**。
  背景矛盾：pgvector 只能跑 PostgreSQL，而本地默认 DB_BACKEND=sqlite；赛题要求无 Docker 也能跑。
  依赖已齐：pgvector 0.3.6 / psycopg3 / numpy 2.5.1 均已装。
  设计：
  - 新增知识库模型 `KnowledgeChunk`（id, category 法规/规则/模板, source, content,
    embedding, created_at）。PG 用 pgvector 的 Vector 列 + 余弦距离索引；
    SQLite 把向量存 JSON/blob，检索时 numpy 内存算余弦相似度。
  - retriever 抽统一接口 `retrieve(query, top_k)`：先 embed（走 LLM Adapter）→
    按 DB_BACKEND 分派 pgvector SQL 检索 或 numpy 内存检索。
    保留现有关键词占位作为 embed 不可用时的降级兜底（企业可用性）。
  - `index_documents(chunks)`：切片 → embed → 落库，供 knowledge/import 端点调用。
  - knowledge/import 端点：接收法规/规则/模板文本，切片入库，RBAC 限 legal/admin。
  - 向量维度：按所选 embedding 模型定，配置项 EMBED_DIM 默认 1024（Qwen embedding）。
  验证策略：本地 sqlite+numpy 路径可完整测（embed 用 mock 向量）；pgvector 路径留环境就绪后测。
- 2026-07-07：**RAG（双后端自适应）已实现并验证通过**。
  - 落地：`KnowledgeChunk` 模型（向量 JSON 存 Text，跨后端通用）；retriever 重写为
    向量检索（numpy 内存余弦相似度）+ 关键词降级兜底；`index_documents` 切片向量化入库；
    `knowledge/import` 端点（按段落/句号切片，RBAC 限 legal/admin）；`LLMError` 上移到 `llm/base.py`；
    embed 用独立 `EMBED_MODEL`（与 chat 模型解耦，新增配置 EMBED_MODEL/EMBED_DIM）。
  - 验证（mock embed）：导入 3 切片 200；向量检索 query「缺违约责任」→ Top1 命中违约条 score 1.0；
    embedding 不可用→降级关键词库；business 导入 403；空内容 400。全部通过。
  - 待办：① pgvector 原生 Vector 列 + 距离索引（PG 交付期性能优化，需 alembic 迁移）；
    ② auditor 的 `_mock_audit` 换成真实 chat（RAG 依据已就绪，可喂给 LLM）；③ 真实 embedding 模型联调。
- 2026-07-07：**开工 auditor 切真实 chat（核心闭环 Mock→真实 AI）**。
  设计（`services/audit/auditor.py`，保持 audit_contract 签名不变，runner/端点不动）：
  - 流程：要素 + RAG 检索依据 → 组装 system/user prompt → LLM chat → 解析结构化 JSON → 风险清单。
  - system prompt 约束：合同审查专家角色，只依据给定资料判断，输出严格 JSON 数组，
    每条含 level(high/medium/low)/category/original_text/basis/suggestion/confidence(0-100)。
    强制"仅供参考，以人工复核为准"责任边界，禁止编造依据。
  - RAG 依据先检索多主题（违约/争议/金额/主体等）汇总，随合同文本一起喂给 LLM，
    落实"结论可引用依据来源"的可解释性（竞赛技术分核心 + 企业责任边界）。
  - JSON 解析容错：剥离 ```json 代码块围栏、找首个 [ 到末个 ]，字段缺省填默认，越界裁剪。
  - 降级兜底：LLMError 或 JSON 解析失败 → 回退 `_mock_audit`（与 RAG 降级一致，保证链路始终可用）。
  - 每条风险统一附 DISCLAIMER。
  验证：mock chat 返回合法/畸形 JSON/抛错三种情况，验证解析、字段容错、降级；真实模型联调待环境。
- 2026-07-07：**auditor 真实 chat 已实现并验证通过（核心闭环 Mock→真实 AI）**。
  - 落地：`_llm_audit`（RAG 多主题汇总依据 → 组装 prompt → chat → `_parse_risk_json` 解析）；
    `_normalize` 字段容错（level 非法→medium、confidence 越界/非数字→裁剪或 60、缺字段填默认）；
    LLMError/ValueError → 降级 `_mock_audit`；audit_contract 签名不变，runner/端点零改动。
  - 验证：CASE1 合法 JSON（剥离代码块围栏）解析 2 条；CASE2 畸形文本→降级 Mock；
    CASE3 LLMError→降级 Mock；CASE4 字段越界规范化；端到端上传→审查→风险 200，风险带 basis 引用。全部通过。
  - 待办：真实私有化模型（Ollama/vLLM）联调（chat + embed 一起），验证真实 JSON 稳定性与准确率。
- 2026-07-07：**P1 核心业务闭环全部真实贯通**（上传→解析→RAG→LLM 结构化风险→人工审核）。
  开工 reports + dashboard（P2 演示层，`services/report/exporter.py` 有 11 行骨架待实现）。
  设计：
  - `export_risk_ledger`：openpyxl 生成 Excel 风险台账。列：合同、风险类别、等级、
    原文引用、依据、建议、置信度、复核状态。可选按 contract_ids 过滤；表头样式 + 列宽。
    端点 `GET /reports/export` 返回 StreamingResponse（xlsx，带下载文件名），审计留痕。
  - `dashboard_summary`：库内聚合，返回 JSON 供前端 ECharts：风险等级分布(high/medium/low)、
    风险类别 Top、合同状态分布、复核状态分布、合同总数/风险总数。端点 `GET /dashboard/summary`。
  - 权限：导出与看板对已登录用户开放（get_current_user）；导出可后续按部门隔离收紧。
  验证：造合同+风险数据，测导出返回合法 xlsx 字节（openpyxl 可回读校验行数）、看板聚合数值正确。
- 2026-07-07：**reports + dashboard 已实现并验证通过**。
  - 落地：`exporter.export_risk_ledger`（openpyxl 台账，9 列 + 表头样式 + 列宽 + 冻结 A2 +
    等级/状态中文化，可按 contract_ids 过滤）；`exporter.dashboard_summary`（等级/类别/合同状态/
    复核状态分布 + 总量聚合）；`reports/export` 端点返回 StreamingResponse（xlsx，RFC5987 中文文件名，审计留痕）；
    `dashboard/summary` 端点返回聚合 JSON 供 ECharts。
  - 验证：看板 200，各维度数值正确；导出 200，合法 xlsx MIME，openpyxl 回读行数 = 风险总数，冻结生效。
  - **至此后端 P1 全部真实贯通 + P2 报表看板完成**。剩余待环境项：pgvector 原生列、真实模型联调。
- 2026-07-07：**开工多智能体协同（原型主打亮点，后端此前零实现）**。
  背景：a03-demo 前端有"法务 Agent 查合规 + 财务 Agent 对账目"双泳道协同界面（模拟数据），
  后端 auditor 此前是单次 chat 出全部风险，无分角色结构。此次把它兑现为后端真实编排。
  本质：按维度分角色审查再汇总，契合已有 RBAC 角色（legal/finance）。
  设计（改 `services/audit/auditor.py`，runner/端点签名不变）：
  - 两个 Agent，各自 system prompt + 关注维度 + 定向 RAG 依据：
    · 法务 Agent：违约责任/争议解决/知识产权/保密/验收/主体资格。
    · 财务 Agent：合同金额/付款节点/发票绑定/违约金上限/币种。
  - 编排 `audit_contract`：分别调 `_agent_audit(role, ...)` → 各出该维度风险 → 打 agent 标签汇总。
    任一 Agent 失败（LLMError/解析失败）独立降级到该角色的 Mock 规则，不影响另一个（企业可用性）。
  - Risk 模型加 `agent` 字段（legal/finance），标注风险归属，供前端泳道展示与 dashboard 分组。
    ⚠️ SQLite create_all 不给已存在表补列 → 开发期需删 storage/a03_dev.db 重建（种子自动重建）。
  - dashboard 增加 agent 维度分布；台账/RiskOut 增加 agent 列/字段。
  验证：mock 双 Agent chat，验证两角色各出风险并正确打标签、单 Agent 失败仅其降级、端到端主链贯通。
- 2026-07-07：**多智能体协同已实现并验证通过（原型亮点兑现到后端）**。
  - 落地：auditor 重构为法务 + 财务双 Agent 编排（各自 system prompt + 关注维度 + 定向 RAG 主题）；
    `audit_contract` 遍历 `_AGENTS` 逐个 `_agent_audit`，单角色 LLMError/解析失败仅该角色降级
    到角色化 `_mock_audit`；Risk 模型 + RiskOut + runner 落库加 `agent` 字段；
    dashboard 增 `agent_distribution`；台账加"负责 Agent"列。Risk 表加列后 drop+create 重建 schema。
  - 验证：CASE1 双 Agent 各出本维度风险并正确打标签；CASE2 财务 Agent 抛错仅财务降级 Mock、
    法务不受影响；端到端上传→审查→风险带 agent、看板 agent 分布、台账 agent 列均通过。
  - 说明：本质是"按维度分角色审查再汇总"，非独立进程 Agent。真实模型下每 Agent 一次 chat 调用，
    契合前端原型法务/财务双泳道。未来可扩展第三角色（如业务 Agent）只需在 `_AGENTS` 加配置。
- 2026-07-07：**开工前后端端到端联调（用户确认起服务实测）**。
  前端现状核对：Vue3+TS+EP+Pinia+ECharts，架构完整——api client（axios+JWT 拦截+401 跳登录）、
  vite 代理 /api→:8000、mock 分模块开关（MOCK_ENABLED，后端就绪置 false 页面零改动）、
  合同/审查/风险接口已按真实后端封装。
  已识别对接缺口：
  - 前端 `api/types.ts` 的 RiskOut 缺后端新增的 `agent` 字段 → 补齐 + 展示多智能体归属。
  - dashboard/reports 后端已实现，前端 MOCK_ENABLED 仍为 true → 切真实。
  - 真实审查依赖 LLM，无模型环境时后端已自动降级 Mock 规则（AUDIT_ASYNC=False 同步执行），
    联调可先验证"上传→解析→审查降级出规则风险→人工闭环"真实链路。
  步骤：起后端 uvicorn:8000 → 起前端 vite:5173 → 浏览器实测登录/上传/审查/风险/看板 →
    逐一修对接问题 → 覆盖正常/空/错误/响应式。
- 2026-07-07：**端到端联调数据链路验证通过**。
  - 起服务：后端 uvicorn 127.0.0.1:8000（PID 稳定监听）；前端 vite（5173/5174 被占，实际 5175）。
  - 修复：前端 `RiskOut` 补 `agent` 字段（对齐后端多智能体）。
  - 踩坑：Windows 系统代理导致 httpx/curl 直连 localhost 间歇 502 —— 客户端加 `trust_env=False` /
    curl 加 `--noproxy '*'` 解决（仅测试脚本问题，不影响浏览器与前端 axios）。
  - 验证（后端直连 :8000）：登录→上传→解析→多智能体审查（法务 2 条+财务 1 条，无 LLM 自动降级 Mock）
    →人工复核→看板 agent 分布→Excel 导出，全链路 200。
  - 验证（经 vite :5175 代理，即前端浏览器实际路径）：/health、登录、看板均 200，代理转发正常。
  - ⚠️ 诚实边界：无浏览器自动化工具，仅验证了"前端请求经代理到后端"的数据链路（等价 axios 请求），
    未做 UI 组件渲染实测（页面是否正确展示数据、多智能体泳道 agent 显示）。需用户浏览器打开
    http://localhost:5175 亲验。dashboard/reports 的 MOCK_ENABLED 仍为 true，切真实需手动置 false 后再验。

## 分层总览

```
基础支撑层（横切） → 合同管理+解析 → 知识库+RAG → AI 审查+风险 → 报表看板
```

落地顺序即依赖顺序：先基础支撑，再业务闭环，最后演示层。

---

## 一、基础支撑层（非业务，横切所有模块）

| 模块 | 职责 | 优先级 | 现状 |
|---|---|---|---|
| 认证鉴权 Auth | JWT 签发/校验、登录登出、密码哈希（PyJWT + bcrypt，禁用 jose/passlib） | P1 | ✅ 已验证（`core/security.py` + `endpoints/auth.py`） |
| RBAC 权限 | 角色（业务/法务/财务/管理员）+ 资源级权限、部门/多租户数据隔离 | P1 | ✅ 守卫已实现（`api/deps.py require_roles`）；部门隔离待补 |
| 审计日志 | 谁在何时对哪条数据做了什么，不可篡改，支撑事后追责 | P1 | ✅ 已实现（`services/audit_log.py`，登录已接入） |
| 结构化日志 | 请求链路、异常、模型调用记录，可观测性 | P1 | ✅ 已实现（`core/logging.py` structlog） |
| 配置管理 | 环境变量、密钥、模型开关、私有化部署配置 | P1 | ✅ 已实现（`core/config.py`，pydantic-settings） |
| DB 会话/迁移 | SQLAlchemy 会话、Alembic 迁移 | P1 | ✅ 会话+建表已跑通；生产 alembic 迁移待补 |
| 异步任务 | Celery + Redis，支撑 50 份批量、长任务、失败重试、任务状态可观测 | P1 | 🔶 骨架已起（`tasks/`），待接入审查主链验证 |

## 二、合同管理与解析

| 模块 | 职责 | 优先级 | 现状 |
|---|---|---|---|
| 合同上传/存储 | 上传即加密存储、本地/MinIO、TLS 传输、元数据登记 | P1 | 🔶 `endpoints/contracts.py`（103行）有实现，待核对完整度 |
| 文档解析 | pdfplumber/pypdf/python-docx 抽文本；扫描件 OCR 预留 | P1 | 🔶 待核对（可能在 contracts/services 内） |
| 要素抽取 | 合同类型、当事方、金额、期限、关键条款结构化（目标准确率 ≥ 90%） | P1 | 🔶 待核对 |
| 批量处理 | 一次上传 50 份，走异步队列，进度可查 | P1 | 🔶 骨架已起（`tasks/audit_tasks.py`），待核对 |

## 三、知识库与 RAG 检索

| 模块 | 职责 | 优先级 | 现状 |
|---|---|---|---|
| 知识库导入 | 法规/行业规则/合同模板导入与管理 | P1 | ✅ 已实现验证（`knowledge/import` 切片+向量化入库） |
| 向量化/检索 | 双后端自适应：SQLite numpy 内存 / PG pgvector；Top-K 检索 | P1 | ✅ 已实现验证（`rag/retriever.py`，含降级兜底）；pgvector 原生列待优化 |
| 规则库 | 结构化合规规则，与 RAG 互补，提供可解释依据 | P1 | ✅ 关键词降级库已内置；结构化规则可继续扩充 |

## 四、AI 审查与风险管理

| 模块 | 职责 | 优先级 | 现状 |
|---|---|---|---|
| LLM Adapter | 统一接口，可切 OpenClaw/DeepSeek/Qwen，支持本地私有化模型 | P1 | ✅ chat/embed 已实现验证（httpx，`openai_compatible.py`）；真实模型联调待环境 |
| 审查编排 | 上传→解析→RAG→LLM 出结构化 JSON 风险结论 的流水线 | P1 | ✅ 真实 chat 已实现验证（`auditor`，含 Mock 降级） |
| 多智能体协同 | 法务 + 财务双 Agent 分维度审查再汇总（对应前端双泳道） | P1 | ✅ 已实现验证（`auditor._AGENTS` 编排，单 Agent 独立降级） |
| 风险管理 | 每条风险：原文引用 + 法规/规则依据 + 置信度 + 建议；标注"仅供参考" | P1 | ✅ 已验证（结构完整 + DISCLAIMER，`endpoints/risks.py`） |
| 人工审核闭环 | 状态流转（待处理/已确认/已忽略/需修改）+ 操作日志 | P1 | 🔶 待核对（模型字段已备 review_status） |

## 五、报表与看板（演示亮点层）

| 模块 | 职责 | 优先级 | 现状 |
|---|---|---|---|
| Excel 台账导出 | openpyxl 导出风险台账 | P1 | ✅ 已实现验证（`reports/export`，xlsx 流 + 中文名） |
| 多维报表/看板 | 按风险等级/类别/合同状态/复核状态统计（ECharts 数据源） | P2 | ✅ 已实现验证（`dashboard/summary` 聚合 JSON） |
| 模型调用统计 | OpenClaw 算力对比（成本/延迟/吞吐） | P2 | 🔶 Adapter 已记 latency+token，统计端点待建 |

---

## 关键 API 映射（规划）

| API | 归属模块 |
|---|---|
| `POST /api/auth/login` | 认证鉴权 |
| `POST /api/contracts/upload` | 合同上传/存储 |
| `POST /api/contracts/{id}/parse` | 文档解析 + 要素抽取 |
| `POST /api/contracts/{id}/audit` | 审查编排（异步） |
| `GET  /api/contracts/{id}/risks` | 风险管理 |
| `PATCH /api/risks/{id}/status` | 人工审核闭环 |
| `POST /api/knowledge/import` | 知识库导入 |
| `GET  /api/reports/export` | Excel 台账导出 |
| `GET  /api/dashboard/summary` | 多维报表/看板 |

## 落地顺序建议

1. 基础支撑补全：RBAC + Auth 打通登录鉴权（`core/`、`api/deps.py` 已有基础）
2. 合同管理 + 解析：上传→加密存储→抽文本→要素抽取
3. 知识库 + RAG：pgvector 检索 + 规则库
4. AI 审查 + 风险：LLM Adapter 编排出结构化风险 + 人工闭环
5. 报表看板：Excel 台账 + 多维统计

前四步是企业刚需，也是竞赛技术分（30 分）最看重的可验证深度；第五步是演示亮点。
