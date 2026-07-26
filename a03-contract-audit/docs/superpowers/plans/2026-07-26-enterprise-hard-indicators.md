# 赛题硬指标企业交付化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 OCR、风险级法规溯源、50 份以上异步批处理、要素准确率评测和 OpenClaw/GPU 对照测试建设为可复现、可审计、可交付的真实能力。

**Architecture:** 保留现有 FastAPI + Vue 业务闭环，在后端增加持久化批次域、OCR 适配层、评测工具和基准测试工具。所有长任务通过 Celery 调度，状态落数据库；前端只展示服务端真实状态。外部模型和硬件通过明确接口接入，不使用演示数据替代测量结果。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy、Alembic、Celery、Redis、SQLite（本地）/PostgreSQL（交付）、Vue 3、TypeScript、pytest、Playwright；OCR 候选为 RapidOCR + ONNX Runtime，前端单测候选为 Vitest（新增依赖均在安装前单独审批）。

---

## 文件结构

| 路径 | 职责 |
|---|---|
| `backend/app/services/parser/ocr.py` | OCR 协议、图像渲染、离线 OCR 实现和质量门槛 |
| `backend/app/services/parser/extractor.py` | 文本型 PDF/DOCX 解析与 OCR 降级编排 |
| `backend/app/models/models.py` | `AuditBatch`、`AuditBatchItem` 持久化模型 |
| `backend/alembic/` | PostgreSQL 交付环境的可回滚数据库迁移 |
| `backend/app/schemas/batch.py` | 批次创建、状态、重试响应模型 |
| `backend/app/services/batch/service.py` | 批次状态机、进度聚合、幂等与失败隔离 |
| `backend/app/tasks/audit_tasks.py` | 单文件解析审查任务和批次任务调度 |
| `backend/app/api/v1/endpoints/batches.py` | 创建、查询、重试批次接口 |
| `backend/app/services/audit/evidence.py` | 单条风险检索查询与法规证据绑定 |
| `backend/evaluation/elements.py` | 字段标准化与准确率、召回率、F1 计算 |
| `backend/evaluation/batch.py` | 50 份批处理验收与原始事件记录 |
| `backend/evaluation/benchmark.py` | OpenClaw/GPU 同口径基准测试与统计 |
| `backend/app/api/v1/endpoints/runtime.py` | 真实模型端点健康状态 |
| `frontend/src/api/batches.ts` | 批次接口类型与请求封装 |
| `frontend/src/stores/batch.ts` | 服务端批次状态轮询与重试 |
| `frontend/src/api/runtime.ts` | 真实算力状态接口 |
| `frontend/src/components/layout/OpenClawBadge.vue` | 展示真实在线、离线、未知状态 |

## Task 1：建立硬指标测试基线

**Files:**
- Create: `backend/tests/test_parser_contracts.py`
- Create: `backend/tests/test_audit_evidence.py`
- Create: `backend/tests/test_batch_service.py`
- Create: `backend/tests/test_element_metrics.py`
- Create: `backend/tests/test_runtime_status.py`
- Modify: `backend/tests/test_placeholder.py`

- [ ] **Step 1：删除恒真占位用例，写解析契约失败测试**

```python
def test_scanned_pdf_uses_ocr_when_text_layer_is_empty(monkeypatch):
    monkeypatch.setattr(extractor, "_extract_pdf_text", lambda _: "")
    monkeypatch.setattr(extractor, "ocr_pdf_bytes", lambda _: "甲方：测试公司")
    assert extractor._extract_pdf_bytes(b"pdf") == "甲方：测试公司"
```

- [ ] **Step 2：运行解析契约测试并确认因接口缺失而失败**

Run: `pytest tests/test_parser_contracts.py -q`

Expected: FAIL，提示 `_extract_pdf_text` 或 `ocr_pdf_bytes` 不存在。

- [ ] **Step 3：为批次状态机、证据绑定、评测和健康检查分别写最小失败用例**

```python
def test_batch_progress_counts_terminal_items():
    assert summarize(["done", "failed", "running"]).completed == 2

def test_risk_evidence_uses_risk_text_as_query():
    assert build_evidence_query("违约金过高", "每日1%") == "违约金过高 每日1%"

def test_scalar_accuracy_uses_gold_labels():
    assert scalar_accuracy(["甲公司"], ["甲公司"]) == 1.0

def test_runtime_is_offline_when_health_request_fails():
    assert probe_runtime(lambda: (_ for _ in ()).throw(OSError())).status == "offline"
```

