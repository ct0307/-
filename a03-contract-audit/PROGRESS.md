# 项目进度记录 · A03 企业合同合规审查系统

> 每完成一次完整改动（功能闭环 / 前后端联动 / 重要重构），在此追加一条改动日志（最新在上）。
> 记录格式：日期 + 改动主题 + 涉及文件 + 验证结论。
> 「完成情况总览」章节随项目推进整体刷新，不追加。

---

## 完成情况总览（截至 2026-07-07）

### 整体架构
- **前端**：Vue 3 + TS + Element Plus + ECharts，卷宗风 UI。8 个业务视图 + 登录，侧栏导航齐全。
- **后端**：FastAPI + SQLAlchemy + SQLite（开发）/PostgreSQL（生产），JWT+RBAC，Celery 异步（可切同步），LLM Adapter + RAG 检索，审计日志。
- **数据策略**：前端 `MOCK_ENABLED` 总开关，页面只调 `api/*.ts`，后端接口就绪后置 false 即可零改动切换。

### 模块完成度
| 模块 | 前端 | 后端 | 数据来源 | 状态 |
|---|---|---|---|---|
| 登录 / RBAC | ✅ | ✅ | 真接口 | 闭环 |
| 合同审查（上传→解析→审查→复核→整改） | ✅ | ✅ | 真接口 | 核心闭环已通 |
| 双 Agent 协作（串行协同/冲突消解/分级分档） | ✅ | ✅ | 真接口 + mock 降级 | 前后端联动完成 |
| 工作台 Dashboard | ✅ | ✅（dashboard/summary） | 真接口 + seed | ✅ 已切真接口 |
| 多维报表 Reports | ✅ | ✅（summary + 导出） | 真接口 + seed | ✅ 已切真接口 |
| 法规知识库 Knowledge | ✅ | ✅（cards/stats/导入） | 真接口 + seed | ✅ 已切真接口 |
| 规则与模板 Rules | ✅ | ⬜ 无端点 | 纯前端 mock | 后端未做（下一步，方案见下） |
| 审查记录 History | ✅ | ⬜ 无端点 | 纯前端 mock | 后端未做（下一步，可复用 contracts/risks） |
| 权限与审计 Admin | ✅ | 部分（audit_logs 表有，缺 ip 列） | 前端仍挂 mock | 后端未做（下一步） |
| 整改跟踪 Rectify | ✅ | ⬜ 无端点 | 前端 store 本地态 | 后端未做（下一步，价值最高） |

### 关键待办（优先级）
1. ✅ ~~**P1** LLM 502~~ 已修（切 DeepSeek，真实 audit 跑通，见 2026-07-07 条）
2. ✅ ~~**P1** Dashboard/Reports/Knowledge 切真接口~~ 已完成并浏览器实测
3. ✅ ~~**P2** DemoBadge 按页显示数据来源~~ 已完成（改为按 `MOCK_ENABLED` 自动切实时/演示态）
4. **P2** Rules / History / Rectify / Admin 后端端点尚未创建（前端仍纯 mock）—— 下一步主攻
5. **P1** 数据安全硬约束：上传加密存储、字段级脱敏、审计日志增强（CLAUDE.md 第一目标，尚未动）
6. **P3** 生产 PostgreSQL 的 alembic 迁移脚本（当前 SQLite 用开发期补列兜底）
7. **P3** 生产切私有化 Qwen（合同数据出公网与「私有化优先」冲突，DeepSeek 仅开发/演示用）

---

## 2026-07-07 · 【下一步计划·未开工】补全 Rectify/History/Rules/Admin 后端

> ⚠️ 本条是**待办计划**，尚未写任何代码。下次新窗口从这里开始。方向已定：一次补全四个 mock 模块的后端（用户选「补全全部剩余模块」）。
> 前端契约已由 Explore 子代理调研确认（结论见下），后端现有模式已摸清。

### 后端现有模式（照此写新端点）
- 端点：`APIRouter()` + `Depends(get_db)` + `Depends(require_roles("legal","finance"))`（admin 通配），参考 `endpoints/risks.py`。
- 审计留痕：每个写操作调 `from app.services import audit_log; audit_log.record(db, user_id=user.id, action=..., target=..., detail=...)`。
- schema：`app/schemas/contract.py`（Pydantic，`model_config={"from_attributes": True}` 支持 ORM 直转）。
- 路由注册：`app/api/v1/router.py` 加 `api_router.include_router(xxx.router, prefix="/xxx", tags=[...])`。
- 建表：`app/db/init_db.py` `create_all` + SQLite 开发期 `_migrate_dev_columns()` 补列（`_DEV_COLUMNS` 字典加表列即可）；生产走 alembic。
- seed：仿 `backend/scripts/seed_demo.py`（幂等判重哨兵），四模块都要灌演示数据否则切接口后页面空。

