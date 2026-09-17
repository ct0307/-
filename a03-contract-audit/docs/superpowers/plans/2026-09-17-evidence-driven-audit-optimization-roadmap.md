# 证据驱动审查优化实施路线

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按可独立验证、可回退的顺序实施证据驱动合同审查优化，避免把后端重构、模型接入、数据库迁移和前端改造混成一个大变更。

**Architecture:** 四个实施计划按“审查内核 → RAG → 规则与证据 → 评测与前端”顺序执行。每一阶段通过自己的测试与质量门禁后，下一阶段才能开始；外部模型下载、依赖变化和真实数据调用设置单独确认点。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLAlchemy、Alembic、sentence-transformers、Vue 3、TypeScript、Element Plus、pytest、Playwright。

---

## 计划依赖

```text
阶段 1：审查内核与提示词版本化
  |
  | 产出 Claim v1、Prompt Registry、独立双 Agent 首审
  v
阶段 2：RAG 适用性与精排
  |
  | 产出 Query Plan v1、法规时点、可降级 Cross-Encoder
  v
阶段 3：规则引擎与证据支持 V3
  |
  | 产出 Rule Registry、Support V3、统一 RiskDecision、迁移
  v
阶段 4：评测与前端证据展示
     产出 V0-V4 消融、兼容 API、局部 UI、浏览器验收
```

对应详细计划：

1. `docs/superpowers/plans/2026-09-17-audit-core-and-prompt-versioning.md`
2. `docs/superpowers/plans/2026-09-17-rag-applicability-and-reranking.md`
3. `docs/superpowers/plans/2026-09-17-rule-engine-and-evidence-v3.md`
4. `docs/superpowers/plans/2026-09-17-audit-evaluation-and-ui-evidence.md`

### Task 1: 冻结实施基线

- [ ] **Step 1: 记录当前工作树，避免覆盖用户改动**

Run: `git -C a03-contract-audit status --short`

Expected: 保存输出；已有修改不回退、不混入本项目各阶段提交。

- [ ] **Step 2: 运行当前质量门禁**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File a03-contract-audit/scripts/quality_gate.ps1`

Expected: 退出码 0；若失败，保存具体失败测试和环境原因，先区分既有失败与本计划回归。

- [ ] **Step 3: 生成 V0 基线快照**

先在批准的输入目录中验证 `gold.jsonl` 和 `predictions-v0.jsonl` 的存在与哈希，然后在 `backend/` 工作目录运行：

```powershell
if (-not (Test-Path -LiteralPath 'evaluation-inputs/gold.jsonl')) { throw '缺少经批准的金标，停止专业基线评测' }
if (-not (Test-Path -LiteralPath 'evaluation-inputs/predictions-v0.jsonl')) { throw '缺少当前实现预测，停止专业基线评测' }
.\.venv\Scripts\python.exe -m evaluation.cli audit-quality --gold evaluation-inputs/gold.jsonl --predictions evaluation-inputs/predictions-v0.jsonl --runs-root evaluation-runs --run-id evidence-v0
```

这些输入不属于版本控制交付物，不得自动创建或从系统预测反推金标。

Expected: 生成 `manifest.json`、`evidence.jsonl` 和 `report.md`。没有经批准金标或真实预测时，本步骤明确标记 `blocked_external_evidence`，不得使用测试夹具伪装 V0 专业基线。

- [ ] **Step 4: 建立实施分支或隔离工作树**

Run: `git -C a03-contract-audit branch --show-current`

Expected: 分支名可识别且不是需要保护的交付分支；如需创建分支，使用 `codex/evidence-driven-audit`。创建工作树属于实施会话动作，本计划不自动执行。

### Task 2: 执行阶段 1

- [ ] **Step 1: 按第一份详细计划逐任务执行**

Run: 打开 `docs/superpowers/plans/2026-09-17-audit-core-and-prompt-versioning.md`，从 Task 1 开始按红灯、实现、绿灯、提交顺序执行。

Expected: Claim、Prompt 和独立首审均由新模块负责，`audit_contract()` 和现有 API 保持兼容。

- [ ] **Step 2: 检查阶段退出条件**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_claims.py a03-contract-audit/backend/tests/test_audit_prompts.py a03-contract-audit/backend/tests/test_audit_collaboration.py a03-contract-audit/backend/tests/test_audit_evidence.py -q`

Expected: 全部 PASS；财务首审提示词不含法务 Claim；单个 Agent 失败不抹除另一 Agent 已验证结果。