- [ ] **Step 4：逐个运行并记录预期失败原因**

Run: `pytest tests/test_batch_service.py tests/test_audit_evidence.py tests/test_element_metrics.py tests/test_runtime_status.py -q`

Expected: FAIL，均因目标模块尚未创建。

## Task 2：修复风险级法规证据链

**Files:**
- Create: `backend/app/services/audit/evidence.py`
- Modify: `backend/app/services/audit/auditor.py`
- Test: `backend/tests/test_audit_evidence.py`

- [ ] **Step 1：实现稳定的风险查询构造器**

```python
def build_evidence_query(category: str, original_text: str) -> str:
    return " ".join(part.strip() for part in (category, original_text[:240]) if part.strip())
```

- [ ] **Step 2：为每条风险单独检索并生成受控依据**

```python
def bind_risk_evidence(risk: dict, search=retrieve, top_k: int = 3) -> dict:
    sources = search(build_evidence_query(risk["category"], risk["original_text"]), top_k=top_k)
    risk["rag_sources"] = sources
    risk["basis"] = "；".join(f"{x['content']}（依据：{x['source']}）" for x in sources) or "未检索到可靠依据，必须人工复核"
    return risk
```

- [ ] **Step 3：移除 Agent 级来源向所有风险复制的逻辑**

`auditor._agent_audit()` 仍可把主题检索结果作为模型上下文，但正式 `rag_sources` 和 `basis` 必须由 `bind_risk_evidence()` 覆盖。

- [ ] **Step 4：运行证据测试和 RAG 回归测试**

Run: `pytest tests/test_audit_evidence.py tests/test_rag_hybrid.py -q`

Expected: PASS。

## Task 3：建立持久化批次域

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/db/init_db.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/<revision>_add_audit_batches.py`
- Create: `backend/app/schemas/batch.py`
- Create: `backend/app/services/batch/__init__.py`
- Create: `backend/app/services/batch/service.py`
- Test: `backend/tests/test_batch_service.py`

- [ ] **Step 1：为批次和批次项定义状态枚举与汇总用例**

状态仅允许 `queued/running/done/partial_failed/failed`；批次项仅允许 `queued/parsing/auditing/done/failed`。

- [ ] **Step 2：新增持久化模型**

```python
class AuditBatch(Base):
    __tablename__ = "audit_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    department: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

`AuditBatchItem` 保存 `batch_id/contract_id/filename/status/error/task_id/attempts/started_at/finished_at`，并对 `(batch_id, contract_id)` 建唯一约束。

- [ ] **Step 3：实现状态聚合、合法流转和幂等重试**

```python
ALLOWED_TRANSITIONS = {
    "queued": {"parsing", "failed"},
    "parsing": {"auditing", "failed"},
    "auditing": {"done", "failed"},
    "failed": {"queued"},
    "done": set(),
}
```

- [ ] **Step 4：运行批次服务测试**

Run: `pytest tests/test_batch_service.py -q`

Expected: PASS，覆盖正常、部分失败、非法流转和失败重试。

- [ ] **Step 5：建立正式迁移并验证升级/回滚**

SQLite 继续用于本地开发；PostgreSQL 交付环境通过 Alembic 创建批次表、索引和唯一约束。使用临时数据库执行 `upgrade head -> downgrade -1 -> upgrade head`，禁止拿生产数据验证迁移。

## Task 4：接通 Celery 批处理与任务查询

**Files:**
- Modify: `backend/app/tasks/audit_tasks.py`
- Create: `backend/app/api/v1/endpoints/batches.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/app/api/v1/endpoints/contracts.py`
- Modify: `docker-compose.yml`
- Test: `backend/tests/test_batch_api.py`

- [ ] **Step 1：先写 50 项创建、部门隔离、幂等提交、失败重试和任务参数测试**

```python
def test_audit_task_accepts_dimensions():
    assert run_contract_audit.run(contract_id=1, dimensions=["legal"]) is not None
```

- [ ] **Step 2：统一任务签名**

```python
@celery_app.task(bind=True, max_retries=3, name="audit.run_contract")
def run_contract_audit(self, contract_id: int, dimensions: list[str] | None = None, batch_item_id: int | None = None) -> dict:
    ...
```

- [ ] **Step 3：新增批次接口**

