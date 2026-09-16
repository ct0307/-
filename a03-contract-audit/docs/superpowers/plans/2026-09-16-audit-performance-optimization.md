# Contract Audit Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持风险、证据授权、人工复核和法务→财务依赖不变的前提下，通过批量化、加密解析缓存、RAG 快照和受控并发减少合同审查时间。

**Architecture:** 批量协议按稳定 ID 逐项校验，失败项回退到现有单条路径。解析缓存以文件哈希和解析签名为身份，RAG 快照以数据库修订号失效；并发工作单元不写数据库，由调度线程顺序发布。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy、Alembic、Pydantic、NumPy、rank-bm25、Celery、SQLite/PostgreSQL、pytest。

---

## File Structure

| 路径 | 职责 |
|---|---|
| `backend/app/services/audit/protocol.py` | 批量 enrichment 和二次复核严格协议 |
| `backend/app/services/audit/review_pipeline.py` | 同窗口批量 enrichment 与部分回退 |
| `backend/app/services/audit/secondary_review.py` | 二次复核分批和逐 claim 证据校验 |
| `backend/app/services/parser/cache.py` | `DocumentParseResult` 序列化、签名、加密缓存与回退 |
| `backend/app/services/rag/revision.py` | 知识修订号查询和事务内递增 |
| `backend/app/services/rag/snapshot.py` | 不可变检索快照和单飞重建 |
| `backend/app/services/rag/retriever.py` | 消费快照，保持检索排序语义 |
| `backend/app/services/audit/window_repository.py` | 批量持久化工作线程返回的观测与检查点 |
| `backend/app/services/audit/auditor.py` | 每 Agent 内的窗口调度和法务→财务屏障 |
| `backend/app/models/models.py` | 解析缓存与知识修订 ORM |
| `backend/app/core/config.py` | 批量开关和 1–3 并发参数 |
| `backend/alembic/versions/20260916_02_audit_performance_caches.py` | 生产迁移 |
| `backend/app/db/init_db.py` | SQLite 轻量迁移 |
| `backend/evaluation/audit_performance.py` | 同样本前后调用量、耗时和质量摘要 |

### Task 1: 批量协议与稳定候选 ID

**Files:**
- Modify: `backend/app/services/audit/protocol.py`
- Modify: `backend/app/services/audit/review_pipeline.py`
- Test: `backend/tests/test_audit_protocol.py`
- Test: `backend/tests/test_review_pipeline.py`

- [ ] **Step 1: Write failing protocol tests**

```python
def test_enrichment_batch_accepts_five_unique_items():
    payload = {"items": [{"candidate_id": f"c{i:07d}", "reason": "风险原因", "suggestion": "修改建议"} for i in range(5)]}
    assert len(parse_risk_enrichment_batch(json.dumps(payload, ensure_ascii=False)).items) == 5

def test_enrichment_batch_rejects_six_items_or_duplicate_ids():
    six = {"items": [{"candidate_id": f"c{i:07d}", "reason": "风险原因", "suggestion": "修改建议"} for i in range(6)]}
    duplicate = {"items": [
        {"candidate_id": "candidate-1", "reason": "原因一", "suggestion": "建议一"},
        {"candidate_id": "candidate-1", "reason": "原因二", "suggestion": "建议二"},
    ]}
    with pytest.raises(ValueError):
        parse_risk_enrichment_batch(json.dumps(six, ensure_ascii=False))
    with pytest.raises(ValueError):
        parse_risk_enrichment_batch(json.dumps(duplicate, ensure_ascii=False))
```

添加 `candidate_id(window_id, finding)` 确定性测试，确认 ID 不包含合同正文。

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_audit_protocol.py tests/test_review_pipeline.py -k "enrichment_batch or candidate_id" -q`

- [ ] **Step 3: Add strict batch models**

```python
class RiskEnrichmentItem(RiskEnrichment):
    candidate_id: str = Field(min_length=8, max_length=64)

class RiskEnrichmentBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    items: list[RiskEnrichmentItem] = Field(min_length=1, max_length=5)