### 数据模型改动（`app/models/models.py` 新增表）
| 表 | 字段 | 备注 |
|---|---|---|
| `Rectification` | id, contract(合同名), risk(风险描述), level(**英文** high/medium/low), owner, status(**中文** 待处理/处理中/已闭环), created(YYYY-MM-DD), due(默认+7天), note, risk_id(外键可空) | 对齐前端 `stores/rectify.ts` |
| `AuditRule` | id, name, dimension, level(high/medium/low), agent(法务Agent/财务Agent), desc, builtin(bool) | Rules |
| `ContractTemplate` | id, name, type, clauses(JSON 数组), builtin(bool) | Rules |
| 权限矩阵 | 可用 DB 表 `AccessRole`(key,label,perms JSON) 或直接配置常量 | Admin，**待定：DB 表 or 配置常量** |
| `audit_logs` | **需补 `ip` 列**（现表无 ip）→ 加进 `_DEV_COLUMNS` | Admin |

### 端点清单（前端契约，字段名须精确对齐，返回体形态别改）
**Rectify**（新建 `endpoints/rectifications.py`）
- `GET /rectifications` → `Rectification[]`（裸数组）
- `POST /rectifications` → 入参 `{contract,risk,level,owner,status,created,due,note}` 返回带 id
- `PATCH /rectifications/{id}` → 改 status
- ⚠️ 前端目前是纯 Pinia 本地态（`addFromRisk`/`setStatus`），切接口要改 `stores/rectify.ts` 调 api

**History**（并入现有 `endpoints/contracts.py`）
- `GET /contracts` → `HistoryRow[]`（裸数组，8 字段：id,name,type,submitter,time,level,riskCount,status）
- ⚠️ `level` 是**中文**枚举（高风险/中风险/低风险），`status` 中文（合规/待整改/已整改），`time` 是 `YYYY-MM-DD HH:mm` 字符串。搜索/筛选/分页全在前端本地做。
- api 壳已写好 `client.get('/contracts')`，路径已定。

**Rules**（新建 `endpoints/rules.py`）
- `GET /rules` / `POST /rules`(入参 name,dimension,level,agent,desc；builtin后端置false) / `DELETE /rules/{id}`
- `GET /templates` / `POST /templates`(入参 name,type,clauses[]) / `DELETE /templates/{id}`
- ⚠️ 前端增删目前纯内存态，切接口要在 `api/rules.ts` 补 POST/DELETE 调用（现只有两个 GET 壳，mock 关时 fallback 返回空数组）

**Admin**（新建 `endpoints/admin.py`，prefix `/admin`）
- `GET /admin/access-matrix` → `{modules: string[], roles: AccessRole[]}`（**对象包裹**，非裸数组）
  - `modules` 7 个固定顺序：`['工作台','合同审查','整改跟踪','多维报表','法规知识库','规则与模板','权限与审计']`
  - `roles[].perms[]` 与 modules **等长同序**，值 ∈ `读写/只读/无`（中文）
- `GET /admin/audit-logs` → `AuditLogRow[]`（裸数组，7 字段：id,user,role,action,target,time,ip）join users 出 user/role
- ⚠️ api 壳 mock 关时返回空壳，路径待前端补 `client.get`

### 跨模块坑（子代理确认）
1. **枚举语言不统一**：History level 中文、Rectify/Rules level 英文；History/Rectify status 中文。后端逐模块按现值返回，别统一成英文。
2. **返回体**：History/audit-logs/rules/templates 裸数组；access-matrix 是 `{modules,roles}` 对象。别加 `{data,total,code}` 外层（前端 client 已 unwrap `.data`）。
3. **时间格式**：History/Admin 用 `YYYY-MM-DD HH:mm`，Rectify 用 `YYYY-MM-DD`，均非 ISO。
4. **写操作前端 api 壳未接**：Rules 增删、Rectify 增改要前端补 api 调用，不是翻开关能覆盖。
5. 切接口 = 后端端点 + seed 数据 + 前端 `MOCK_ENABLED` 对应项置 false（+ 写操作补 api 调用）。

### 建议执行顺序（逐模块提交，做一个验一个，别一次全改）
**Rectify → History → Rules → Admin**（Rectify 关联核心审查闭环价值最高；History 复用现有 contracts/risks 表最简单）。每模块完成后 `npm run type-check` + Playwright 浏览器实测再进下一个。

