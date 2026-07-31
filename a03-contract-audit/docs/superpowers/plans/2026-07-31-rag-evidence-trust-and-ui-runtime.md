# RAG Evidence Trust and UI Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 阻止未分类或跨领域知识成为正式审查依据，要求用户明确确认合同类型，并修复前端运行时图标错误、补充审查阶段耗时观测。

**Architecture:** 保持单一知识索引，为每个知识切片增加 `global | scoped | unclassified` 显式作用域。检索先按作用域、合同类型、维度和有效期做默认拒绝过滤，再执行向量/BM25 融合；只有通过过滤且有正相关分数的结果才标记可靠。审查接口把合同类型作为强前置条件，前端不再静默写入默认类型。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、SQLite/PostgreSQL、pytest/unittest、Vue 3、TypeScript、Element Plus、Playwright

---

### Task 1: 知识作用域模型与迁移

**Files:**
- Create: `backend/alembic/versions/20260731_01_add_knowledge_scope_mode.py`
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/db/init_db.py`
- Test: `backend/tests/test_rag_hardening_unittest.py`

- [ ] **Step 1: 写迁移红灯测试**

在 `RagHardeningTests` 增加断言：`KnowledgeChunk.scope_mode` 默认值为 `unclassified`；Alembic 升级后 `knowledge_chunks.scope_mode` 存在且服务端默认值为 `unclassified`；`init_db._DEV_COLUMNS["knowledge_chunks"]` 包含补列 SQL。

```python
def test_knowledge_scope_defaults_to_unclassified(self):
    chunk = KnowledgeChunk(category="law", source="unknown", content="text")
    self.assertEqual(chunk.scope_mode, "unclassified")

def test_dev_schema_contains_scope_mode_backfill(self):
    self.assertIn("scope_mode", init_db._DEV_COLUMNS["knowledge_chunks"])
```

- [ ] **Step 2: 运行红灯**

Run: `cd backend; python -m pytest tests/test_rag_hardening_unittest.py -k "scope_mode or dev_schema" -q`

Expected: FAIL，原因是字段和迁移尚不存在。

- [ ] **Step 3: 实现最小模型和迁移**

模型字段使用非空字符串且默认拒绝：

```python
scope_mode: Mapped[str] = mapped_column(
    String(16), nullable=False, default="unclassified", server_default="unclassified"
)
```

Alembic `upgrade()` 新增非空列，默认 `unclassified`；`downgrade()` 删除该列。开发态 SQLite 补列沿用同一默认值，不把历史空范围知识自动升级为 `global`。

- [ ] **Step 4: 运行绿灯及迁移往返**

Run: `cd backend; python -m pytest tests/test_rag_hardening_unittest.py -k "scope_mode or dev_schema or alembic" -q`

Expected: PASS，fresh database 可 upgrade 到 head 并 downgrade 到 base。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/models/models.py backend/app/db/init_db.py backend/alembic/versions/20260731_01_add_knowledge_scope_mode.py backend/tests/test_rag_hardening_unittest.py
git commit -m "feat: add explicit knowledge scope mode"
```

### Task 2: 检索默认拒绝与可靠性判定

**Files:**
- Modify: `backend/app/services/rag/retriever.py`
- Modify: `backend/app/services/audit/auditor.py`
- Test: `backend/tests/test_rag_hardening_unittest.py`
- Test: `backend/tests/test_rag_grounding.py`

- [ ] **Step 1: 写检索红灯测试**

新增四个独立行为测试：`unclassified` 永不进入正式结果；`global` 可跨合同类型但仍受日期/分类约束；`scoped` 必须命中合同类型或审查维度；BM25 零分文档不返回。文档元组在现有 13 列末尾增加 `scope_mode`。

```python
def test_filter_docs_rejects_unclassified_and_cross_domain_scoped(self):
    result = retriever._filter_docs(
        [unclassified_doc, software_scoped_doc, global_doc],
        contract_type="设备采购合同",
        dimensions=["payment"],
    )
    self.assertEqual([doc[0] for doc in result], [global_doc[0]])
```

再增加审查落地测试：来源缺少 `reliable` 时按 `False` 处理，风险降级为无 `rag_sources`、人工复核、置信度不超过 50。

- [ ] **Step 2: 运行红灯**

Run: `cd backend; python -m pytest tests/test_rag_hardening_unittest.py tests/test_rag_grounding.py -k "unclassified or scoped or zero_score or missing_reliable" -q`

Expected: FAIL，旧实现放行空范围、固定写 `reliable=True`，并把缺失可靠性当真。

- [ ] **Step 3: 实现最小过滤与可靠性逻辑**

查询列加入 `KnowledgeChunk.scope_mode`。`_filter_docs()` 规则：

```python
if scope_mode == "unclassified":
    continue
if scope_mode == "scoped" and not (
    contract_type in applicable_contract_types
    or bool(set(dimensions) & set(applicable_dimensions))
):
    continue
if scope_mode not in {"global", "scoped"}:
    continue
```