```text
POST /api/v1/batches                 创建批次并保存文件
GET  /api/v1/batches/{batch_id}      查询真实进度
POST /api/v1/batches/{batch_id}/retry 仅重试失败项
```

创建请求最多 200 份、至少 1 份；文件只在请求阶段校验和加密落盘，解析与审查全部转交 worker。客户端提交 `Idempotency-Key`，同一用户重复提交返回原批次；数据库唯一约束负责并发兜底。

若任一文件校验、落盘或数据库提交失败，必须回滚本次批次并清理本请求已创建的加密文件；不得删除既有合同文件。worker 超时或进程重启后，租约过期项可被重新入队，且同一批次项最多只有一个有效执行租约。

- [ ] **Step 4：补齐 Redis 与 worker 部署**

`docker-compose.yml` 新增 `redis` 和 `worker`，worker 使用与 backend 相同镜像和存储卷，`AUDIT_ASYNC=true`；健康检查覆盖 Redis ping 和 Celery inspect ping。

- [ ] **Step 5：运行 API 与任务回归测试**

Run: `pytest tests/test_batch_api.py tests/test_batch_service.py -q`

Expected: PASS。

## Task 5：前端展示真实批次状态

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/api/batches.ts`
- Create: `frontend/src/stores/batch.ts`
- Modify: `frontend/src/views/AuditView.vue`
- Test: `frontend/tests/batch-store.spec.ts`

- [ ] **Step 1：前端测试依赖审批门槛**

当前项目没有 `test` 脚本和 Vitest。安装前检查 npm 官方来源、锁定版本、传递依赖和已知漏洞；未获用户确认不得修改依赖或安装。

- [ ] **Step 2：写轮询停止和失败重试测试**

```typescript
it('stops polling when every item is terminal', async () => {
  const store = createBatchStore(fakeApi([{ status: 'done' }, { status: 'failed' }]))
  await store.pollOnce(1)
  expect(store.polling).toBe(false)
})
```

- [ ] **Step 3：用服务端批次替换前端串行审查**

删除 `for (const cid of batchSuccessIds)`；上传后保存 `batchId`，每 1500ms 查询一次，终态停止，页面刷新后从路由参数恢复批次。

- [ ] **Step 4：显示 queued/parsing/auditing/done/failed 真实状态和失败原因**

- [ ] **Step 5：运行前端测试、类型检查和构建**

Run: `npm.cmd run test -- batch-store.spec.ts`

Run: `npm.cmd run type-check`

Run: `npm.cmd run build`

Expected: 全部退出码 0。

## Task 6：补齐报表数据隔离

**Files:**
- Modify: `backend/app/services/report/exporter.py`
- Modify: `backend/app/api/v1/endpoints/reports.py`
- Test: `backend/tests/test_report_scope.py`

- [ ] **Step 1：写 business 只能看到本部门数据的失败测试**

- [ ] **Step 2：所有报表查询显式接收 `department_scope`**

```python
def department_scope_for(user: User) -> str | None:
    return user.department if user.role == "business" else None
```

`summary/metadata/export` 三条路径必须应用相同过滤器，传入越权 `contract_ids` 返回 403 而非静默忽略。

- [ ] **Step 3：运行报表权限测试**

Run: `pytest tests/test_report_scope.py -q`

Expected: PASS。

## Task 7：增加离线 OCR 降级通道

**Files:**
- Create: `backend/app/services/parser/ocr.py`
- Modify: `backend/app/services/parser/extractor.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/Dockerfile`
- Test: `backend/tests/test_parser_contracts.py`

- [ ] **Step 1：依赖审批门槛**

候选：RapidOCR（Apache-2.0）+ ONNX Runtime（MIT）。安装前检查 PyPI 来源、锁定版本、传递依赖和已知漏洞；未获用户确认不得修改 requirements 或安装。

- [ ] **Step 2：定义 OCR 协议和质量结果**

```python
@dataclass(frozen=True)
class OCRResult:
    text: str
    page_count: int
    mean_confidence: float

class OCREngine(Protocol):
    def recognize(self, image: bytes) -> tuple[str, float]: ...