def enrichment_candidate_id(window_id: str, finding: RiskFinding) -> str:
    payload = f"{window_id}\0{finding.category}\0{finding.quote}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
```

`RiskEnrichmentBatch` 增加 model validator 禁止重复 ID。保留现有单条 `RiskEnrichment` 与旧响应解析，作为回退协议。

- [ ] **Step 4: Verify GREEN**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_audit_protocol.py tests/test_review_pipeline.py -k "enrichment_batch or candidate_id" -q`

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/audit/protocol.py backend/app/services/audit/review_pipeline.py backend/tests/test_audit_protocol.py backend/tests/test_review_pipeline.py
git commit -m "feat: define batched audit protocols"
```

### Task 2: 二次复核批量化

**Files:**
- Modify: `backend/app/services/audit/secondary_review.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/test_secondary_review.py`

- [ ] **Step 1: Write failing batch and partial-fallback tests**

```python
def test_five_secondary_candidates_use_one_model_call():
    adapter = QueueAdapter([response_with_decisions(*claims)])
    result = reviewer(adapter).review(risks=risks, conflict_claim_ids=set())
    assert adapter.calls == 1
    assert set(result.by_claim) == set(claims)

def test_missing_secondary_decision_retries_only_missing_claim():
    adapter = QueueAdapter([response_with_decisions(*claims[:4]), response_with_decisions(claims[4])])
    result = reviewer(adapter).review(risks=risks, conflict_claim_ids=set())
    assert adapter.calls == 2
```

添加跨 claim 证据、重复 claim、未知 claim、批量截断、回退超时和部分成功用例。

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_secondary_review.py -k "batch or missing or cross_claim" -q`

- [ ] **Step 3: Add the rollout flag**

```python
AUDIT_BATCH_SECONDARY_ENABLED: bool = False
```

`.env.example` 显式列出 `AUDIT_BATCH_SECONDARY_ENABLED=false`，在真实模型 A/B 通过前不把批量路径设为生产默认。

- [ ] **Step 4: Implement chunking, exact-set validation, and fallback**

`review()` 将 selected 按 5 分批。`_review_batch()` 构建每 claim 独立 `authorized_evidence`，返回 `dict[claim_id, SecondaryOutcome]` 和失败 claim ID。验证顺序为：请求集合成员、唯一性、verdict/reason 映射、confirm 非空证据、证据属于该 claim。失败 ID 逐条调用现有 `_review_one()`。

- [ ] **Step 5: Verify legacy and batch paths**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_secondary_review.py tests/test_audit_protocol.py -q`

Expected: flag off retains one-call-per-claim behavior; flag on passes all batch, evidence and fallback tests.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/audit/secondary_review.py backend/app/core/config.py backend/.env.example backend/tests/test_secondary_review.py
git commit -m "feat: batch secondary audit review"
```

### Task 3: 同窗口 enrichment 批量化

**Files:**
- Modify: `backend/app/services/audit/review_pipeline.py`
- Modify: `backend/app/services/audit/auditor.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/test_review_pipeline.py`
- Test: `backend/tests/test_audit_runner_quality.py`

- [ ] **Step 1: Write failing same-window batch tests**

测试 5 个 finding 只调用一次、6 个拆成 5+1、两个窗口永远不合并、合同窗口正文每批只出现一次、缺失项仅单条回退。

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_review_pipeline.py -k "batch_enrichment or same_window or missing_item" -q`

- [ ] **Step 3: Add the rollout flag and batch prompt contract**

```python
AUDIT_BATCH_ENRICHMENT_ENABLED: bool = False
```

`WindowReviewRequest` 增加 `build_enrichment_batch_prompt: Callable[[ReviewWindow, tuple[RiskFinding, ...], bool], str] | None`。提示词只包含一次 `window.text`，候选列表每项包含 `candidate_id/category/quote`。

- [ ] **Step 4: Implement per-item validation and single-item fallback**

`_review_two_stage_uncached()` 先收集当页新 finding，再按 5 传入 `_review_enrichment_batch()`。已验证项直接转为 `ReviewedRiskCandidate`；无效或缺失项才调用 `_review_enrichment()`。如果截止时间已到，不启动回退请求并返回既有部分结果与问题。

- [ ] **Step 5: Verify all pipeline reliability behavior**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_review_pipeline.py tests/test_audit_runner_quality.py -q`

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/audit/review_pipeline.py backend/app/services/audit/auditor.py backend/app/core/config.py backend/.env.example backend/tests/test_review_pipeline.py backend/tests/test_audit_runner_quality.py
git commit -m "feat: batch risk enrichment per window"
```

### Task 4: 解析缓存模型、序列化和签名

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/db/init_db.py`
- Create: `backend/alembic/versions/20260916_02_audit_performance_caches.py`
- Create: `backend/app/services/parser/cache.py`
- Create: `backend/tests/test_parse_cache.py`
- Modify: `backend/tests/test_db_migrations.py`