BM25 只保留 `score > 0`；向量结果只有达到既有阈值才参与融合；正式知识结果的 `reliable` 来自通过上述过滤和有效分数，而不是无条件赋真。`auditor.py` 使用 `source.get("reliable", False)`。

- [ ] **Step 4: 运行绿灯与相关回归**

Run: `cd backend; python -m pytest tests/test_rag_hardening_unittest.py tests/test_rag_grounding.py tests/test_audit_evidence.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/services/rag/retriever.py backend/app/services/audit/auditor.py backend/tests/test_rag_hardening_unittest.py backend/tests/test_rag_grounding.py
git commit -m "fix: default deny untrusted rag evidence"
```

### Task 3: 知识导入校验与种子分类

**Files:**
- Modify: `backend/app/api/v1/endpoints/knowledge.py`
- Modify: `backend/app/services/rag/retriever.py`
- Modify: `backend/app/db/init_db.py`
- Test: `backend/tests/test_rag_hardening_unittest.py`

- [ ] **Step 1: 写导入红灯测试**

覆盖：未传作用域时导入为 `unclassified`；`scope_mode=scoped` 且合同类型、维度均为空时返回 422；`global` 可无适用范围；核心《民法典》种子显式为 `global`；软件和采购模板显式为对应 `scoped`。

```python
def test_prepare_documents_rejects_scope_without_targets(self):
    with self.assertRaisesRegex(ValueError, "适用合同类型或审查维度"):
        retriever.prepare_documents([{"content": "x", "scope_mode": "scoped"}])
```

- [ ] **Step 2: 运行红灯**

Run: `cd backend; python -m pytest tests/test_rag_hardening_unittest.py -k "scope_without_targets or seed_scope or upload_scope" -q`

Expected: FAIL，旧导入链没有 `scope_mode` 校验和持久化。

- [ ] **Step 3: 实现最小导入规则**

在 API/索引准备边界规范化枚举，拒绝未知值；`scoped` 必须至少含一个适用目标；未知历史/普通上传保持 `unclassified`。仅在明确可识别的受控种子定义中写入 `global` 或 `scoped`，不按 `category=law` 自动升级。

- [ ] **Step 4: 运行绿灯**

Run: `cd backend; python -m pytest tests/test_rag_hardening_unittest.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/api/v1/endpoints/knowledge.py backend/app/services/rag/retriever.py backend/app/db/init_db.py backend/tests/test_rag_hardening_unittest.py
git commit -m "feat: validate knowledge scope on ingestion"
```

### Task 4: 合同类型确认门禁

**Files:**
- Modify: `backend/app/api/v1/endpoints/contracts.py`
- Modify: `frontend/src/api/contract.ts`
- Modify: `frontend/src/views/AuditView.vue`
- Test: `backend/tests/test_contract_quality_api.py`
- Test: `frontend/tests/enterprise-ui.spec.ts`

- [ ] **Step 1: 写后端与前端红灯测试**

后端直接调用审查端点时，空白合同类型应得到 422，且不会启动审查；批量审查条目缺少明确合同类型时也不得继承单合同页面默认值。前端测试上传设备采购材料后，合同类型控件初始为空；未确认时“开始审查”不可用并显示明确校验；选择类型后请求携带该值并允许审查；文件名或已解析内容明显指向采购、但用户选择软件开发时显示非阻断式冲突确认提示。

```python
def test_audit_rejects_contract_without_confirmed_type(...):
    contract.contract_type = " "
    with pytest.raises(HTTPException) as exc:
        contracts.audit_contract(contract.id, request, db=db, user=user)
    assert exc.value.status_code == 422
```

- [ ] **Step 2: 运行红灯**

Run: `cd backend; python -m pytest tests/test_contract_quality_api.py -k contract_type -q`

Run: `cd frontend; npm test -- enterprise-ui.spec.ts --grep "合同类型"`

Expected: 两组均 FAIL；旧后端不拦截，旧前端静默默认软件开发类型。

- [ ] **Step 3: 实现最小确认链路**

后端单合同和批量审查入口都在任何 Agent/RAG 调用前验证持久化合同类型，缺失返回 422。前端 `contractType` 初始为 `''`，上传不写虚假默认值；类型控件标为必选，按钮禁用条件加入 `!contractType`，启动审查前先持久化/随请求提交用户确认值。建议值只能作为提示，不自动选中；用文件名和已解析合同标题中的受控关键词生成冲突提示，用户二次确认后才继续，不把推测值静默写入数据库。

- [ ] **Step 4: 运行绿灯**

Run: `cd backend; python -m pytest tests/test_contract_quality_api.py -q`

Run: `cd frontend; npm test -- enterprise-ui.spec.ts --grep "合同类型"`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/api/v1/endpoints/contracts.py backend/tests/test_contract_quality_api.py frontend/src/api/contract.ts frontend/src/views/AuditView.vue frontend/tests/enterprise-ui.spec.ts
git commit -m "feat: require confirmed contract type before audit"
```

### Task 5: 前端图标运行时修复

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue`
- Modify: `frontend/src/components/layout/AppSidebar.vue`
- Modify: `frontend/src/components/audit/RiskReviewDrawer.vue`
- Test: `frontend/tests/enterprise-ui.spec.ts`