### 待你拍板的设计点
- 权限矩阵用 DB 表还是配置常量？（演示够用可先配置常量，企业交付倾向 DB 表可编辑）
- `audit_logs.ip` 从哪来？（登录/操作时从 request 取 `X-Forwarded-For`/client host 写入，需改 audit_log.record 签名 + 各调用点）

---

## 2026-07-07 · DemoBadge 智能化：按数据来源自动切实时/演示态（✅ 已完成）

### 背景
Dashboard/Reports/Knowledge 已切真接口，但仍显示「演示数据·待后端接入」徽标，观感与实际不符。

### 改动（比单纯隐藏更优）
DemoBadge 接受 `module` prop，按 `MOCK_ENABLED[module]` 自动判定：
- 已切真接口 → 绿色 ✓「实时数据 · 已接入后端」（`--sage`）
- 仍走 mock → 琥珀色 ⓘ「演示数据 · 待后端接入」（`--amber`）
- 不传 module → 默认演示态（兼容 Rules/History/Admin/Rectify 旧用法）

| 文件 | 内容 |
|---|---|
| `src/components/common/DemoBadge.vue` | 加 `module` prop + `isLive` 计算属性 + `.live` 绿色样式 + 图标条件切换 |
| `src/plugins/icons.ts` | 注册 `SuccessFilled`（import + ICONS 两处） |
| `DashboardView/KnowledgeView/ReportsView.vue` | 分别传 `module="dashboard/knowledge/reports"` |

### 好处
翻 `MOCK_ENABLED` 开关时 badge 自动同步，无需再手改页面。演示时绿/黄徽标一眼区分「已落地 vs 演示态」，是加分项。

### 验证
`npm run type-check` 通过；Playwright 实测 Dashboard 徽标已变绿「实时数据·已接入后端」，图标+配色正确。

---

## 2026-07-07 · 修 LLM 502 + Dashboard/Reports/Knowledge 切真接口（✅ 已完成）

### 任务目标
1. 修真实 LLM 端点 502；2. 把 Dashboard/Reports/Knowledge 前端 mock 切真接口并浏览器实测。

### 502 根因与修复
- **根因**：本机无本地 LLM 服务（Ollama 未运行）+ 无 `backend/.env`，默认 `LLM_BASE_URL=http://localhost:11434/v1` 指向空端点 → 502。
- **修复**：新建 `backend/.env` 切 DeepSeek（`LLM_PROVIDER=deepseek` / `https://api.deepseek.com/v1` / `deepseek-chat`），`factory.py` 走 OpenAI 兼容分支无需改。DeepSeek 无 embedding → seed 知识库写 `embedding=""`，RAG 走关键词降级。
- **踩坑**：`settings` 是 `@lru_cache`，改 `.env` 后**必须重启后端进程**才生效（改完没重启会继续用旧 key）。

### 改动清单
| 层 | 文件 | 内容 |
|---|---|---|
| 后端 | `backend/.env`（新建，不入 git） | DeepSeek 配置 + `AUDIT_ASYNC=false`（无 Redis 同步执行） |
| 后端 | `backend/.env.example` | 补方案 A（私有化 Qwen）/ 方案 B（DeepSeek）双注释 |
| 后端 | `backend/scripts/seed_demo.py`（新建） | 幂等 seed：12 合同（4 部门）+ 23 风险（覆盖 level/tier/agent/review_status 全维）+ 12 知识切片（四类，`embedding=""`） |
| 后端 | `app/services/report/exporter.py` | `report_summary()` + `_ramp_series()` + `_RANGE_LABELS`（上条已写） |
| 后端 | `app/api/v1/endpoints/reports.py` | `GET /reports/summary`（上条已写） |
| 后端 | `app/api/v1/endpoints/knowledge.py` | `GET /knowledge/cards` + `/stats` + `_CAT_LABEL` + `_chips_for()`（上条已写） |
| 前端 | `src/api/dashboard.ts`（新建） | dashboard summary 适配壳 |
| 前端 | `src/mock/dashboard.ts`（新建） | `DashboardSummary` 类型 + 演示基线 |
| 前端 | `src/views/DashboardView.vue` | KPI 从真实 summary 派生（累计合同/风险 + 复核派生通过率）+ loading(skeleton)/error(alert+重试) 态 |
| 前端 | `src/mock/index.ts` | `dashboard/reports/knowledge` 三开关置 `false` |