```

- [ ] **Step 3：仅在文本为空或仍为乱码时触发 OCR**

限制最大页数、单页像素和总耗时；低于置信度阈值时保留文本但返回人工核对警告，不得写成“未发现风险”。

- [ ] **Step 4：运行文本 PDF、扫描 PDF、混合 PDF、超限和低置信度测试**

Run: `pytest tests/test_parser_contracts.py -q`

Expected: PASS。

## Task 8：建立要素准确率评测

**Files:**
- Create: `backend/evaluation/__init__.py`
- Create: `backend/evaluation/elements.py`
- Create: `backend/evaluation/cli.py`
- Create: `backend/evaluation/schema.json`
- Create: `backend/tests/test_element_metrics.py`
- Create: `docs/evaluation/element-accuracy-protocol.md`

- [ ] **Step 1：定义冻结清单格式**

每条 JSONL 包含 `case_id/file/contract_type/document_kind/gold/reviewer/version`；`gold` 至少包含甲方、乙方、标的、金额、期限、付款节点。

- [ ] **Step 2：实现标量字段规范化与多值字段 P/R/F1**

总体采用字段宏平均，不允许用高频字段加权；空值仅在金标准也为空时计正确。

- [ ] **Step 3：输出 JSON 与 CSV 原始结果**

必须包含总体、各字段、各合同类型、PDF/DOCX/扫描件分组、错误案例和样本版本哈希。

- [ ] **Step 4：运行指标单测**

Run: `pytest tests/test_element_metrics.py -q`

Expected: PASS。

## Task 9：建立 OpenClaw/GPU 可复现实验

**Files:**
- Create: `backend/evaluation/benchmark.py`
- Create: `backend/evaluation/runtime_client.py`
- Create: `backend/app/api/v1/endpoints/runtime.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `frontend/src/api/runtime.ts`
- Modify: `frontend/src/components/layout/OpenClawBadge.vue`
- Modify: `frontend/src/views/AdminView.vue`
- Test: `backend/tests/test_runtime_status.py`
- Test: `backend/tests/test_benchmark_stats.py`

- [ ] **Step 1：用真实健康接口替换演示 Store**

状态包括 `online/offline/unknown`，并返回 provider、model、最近探测时间和不含密钥的端点标识。

- [ ] **Step 2：实现同口径基准配置**

OpenClaw 和 GPU 必须使用同一模型哈希、提示词版本、数据集哈希、上下文长度、并发和输出结构；预热 3 次，正式 5 轮。

- [ ] **Step 3：计算 P50、P95、吞吐、成功率、均值、标准差和 95% 置信区间**

- [ ] **Step 4：能耗只接收真实采样值**

基准工具接受功率计或设备导出的时间序列 CSV；缺少能耗数据时报告写 `not_measured`，禁止估算成实测值。

- [ ] **Step 5：运行统计与健康检查测试**

Run: `pytest tests/test_runtime_status.py tests/test_benchmark_stats.py -q`

Expected: PASS。

## Task 10：企业交付验收

**Files:**
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Modify: `PROGRESS.md`
- Create: `docs/evaluation/hard-indicator-matrix.md`
- Create: `backend/tests/test_hard_indicator_smoke.py`

- [ ] **Step 1：运行后端完整测试**

Run: `pytest tests -q`

Expected: 0 failed，且不再存在恒真占位测试。

- [ ] **Step 2：运行前端完整验证**

Run: `npm.cmd run test`

Run: `npm.cmd run type-check`

Run: `npm.cmd run build`

Expected: 全部退出码 0。

- [ ] **Step 3：执行 52 文件批次验收**

固定 50 份有效文件 + 2 份异常文件，验证成功率、失败隔离、刷新恢复和失败重试。未实际执行不得勾选。

- [ ] **Step 4：执行准确率和 OpenClaw/GPU 实验**

缺少人工标注集、OpenClaw 实机、GPU 对照机或功率数据时，矩阵明确标记阻塞，不生成虚假结论。

- [ ] **Step 5：浏览器验证正常、空、错、移动端和批次恢复路径**

使用 Playwright 保存截图与控制台日志，确认 0 console error 和无敏感信息泄漏。

## 自检结果

- 赛题七项要求均有对应任务。
- 生产代码修改均排在失败测试之后。
- OCR 安装、人工标注集和真实硬件测试均设置了明确门槛。
- Vitest 安装和部署配置修改均需在实际执行前获得明确确认。
- PostgreSQL 交付通过可回滚 Alembic 迁移，不依赖 `create_all`。
- 批次提交覆盖幂等、事务回滚、加密文件清理和 worker 重启恢复。
- 不使用模拟调用日志作为准确率、吞吐或能效证据。
- 本计划不包含 SSO、多租户、ERP、电子签章等方案 A 之外的扩展。