- [ ] **Step 1: 写控制台红灯测试**

在页面加载、侧栏折叠/展开、风险抽屉打开流程收集 `console` warning/error，断言不存在 `Failed to resolve component: Menu|Expand|Fold|ChatDotRound`。

- [ ] **Step 2: 运行红灯**

Run: `cd frontend; npm test -- enterprise-ui.spec.ts --grep "图标组件"`

Expected: FAIL，控制台记录未解析组件告警。

- [ ] **Step 3: 显式导入图标**

从 `@element-plus/icons-vue` 分别导入模板实际使用的 `Menu`、`Expand`、`Fold`、`ChatDotRound`，保持现有模板与视觉样式不变。

- [ ] **Step 4: 运行绿灯和类型检查**

Run: `cd frontend; npm test -- enterprise-ui.spec.ts --grep "图标组件"`

Run: `cd frontend; npm run type-check`

Expected: PASS，无相关 console warning/error。

- [ ] **Step 5: 提交**

```powershell
git add frontend/src/layouts/MainLayout.vue frontend/src/components/layout/AppSidebar.vue frontend/src/components/audit/RiskReviewDrawer.vue frontend/tests/enterprise-ui.spec.ts
git commit -m "fix: register audit layout icons"
```

### Task 6: 审查阶段耗时观测

**Files:**
- Modify: `backend/app/services/audit/auditor.py`
- Test: `backend/tests/test_audit_evidence.py`

- [ ] **Step 1: 写结构化日志红灯测试**

捕获 logger，断言一次审查输出 RAG、法务 Agent、财务 Agent、证据落地和总耗时字段，值均为非负整数毫秒；Agent 仍按原顺序执行。

```python
assert timing_event == {
    "contract_id": contract.id,
    "rag_ms": ANY_NON_NEGATIVE_INT,
    "legal_agent_ms": ANY_NON_NEGATIVE_INT,
    "finance_agent_ms": ANY_NON_NEGATIVE_INT,
    "grounding_ms": ANY_NON_NEGATIVE_INT,
    "total_ms": ANY_NON_NEGATIVE_INT,
}
```

- [ ] **Step 2: 运行红灯**

Run: `cd backend; python -m pytest tests/test_audit_evidence.py -k timing -q`

Expected: FAIL，旧实现没有阶段计时事件。

- [ ] **Step 3: 实现最小计时**

使用 `time.perf_counter()` 包裹现有串行阶段，在同一审查结束时通过项目 logger 输出一个结构化事件。异常路径保留原异常语义并记录已完成阶段，不引入 Agent 并行或新存储表。日志只含合同 ID、阶段名、耗时和状态，不记录合同正文、API Key 或完整提示词；测试额外断言敏感样本文本未出现在日志参数中。

- [ ] **Step 4: 运行绿灯**

Run: `cd backend; python -m pytest tests/test_audit_evidence.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/services/audit/auditor.py backend/tests/test_audit_evidence.py
git commit -m "perf: log audit stage timings"
```

### Task 7: 全量验收与真实材料回归

**Files:**
- Verify only; do not add generated reports, screenshots, databases, uploads, or `outputs/` to Git.

- [ ] **Step 1: 后端全量测试**

Run: `cd backend; python -m pytest -q`

Expected: 全部 PASS，0 failed。

- [ ] **Step 2: 前端静态验证与构建**

Run: `cd frontend; npm run type-check`

Run: `cd frontend; npm run build`

Expected: 两条命令 exit 0。

- [ ] **Step 3: 前端 E2E**

Run: `cd frontend; npm test`

Expected: 全部 PASS，0 failed。

- [ ] **Step 4: 浏览器桌面与移动端验证**

The flow under test is: `/audit` -> 上传合同 -> 明确选择合同类型 -> 启动审查 -> 风险结果只展示可靠依据；未选合同类型时审查被阻止。

用 Browser 插件访问 `http://127.0.0.1:5173`，检查页面身份、非空、无框架错误覆盖层、console health、交互状态变化，并在桌面与 `390x844` 视口截图。验证正常路径、合同类型空状态、类型冲突确认、后端错误提示、侧栏折叠、移动端侧栏默认隐藏、无横向溢出和风险抽屉。

- [ ] **Step 5: 真实材料 API 回归**

用临时目录生成三份不含敏感信息的材料：设备采购风险合同、正常软件外包合同、过短文本。确认：采购合同不会引用软件专属模板；可靠来源缺失时 `rag_sources=[]` 且置信度不超过 50；短文本进入人工复核；正常合同上传解析成功。

- [ ] **Step 6: 最终差异和规格逐项复核**

Run: `git status --short`

Run: `git diff --check master...HEAD`

Expected: 仅计划内文件变更，无空白错误，`outputs/` 保持未跟踪且未提交。