### Task 3: 执行阶段 2

- [ ] **Step 1: 先完成模型与供应链确认**

在启用 `BAAI/bge-reranker-base` 或其他精排模型前，向用户报告模型来源、许可证、文件体积、哈希记录方案、是否联网下载、缓存目录和合同数据是否离开本机。未经确认保持 `RERANK_BACKEND=disabled`，测试使用假模型，不执行下载。

- [ ] **Step 2: 按第二份详细计划逐任务执行**

Run: 打开 `docs/superpowers/plans/2026-09-17-rag-applicability-and-reranking.md`，依次完成 Query Plan、时点判定、精排适配、一次纠错和 RAG 验收。

Expected: 检索轨迹明确标识 `exact`、`bm25`、`hybrid`、`cross_encoder` 或降级模式；未知法规时点不自动认定适用。

- [ ] **Step 3: 检查阶段退出条件**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rag_query_planner.py a03-contract-audit/backend/tests/test_rag_applicability.py a03-contract-audit/backend/tests/test_rag_reranker.py a03-contract-audit/backend/tests/test_rag_grounding.py -q`

Expected: 全部 PASS；精排器失败时保留 RRF 候选；每个查询最多纠错一次。

### Task 4: 执行阶段 3

- [ ] **Step 1: 按第三份详细计划逐任务执行**

Run: 打开 `docs/superpowers/plans/2026-09-17-rule-engine-and-evidence-v3.md`，依次完成注册表、首批规则、五层支持验证、统一决策和迁移。

Expected: 规则、支持关系和决策均使用受控状态与原因码；模型不能覆盖原文、权威性、时点和硬规则门禁。

- [ ] **Step 2: 验证迁移可逆**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_db_migrations.py -q`

Expected: 升级、降级和再次升级均 PASS；旧风险记录可读取并默认进入保守状态。

- [ ] **Step 3: 检查阶段退出条件**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rule_registry.py a03-contract-audit/backend/tests/test_rule_executor.py a03-contract-audit/backend/tests/test_evidence_support_v3.py a03-contract-audit/backend/tests/test_risk_decision.py -q`

Expected: 全部 PASS；未知、冲突和异常不会进入 `accepted`。

### Task 5: 执行阶段 4

- [ ] **Step 1: 先完成后端评测，再修改前端**

Run: 打开 `docs/superpowers/plans/2026-09-17-audit-evaluation-and-ui-evidence.md`，先完成 Task 1 至 Task 3。

Expected: V0-V4 比较器和兼容 API 字段稳定；缺少真实证据时输出 `not_measured`，不填零。

- [ ] **Step 2: 执行前端最小联动**

Run: 继续执行该计划 Task 4 至 Task 6。

Expected: 不新增主导航或大型页面；旧 API、空状态、错误状态、降级状态和移动端均可用。

- [ ] **Step 3: 浏览器实测**

Run: 启动后端与前端，并按详细计划在 1440x900、1024x768 和 390x844 验证风险抽屉、协同页和报告证据抽屉。

Expected: 无遮挡和横向溢出；未知或冲突状态不显示为通过；交互动作调用真实服务接口或明确测试替身。

### Task 6: 项目级最终验收

- [ ] **Step 1: 运行完整质量门禁**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File a03-contract-audit/scripts/quality_gate.ps1`

Expected: 退出码 0。

- [ ] **Step 2: 检查差异和敏感文件**

Run: `git -C a03-contract-audit diff --check`

Run: `git -C a03-contract-audit status --short`

Expected: 没有空白错误；不包含 `.env`、合同原件、数据库、模型缓存、运行日志或 `outputs/`。

- [ ] **Step 3: 核对证据边界**

逐项检查 `docs/evaluation/hard-indicator-matrix.md`：只有本轮真实执行的测试、金标、模型和浏览器证据可更新为已验证；真实专家金标、PostgreSQL、模型精排或设备实测缺失时继续标记“代码就绪待实测”或“阻塞”。

- [ ] **Step 4: 形成提交与验收记录**

Expected: 四阶段提交边界清晰；每个阶段包含对应测试证据；不把工作区既有无关改动纳入提交。

## 暂停与确认点

以下情况必须暂停并取得用户确认：

- 下载新的精排模型、安装或升级依赖；
- 使用真实合同、真实专家标注或外部 LLM 服务；
- 修改生产配置、CI/CD 或部署环境；
- 删除文件、重置分支、强推或清理工作区；
- 发现现有未提交改动与计划目标文件发生无法安全合并的冲突。
