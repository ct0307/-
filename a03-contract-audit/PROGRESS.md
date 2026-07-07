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
| 工作台 Dashboard | ✅ | ✅（dashboard/summary） | 前端仍挂 mock | 待切真接口 |
| 多维报表 Reports | ✅ | ✅（reports 导出） | 前端仍挂 mock | 待切真接口 |
| 法规知识库 Knowledge | ✅ | ✅（导入/检索） | 前端仍挂 mock | 待切真接口 |
| 规则与模板 Rules | ✅ | ⬜ 无端点 | 纯前端 mock | 后端未做 |
| 审查记录 History | ✅ | ⬜ 无端点 | 纯前端 mock | 后端未做 |
| 权限与审计 Admin | ✅ | 部分（audit_logs 有表） | 前端仍挂 mock | 待接 |
| 整改跟踪 Rectify | ✅ | ⬜ 无端点 | 前端 store 本地态 | 后端未做 |

### 关键待办（优先级）
1. **P1** 真实 LLM 端点当前 502，需排查 `backend/app/llm/` 配置，跑通真实审查（现降级 mock 可用）
2. **P1** Dashboard / Reports / Knowledge 后端已就绪，把前端 `MOCK_ENABLED` 对应项置 false 并联调
3. **P2** Rules / History / Rectify 后端端点尚未创建
4. **P3** 生产 PostgreSQL 的 alembic 迁移脚本（当前 SQLite 用开发期补列兜底）

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