- [ ] **Step 1: Write failing serialization and invalidation tests**

```python
def test_parse_result_round_trip_preserves_blocks_and_anchors():
    restored = deserialize_parse_result(serialize_parse_result(parsed))
    assert restored == parsed

def test_parser_signature_changes_with_code_or_ocr_parameters(monkeypatch):
    baseline = build_parser_signature()
    monkeypatch.setattr(cache, "OCR_MAX_PAGES", cache.OCR_MAX_PAGES + 1)
    assert build_parser_signature() != baseline
```

添加密钥不匹配、载荷损坏、未知 schema version、并发 upsert 唯一性测试。

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_parse_cache.py tests/test_db_migrations.py -q`

- [ ] **Step 3: Add the one-to-one cache model and migrations**

```python
class ContractParseCache(Base):
    __tablename__ = "contract_parse_caches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), unique=True, index=True)
    content_sha256: Mapped[str] = mapped_column(String(64))
    parser_signature: Mapped[str] = mapped_column(String(64))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

Alembic 和 `init_db.py` 创建同构表和唯一索引；降级只删除缓存表。

- [ ] **Step 4: Implement versioned encrypted serialization**

```python
_PARSE_CACHE_SCHEMA = 1

def serialize_parse_result(parsed: DocumentParseResult) -> bytes:
    raw = json.dumps({"schema": _PARSE_CACHE_SCHEMA, "result": asdict(parsed)}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return encrypt_bytes(raw)
```

`deserialize_parse_result()` 严格校验 schema、source、block type、anchor 数值与 tuple 结构。`build_parser_signature()` 组合 schema、三个解析模块文件 SHA-256、OCR 常量和通过 `importlib.metadata.version()` 获取的 `pdfplumber/PyMuPDF/python-docx/pytesseract` 版本。

- [ ] **Step 5: Implement safe lookup and atomic upsert**

`get_cached_parse(db, contract)` 仅在合同 ID、内容哈希、解析签名一致时返回。任何解密或校验异常记录类型名后返回 `None`。`save_parse_cache()` 按 `contract_id` 更新或插入，唯一冲突时重读并更新，不记录 payload。

- [ ] **Step 6: Verify GREEN**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_parse_cache.py tests/test_db_migrations.py -q`

- [ ] **Step 7: Commit**

```powershell
git add backend/app/models/models.py backend/app/db/init_db.py backend/alembic/versions/20260916_02_audit_performance_caches.py backend/app/services/parser/cache.py backend/tests/test_parse_cache.py backend/tests/test_db_migrations.py
git commit -m "feat: cache encrypted parse results"
```

### Task 5: 在上传、导入和审查中复用解析缓存

**Files:**
- Modify: `backend/app/api/v1/endpoints/contracts.py`
- Modify: `backend/app/tasks/import_tasks.py`
- Modify: `backend/app/services/audit/runner.py`
- Test: `backend/tests/test_contract_quality_api.py`
- Test: `backend/tests/test_import_tasks.py`
- Test: `backend/tests/test_audit_runner_quality.py`

- [ ] **Step 1: Write failing call-count tests**

上传/导入解析后执行审查，将 `extract_document` 设为若再调用就失败的 spy，断言审查从缓存还原。内容哈希或 parser signature 不同时断言恰好重新解析一次。

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_contract_quality_api.py tests/test_import_tasks.py tests/test_audit_runner_quality.py -k "parse_cache" -q`

