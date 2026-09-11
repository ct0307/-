# 大模型合同审查可靠性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将单文件上传和审查改造成幂等、持久、可恢复且模型成本受控的企业级流程。

**Architecture:** 单文件审查复用 `AuditBatch`/`AuditBatchItem`，由 Celery 或本地线程池 Adapter 异步执行。上传使用用户范围幂等键和内容指纹；审查用 generation 在事务外推理并以短事务发布结果，前端只消费持久状态。

**Tech Stack:** Python、FastAPI、SQLAlchemy、Alembic、Celery、pytest、Vue 3、TypeScript、Pinia、Axios、Playwright。

---

### Task 1: 数据契约与迁移

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/schemas/contract.py`
- Modify: `backend/app/schemas/batch.py`
- Modify: `backend/app/db/init_db.py`
- Create: `backend/alembic/versions/20260911_01_audit_reliability.py`
- Test: `backend/tests/test_audit_job_service.py`

- [ ] 写失败测试：断言合同上传指纹、审查 generation、批次请求指纹、任务错误码和结果 JSON 可持久化。
- [ ] 运行 `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_audit_job_service.py -q`，确认因字段缺失失败。
- [ ] 增加向后兼容的可空/默认字段和升级、降级迁移。
- [ ] 重跑目标测试确认通过。

### Task 2: 上传幂等与文件一致性

**Files:**
- Modify: `backend/app/api/v1/endpoints/contracts.py`
- Modify: `backend/app/services/audit_log.py`
- Test: `backend/tests/test_contract_quality_api.py`

- [ ] 写失败测试：相同 key/内容返回原合同，不同内容返回 409，数据库失败清理新文件，日志记录不隐式提交。
- [ ] 运行目标测试确认 RED。
- [ ] 计算 SHA-256 并在用户范围解析幂等；用异常清理保证文件与数据库一致。
- [ ] 将审计日志改为只 `add/flush`，由端点显式提交。
- [ ] 重跑目标测试确认 GREEN。

### Task 3: 持久单文件审查任务

**Files:**
- Create: `backend/app/services/audit/jobs.py`
- Create: `backend/app/tasks/dispatcher.py`
- Modify: `backend/app/api/v1/endpoints/contracts.py`
- Modify: `backend/app/tasks/audit_tasks.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_audit_job_service.py`
- Test: `backend/tests/test_batch_api.py`

- [ ] 写失败测试：创建单项任务、幂等复用、payload 冲突、本地后台派发、活动租约防重复、启动恢复。
- [ ] 运行目标测试确认 RED。
- [ ] 实现任务创建 Module 和 Celery/本地两个 Adapter；端点始终快速返回持久任务身份。
- [ ] 状态查询从任务项读取状态、错误和结果。
- [ ] 重跑目标测试确认 GREEN。

### Task 4: 模型预算与短事务发布

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/app/llm/base.py`
- Modify: `backend/app/llm/adapters/openai_compatible.py`
- Modify: `backend/app/services/audit/runner.py`
- Test: `backend/tests/test_llm_adapter.py`
- Test: `backend/tests/test_audit_runner_quality.py`

- [ ] 写失败测试：请求包含 `max_tokens`，模型调用前已释放合同锁事务，陈旧 generation 拒绝发布，交叉验证写入任务结果。
- [ ] 运行目标测试确认 RED。
- [ ] 增加模型输出预算；重构 runner 为领取、计算、短事务发布三个阶段。
- [ ] 重跑目标测试确认 GREEN。

### Task 5: 前端幂等、错误与恢复

**Files:**
- Modify: `frontend/src/api/contract.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/stores/audit-session.ts`
- Modify: `frontend/src/views/AuditView.vue`
- Modify: `frontend/src/utils/audit-progress.ts`
- Test: `frontend/tests/contract-upload-session.spec.ts`
- Test: `frontend/tests/audit-progress.spec.ts`

- [ ] 写失败测试：请求携带稳定键、审查错误透传、未知状态失败关闭、刷新恢复进行中任务。
- [ ] 运行目标测试确认 RED。
- [ ] 使用 Web Crypto 生成上传指纹，持久化最小活动任务元数据并恢复轮询，页面展示真实错误。
- [ ] 重跑测试、类型检查和构建确认 GREEN。

### Task 6: 完整验收与版本控制

**Files:**
- Modify: `.planning/llm-audit-reliability-implementation/task_plan.md`
- Modify: `.planning/llm-audit-reliability-implementation/progress.md`

- [ ] 启动后端和前端，浏览器验证正常、错误、恢复及 1440x900/390x844。
- [ ] 运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1`。
- [ ] 运行 `git diff --check`、密钥/大文件/数据库检查和迁移升级降级检查。
- [ ] 复核需求清单，记录未覆盖的真实环境边界。
- [ ] 提交业务改动和验收记录，确认 `git status --short` 为空。

