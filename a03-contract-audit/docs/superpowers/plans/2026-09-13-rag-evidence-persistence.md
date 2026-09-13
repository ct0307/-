# RAG Evidence Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 持久化合同条款、来源锚点、Agent Claim 和检索轨迹，并让风险查询接口返回可用于原页定位的结构化证据。

**Architecture:** 新增 `ContractClause` 关系模型保存审查版本内的条款结构；风险表使用 JSON 字段保存不可变证据快照。审查发布事务统一写入条款和风险，避免出现“风险已发布但定位数据缺失”的中间状态。

**Tech Stack:** Python、FastAPI、SQLAlchemy、Alembic、Pydantic、pytest、SQLite/PostgreSQL

---

### Task 1: 数据模型与迁移

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/db/init_db.py`
- Create: `backend/alembic/versions/20260913_01_rag_evidence_persistence.py`
- Test: `backend/tests/test_rag_evidence_persistence.py`

- [x] 写测试，断言 `contract_clauses` 表的唯一约束、条款字段和风险新增字段存在。
- [x] 运行 `pytest tests/test_rag_evidence_persistence.py -v`，确认因模型缺失失败。
- [x] 新增 `ContractClause` 模型及 `Risk` 的 Claim/轨迹 JSON 字段。
- [x] 增加 Alembic upgrade/downgrade，并让 SQLite 开发迁移能为旧表补列、创建新表。
- [x] 重跑专项测试，确认通过。

### Task 2: 条款序列化与证据绑定服务

**Files:**
- Create: `backend/app/services/audit/evidence_persistence.py`
- Test: `backend/tests/test_rag_evidence_persistence.py`

- [x] 写测试，覆盖条款锚点序列化、风险原文精确匹配、条款提示降级和无匹配场景。
- [x] 运行专项测试，确认服务尚不存在导致预期失败。
- [x] 实现 `replace_contract_clauses()`、`build_contract_evidence()` 和严格 JSON 序列化。
- [x] 重跑专项测试，确认通过。

### Task 3: 接入审查发布事务

**Files:**
- Modify: `backend/app/services/audit/runner.py`
- Test: `backend/tests/test_audit_runner_quality.py`

- [x] 写测试，断言一次审查原子写入条款、锚点、Claim、Evidence ID 和检索尝试。
- [x] 运行目标测试，确认因未接入发布事务而失败。
- [x] 在 generation 校验后替换条款并创建风险证据快照，扩展 `_risk_model()` 持久化字段。
- [x] 重跑审查执行器专项测试，确认通过且旧行为不回归。

### Task 4: 扩展风险 API 契约

**Files:**
- Modify: `backend/app/schemas/contract.py`
- Modify: `backend/app/services/masking.py`
- Test: `backend/tests/test_contract_quality_api.py`

- [x] 写 API 测试，验证高权限角色收到完整 Claim/定位/检索轨迹，业务角色不收到检索查询原文。
- [x] 运行目标测试，确认新字段缺失导致预期失败。
- [x] 扩展 `RiskOut` JSON 解析和业务角色脱敏映射。
- [x] 重跑 API 测试，确认通过。

### Task 5: 回归与文档

**Files:**
- Modify: `README.md`
- Modify: `docs/evaluation/hard-indicator-matrix.md`

- [x] 运行新增专项测试和相关审查/API 测试。
- [x] 运行 Alembic 升降级测试，确认迁移链完整。
- [x] 更新能力边界，明确后端证据持久化已实现、前端原页高亮仍未实现。
- [x] 运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1` 并记录退出码与测试计数。

本轮不自动创建 Git 提交，避免替用户决定当前未提交工作树的提交边界。