- [ ] **Step 3: Save cache in every successful parse entry point**

在单份/批量上传和异步导入完成 `DocumentParseResult` 校验后，在同一合同事务中调用 `save_parse_cache()`。解析失败时不写入缓存。

- [ ] **Step 4: Read cache in the audit runner**

`_compute_audit()` 先通过 contract ID 查找完整 Contract，再执行 `get_cached_parse()`；未命中时调用 `extract_document()` 并更新缓存。`parse_ms` 覆盖缓存查找或重新解析的总时间，另增安全布尔观测 `parse_cache_hit`。

- [ ] **Step 5: Verify all call sites and quality metadata**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_contract_quality_api.py tests/test_import_tasks.py tests/test_audit_runner_quality.py tests/test_element_evidence_persistence.py -q`

- [ ] **Step 6: Commit**

```powershell
git add backend/app/api/v1/endpoints/contracts.py backend/app/tasks/import_tasks.py backend/app/services/audit/runner.py backend/tests/test_contract_quality_api.py backend/tests/test_import_tasks.py backend/tests/test_audit_runner_quality.py
git commit -m "feat: reuse parsed contracts during audit"
```

### Task 6: 知识库修订号与写入覆盖

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/db/init_db.py`
- Modify: `backend/alembic/versions/20260916_02_audit_performance_caches.py`
- Create: `backend/app/services/rag/revision.py`
- Modify: `backend/app/services/rag/legal_import.py`
- Modify: `backend/app/services/rag/legal_sync.py`
- Modify: `backend/app/api/v1/endpoints/knowledge.py`
- Create: `backend/tests/test_rag_revision.py`
- Test: `backend/tests/test_rag_legal_retrieval.py`

- [ ] **Step 1: Write failing transactional revision tests**

```python
def test_knowledge_write_and_revision_commit_together(db):
    before = current_knowledge_revision(db)
    import_fixture(db)
    assert current_knowledge_revision(db) == before + 1

def test_rollback_does_not_publish_revision(db):
    before = current_knowledge_revision(db)
    with pytest.raises(RuntimeError): mutate_then_fail(db)
    db.rollback()
    assert current_knowledge_revision(db) == before
```

对单文件导入、批量导入、同步、按 source 替换、单 chunk 删除各写一个修订增量断言。

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_rag_revision.py -q`

- [ ] **Step 3: Add singleton state and row-locked bump**

```python
class KnowledgeIndexState(Base):
    __tablename__ = "knowledge_index_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

def bump_knowledge_revision(db: Session) -> int:
    row = db.execute(select(KnowledgeIndexState).where(KnowledgeIndexState.id == 1).with_for_update()).scalar_one()
    row.revision += 1
    return row.revision
```

迁移和 `init_db.py` 始终种入 `id=1, revision=0`。

- [ ] **Step 4: Cover every write transaction**

在知识变更完成且调用方 commit 之前恰好 bump 一次。接受 `commit=False` 的底层导入函数不自行 commit，只在同一 session 中 bump，由上层统一提交或回滚。

- [ ] **Step 5: Verify write coverage**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_rag_revision.py tests/test_rag_legal_retrieval.py tests/test_legal_import.py -q`

- [ ] **Step 6: Commit**

```powershell
git add backend/app/models/models.py backend/app/db/init_db.py backend/alembic/versions/20260916_02_audit_performance_caches.py backend/app/services/rag/revision.py backend/app/services/rag/legal_import.py backend/app/services/rag/legal_sync.py backend/app/api/v1/endpoints/knowledge.py backend/tests/test_rag_revision.py backend/tests/test_rag_legal_retrieval.py
git commit -m "feat: version knowledge index mutations"
```

### Task 7: RAG 不可变快照

**Files:**
- Create: `backend/app/services/rag/snapshot.py`
- Modify: `backend/app/services/rag/retriever.py`
- Create: `backend/tests/test_rag_snapshot.py`
- Test: `backend/tests/test_rag_hybrid.py`
- Test: `backend/tests/test_rag_retrieval_fixes_20260915.py`