### 验证结论（已实测通过）
- **后端三端点**（curl + legal 账号）：`/dashboard/summary` 返回 14 合同/28 风险；`/reports/summary` KPI+trend+donut 齐全；`/knowledge/stats` 四类 3/4/3/2、`/cards` 12 张，中文正常。
- **前端浏览器实测**（Playwright，5173）：登录→Dashboard KPI 显示真实 14份/28条/35.7%；Reports 趋势图+KPI 渲染；Knowledge 四统计卡+12 卡片渲染；分类筛选/range 切换交互正常；响应式 <1180px（1000×800）侧栏折叠+KPI 变 2 列正常；仅 favicon 404 无害。
- **真实 LLM audit 跑通**：造测试合同（ID 15）走 upload→audit，两 Agent 均 `mode=llm`（法务 7 条+财务 8 条=15 条），日志有 `llm.chat`（deepseek-chat，441+644/6.2s、551+720/6.8s），触发 X1 关联交易 + X3 联合高风险交叉验证。相比 mock 降级的 2 条，LLM 语义分析质量明显更高。
- `npm run type-check` 通过。

### 遗留
- **合规通过率 seed 下为 0%/35.7%**：seed 的 12 份合同全部挂了风险，无「无风险」合同，故 reports 通过率算 0，符合逻辑（真实运营数据会有通过合同）。
- **DemoBadge「演示数据·待后端接入」仍全局显示**：Dashboard/Reports/Knowledge 已是真接口，badge 是全局演示标识，后续可按页做条件隐藏。
- **测试合同 ID 15 + 截图临时文件**留在库中/桌面（删除被拒未清理），可手动删。
- **P2 Rules/History/Rectify 后端端点仍未创建**（本次未涉及）。

---

## 2026-07-07 · 双 Agent 协作深化：串行协同 + 冲突消解 + 分级分档（前后端联动）

参考组员建议（`桌面/新建 DOCX 文档.docx`），把"双 Agent 各跑各的"升级为真协同，并在前后端同时落地。

### 背景
前端新增"双 Agent 协作"页面后，展示了主从串行链路、交叉验证、分级人工干预，但后端仍是两个 Agent 平行独立跑（`for role in _AGENTS`），存在"前端画饼、后端未兑现"落差。本次补齐后端。

### 后端改动（`backend/`）
| 模块 | 文件 | 内容 |
|---|---|---|
| 串行协作 | `app/services/audit/auditor.py` | 平行循环改主从串行：法务先行→结论写入 `shared_context`（共享记忆窗口）→财务读取法务输出（含关联交易标记）再审，prompt 声明勿重复解析 |
| 冲突消解 | `auditor.py` + `app/schemas/contract.py` | 新增 `detect_conflicts()`：关联交易→财务价格公允性复查、收款账户不一致→回传法务、双高风险→联合决策；随 audit 响应返回 `cross_checks` |
| 分级分档 | `app/models/models.py` + `auditor.py` + `schemas` | Risk 表加 `tier` 字段；`classify_tier()` 按 level+置信度+敏感词+是否卷入冲突 分 green/yellow/red |
| 返回结构 | `runner.py` / `contracts.py` / `tasks/audit_tasks.py` | `audit_contract` 返回 `{risks, cross_checks}`；audit 端点响应模型改 `AuditResponse`（含 cross_checks） |
| DB 迁移 | `app/db/init_db.py` | 开发期 SQLite 自动补 `tier` 列（`_migrate_dev_columns`），生产走 alembic |

### 前端改动（`frontend/`）
| 文件 | 内容 |
|---|---|
| `src/api/types.ts` | `RiskOut` 加 `tier`；新增 `CrossCheckOut`；`AuditResult` 加 `cross_checks` |
| `src/stores/audit-session.ts` | 审查完成存 `crossChecks` |
| `src/views/CollaborationView.vue` | 真实会话用后端 `tier` 与 `cross_checks`，无会话降级 mock（`tierOf` 优先读 `r.tier`） |
| `src/mock/collaboration.ts` | 新增 `COLLAB_CHAIN`（串行链路）、`CROSS_CHECKS`（冲突场景）、`RISK_TIERS`（三档元数据）；删除废弃的 `COLLAB_FLOW` |
| `src/config/nav.ts` / `src/router/index.ts` / `src/plugins/icons.ts` | 新增"双 Agent 协作"导航项、路由、`Connection` 图标 |

### 验证
- 后端：编译通过；独立脚本验证串行降级、冲突检测（收款账户冲突不依赖 LLM 也触发）、分档单测 5/5 通过；`init_db` 已实测补上 `tier` 列
- 前端：`npm run type-check` 通过
- 实测发现真实 LLM 端点 502，两 Agent 降级 mock、链路照常工作，印证"单 Agent 不可用降级、链路始终可用"设计

### 待办
- 真实 LLM 端点当前返回 502，需排查配置（`app/llm/`）
- `detect_conflicts` 关联交易检测依赖法务输出含"关联"字样，LLM 接通后更准