- [ ] **Step 1: Write failing reuse, invalidation, and equivalence tests**

统计全量 rows 查询和 `_parse_stored_vector()` 调用次数：同一 revision 连续 10 次 retrieve 应各发生 1 次；revision+1 后恰好重建 1 次。将缓存与强制数据库路径的返回 JSON 作完全相等比较。

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_rag_snapshot.py -q`

- [ ] **Step 3: Implement immutable snapshot types**

```python
@dataclass(frozen=True)
class RetrievalSnapshot:
    revision: int
    docs: tuple[tuple, ...]
    bm25: object
    bm25_doc_ids: tuple[int, ...]
    vector_doc_ids: tuple[int, ...]
    vector_matrix: np.ndarray
```

`vector_matrix.setflags(write=False)`；docs 不包含 ORM 对象。`SnapshotStore` 使用 `threading.Lock` 保证单飞重建，只在完整构建后替换 `_current`。

- [ ] **Step 4: Route retrieve through the snapshot**

`retrieve()` 先用短 session 读 revision，获取 snapshot 后才执行作用域过滤、BM25 和向量计分。快照获取失败时调用 `_load_docs_uncached()` 保持旧路径。查询 embedding 仍每次生成，不缓存用户查询文本。

- [ ] **Step 5: Verify ranking and trace parity**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_rag_snapshot.py tests/test_rag_hybrid.py tests/test_rag_retrieval_fixes_20260915.py tests/test_rag_grounding.py -q`

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/rag/snapshot.py backend/app/services/rag/retriever.py backend/tests/test_rag_snapshot.py backend/tests/test_rag_hybrid.py backend/tests/test_rag_retrieval_fixes_20260915.py
git commit -m "perf: reuse versioned rag snapshots"
```

### Task 8: 窗口并发计算与主线程单写入

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/app/services/audit/window_repository.py`
- Modify: `backend/app/services/audit/review_pipeline.py`
- Modify: `backend/app/services/audit/auditor.py`
- Test: `backend/tests/test_audit_window_repository.py`
- Test: `backend/tests/test_review_pipeline.py`
- Test: `backend/tests/test_audit_runner_quality.py`
- Create: `backend/tests/test_audit_window_concurrency.py`

- [ ] **Step 1: Write failing deterministic-concurrency tests**

```python
def test_two_windows_overlap_but_persist_in_source_order(tmp_path):
    adapter = BlockingAdapter()
    result = run_agent_with_concurrency(2, windows=[first, second], adapter_factory=adapter.factory)
    assert adapter.max_active == 2
    assert persisted_window_ids == [first.window_id, second.window_id]
    assert [r["source_window_id"] for r in result.risks] == [first.window_id, second.window_id]
```

增加法务未完成时财务不启动、并发度 1/2 结果一致、全局 deadline、任意窗口失败保留其他已验证结果测试。

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_audit_window_concurrency.py -q`

- [ ] **Step 3: Add bounded configuration**

```python
AUDIT_MODEL_CONCURRENCY: int = Field(default=2, ge=1, le=3)
```

`.env.example` 列出 `AUDIT_MODEL_CONCURRENCY=2`。

- [ ] **Step 4: Introduce buffered worker observations**

`BufferedWindowCheckpoint` 在内存中实现 `load_valid/record_call/save_valid`，收集 `WindowCallObservation` 与最终 result，不打开 DB session。`SqlAlchemyWindowCheckpoint.flush_execution(request, execution)` 由调度线程使用独立短事务按调用顺序写入观测，再保存 valid 检查点。

- [ ] **Step 5: Schedule independent windows with isolated adapters**

`_agent_audit()` 先在主线程按顺序查询已有检查点；未命中窗口提交到 `ThreadPoolExecutor(max_workers=min(settings.AUDIT_MODEL_CONCURRENCY, len(pending)))`。每个 worker 调用 `get_llm_adapter()` 创建独立 adapter。主线程按原窗口序号取结果、flush、更新进度和合并风险。

- [ ] **Step 6: Add real SQLite contention coverage**

使用 `tmp_path` 真实 SQLite 文件、`check_same_thread=False`、2 个工作窗口和同一审查任务，断言无未处理 `OperationalError`、无重复 `AuditWindowRun`、无重复最终风险。该测试必须实际执行并发，不只构造错误字符串。

- [ ] **Step 7: Verify concurrency and all window reliability tests**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_audit_window_concurrency.py tests/test_audit_window_repository.py tests/test_review_pipeline.py tests/test_audit_runner_quality.py -q`

- [ ] **Step 8: Commit**

```powershell
git add backend/app/core/config.py backend/.env.example backend/app/services/audit/window_repository.py backend/app/services/audit/review_pipeline.py backend/app/services/audit/auditor.py backend/tests/test_audit_window_repository.py backend/tests/test_review_pipeline.py backend/tests/test_audit_runner_quality.py backend/tests/test_audit_window_concurrency.py
git commit -m "perf: review independent windows concurrently"
```

### Task 9: 性能与质量双门禁

**Files:**
- Create: `backend/evaluation/audit_performance.py`
- Create: `backend/tests/test_audit_performance.py`
- Modify: `backend/evaluation/cli.py`
- Modify: `backend/tests/test_evaluation_cli.py`

- [ ] **Step 1: Write failing metric aggregation tests**

```python
def test_performance_report_separates_speed_and_quality():
    report = compare_runs(baseline, candidate)
    assert report.speed.llm_calls_delta == -8
    assert report.quality.unauthorized_evidence_count == 0
    assert report.quality.unverified_auto_publish_count == 0
```

质量摘要包含：发布风险数、高/中/低分布、证据支持状态、跨 claim 证据数、人工复核数、未验证自动发布数。性能摘要包含：总时长、各阶段时长、LLM 调用数/P50/P95、缓存命中和回退数。

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_audit_performance.py tests/test_evaluation_cli.py -q`

- [ ] **Step 3: Implement deterministic report generation**

CLI 接受两个已有基准运行 JSON/JSONL 路径，输出结构化 JSON 和简短 Markdown。报告只计算已提供的实测数据，不补齐或推测缺失指标。

- [ ] **Step 4: Verify GREEN**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_audit_performance.py tests/test_evaluation_cli.py -q`

- [ ] **Step 5: Commit**

```powershell
git add backend/evaluation/audit_performance.py backend/tests/test_audit_performance.py backend/evaluation/cli.py backend/tests/test_evaluation_cli.py
git commit -m "test: add audit performance quality gate"
```

### Task 10: 分层回归和完整验收

**Files:**
- Update: `.planning/audit-speed-ingestion-hardening/progress.md`

- [ ] **Step 1: Run protocol, batching, cache, RAG, and concurrency tests**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_audit_protocol.py tests/test_secondary_review.py tests/test_review_pipeline.py tests/test_parse_cache.py tests/test_rag_revision.py tests/test_rag_snapshot.py tests/test_rag_hybrid.py tests/test_rag_grounding.py tests/test_audit_window_repository.py tests/test_audit_window_concurrency.py tests/test_audit_runner_quality.py -q`

- [ ] **Step 2: Run the entire backend suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests -q`

- [ ] **Step 3: Run the complete project quality gate**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1`

- [ ] **Step 4: Run the same-fixture local performance comparison**

用模拟延时 adapter 和固定合成合同各运行三次，比较开关关闭/开启的调用数、并发峰值、缓存命中、风险 ID 和证据集。该结果用于验证实现，不写成真实模型性能结论。

- [ ] **Step 5: Run real-model A/B when credentials and the approved dataset are available**

在不输出 API 密钥和合同正文的前提下，使用相同合同集、模型、知识修订号和审查维度运行单条基线与批量候选。只在风险召回、错误风险、证据支持和人工复核指标通过时，才在部署配置中建议将两个批量开关设为 true。

- [ ] **Step 6: Record exact evidence and residual risks**

在 `.planning/audit-speed-ingestion-hardening/progress.md` 记录每条命令的通过数、失败数、未运行项和原因。如果无可用真实模型或获批数据集，明确标记 A/B 未完成，保持批量默认关闭。
