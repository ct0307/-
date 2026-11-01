# RAG 适用性与精排 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每条结构化 Claim 生成可审计的多路查询，增加法规时点过滤并把真实 Cross-Encoder 接入现有 RRF 检索链。

**Architecture:** 查询规划、检索执行和精排适配彼此独立。精排默认关闭，失败时保留 RRF 顺序；法规时点未知时保留候选但不得自动判定适用。

**Tech Stack:** Python 3.11、SQLAlchemy、NumPy、BM25、sentence-transformers 3.3.1、pytest。

---

## 执行约定

以下命令从仓库外层目录执行，运行 pytest 前设置 `$env:PYTHONPATH=(Resolve-Path 'a03-contract-audit/backend').Path`。只暂存当前任务 Files 清单中的本轮修改，不使用 `git add .`。阶段 1 的 `AuditClaim` 是本计划前置条件；若其测试未通过，不开始本计划。

`sentence-transformers==3.3.1` 已存在于项目依赖，但具体 Cross-Encoder 模型权重不在仓库中。未经用户确认，不下载模型、不修改依赖锁定版本；测试必须注入假模型。

## 文件结构

- Create: `backend/app/services/rag/query_planner.py`。
- Create: `backend/app/services/rag/reranker.py`。
- Create: `backend/app/services/rag/applicability.py`。
- Modify: `backend/app/services/rag/retriever.py`。
- Modify: `backend/app/services/audit/auditor.py`。
- Modify: `backend/app/core/config.py` 和 `backend/.env.example`。
- Test: `backend/tests/test_rag_query_planner.py`。
- Test: `backend/tests/test_rag_reranker.py`。
- Test: `backend/tests/test_rag_applicability.py`。
- Modify: `backend/tests/test_rag_hybrid.py` 和 `backend/tests/test_rag_grounding.py`。

### Task 1: 建立多路查询计划

- [ ] **Step 1: 写入查询分类失败测试**

```python
def test_plan_claim_builds_legal_fact_and_applicability_queries():
    claim = AuditClaim(
        agent="finance", level="medium", category="付款条件不明确",
        dimension="payment", action="支付尾款", condition="验收完成",
        consequence="支付20%合同款", quote="验收完成后支付剩余款项",
        clause_ids=["C-18"],
    )
    plan = plan_claim(claim, contract_type="采购合同")
    assert [query.kind for query in plan.queries] == [
        "legal_issue", "fact_pattern", "applicability"
    ]
    assert plan.max_rewrites == 1
    assert plan.version == "query-plan-v1"
```

- [ ] **Step 2: 运行红灯**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rag_query_planner.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现不可变查询计划**

```python
QueryKind = Literal[
    "exact_reference", "legal_issue", "fact_pattern",
    "applicability", "absence_requirement",
]

@dataclass(frozen=True)
class EvidenceQuery:
    kind: QueryKind
    text: str
    contract_type: str
    dimensions: tuple[str, ...]

@dataclass(frozen=True)
class EvidenceQueryPlan:
    claim_id: str
    queries: tuple[EvidenceQuery, ...]
    max_rewrites: int = 1
    version: str = "query-plan-v1"
```

`plan_claim()` 对精确条号只生成 `exact_reference`；缺失 Claim 使用 `absence_requirement`；普通 Claim 使用法律问题、事实模式和适用性三路，去除空查询和重复查询。

- [ ] **Step 4: 测试并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rag_query_planner.py -q`

Commit: `git commit -m "feat: add auditable evidence query plans"`

### Task 2: 建立法规适用时点判定

- [ ] **Step 1: 添加边界测试**

```python
@pytest.mark.parametrize(("effective", "expiry", "as_of", "status"), [
    (date(2021, 1, 1), None, date(2026, 1, 1), "applicable"),
    (date(2027, 1, 1), None, date(2026, 1, 1), "not_yet_effective"),
    (date(2021, 1, 1), date(2025, 12, 31), date(2026, 1, 1), "expired"),
    (date(2021, 1, 1), None, None, "unknown_as_of"),
])
def test_assess_applicability(effective, expiry, as_of, status):
    assert assess_applicability(effective, expiry, as_of).status == status
```

- [ ] **Step 2: 实现纯函数判定**

```python
@dataclass(frozen=True)
class ApplicabilityResult:
    status: Literal["applicable", "not_yet_effective", "expired", "unknown_as_of"]
    reason_code: str

def assess_applicability(effective, expiry, as_of):
    if as_of is None:
        return ApplicabilityResult("unknown_as_of", "AS_OF_DATE_UNKNOWN")
    if effective and effective > as_of:
        return ApplicabilityResult("not_yet_effective", "SOURCE_NOT_YET_EFFECTIVE")
    if expiry and expiry < as_of:
        return ApplicabilityResult("expired", "SOURCE_EXPIRED")
    return ApplicabilityResult("applicable", "SOURCE_APPLICABLE")
```

- [ ] **Step 3: 贯穿 `as_of`**

`audit_contract()` 增加仅关键字参数 `legal_as_of: date | None = None`；Runner 从已确认合同日期中选择时点并记录来源，没有可靠日期时传 `None`。`retrieve()` 继续使用显式 `as_of`，禁止在审查 grounding 路径静默回退 `date.today()`。

- [ ] **Step 4: 验证并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rag_applicability.py a03-contract-audit/backend/tests/test_rag_legal_retrieval.py a03-contract-audit/backend/tests/test_audit_runner_quality.py -q`

Commit: `git commit -m "feat: enforce legal source applicability dates"`

### Task 3: 接入可降级 Cross-Encoder

- [ ] **Step 1: 添加适配器测试，禁止真实模型下载**

```python
def test_disabled_reranker_returns_none(monkeypatch):
    monkeypatch.setattr(reranker.settings, "RERANK_BACKEND", "disabled")
    assert get_reranker() is None

def test_local_reranker_scores_in_one_batch(monkeypatch):
    class FakeCrossEncoder:
        def __init__(self):
            self.calls = []

        def predict(self, pairs):
            self.calls.append(pairs)
            return [0.2, 0.9]

    fake = FakeCrossEncoder()
    monkeypatch.setattr(reranker, "_load_cross_encoder", lambda _name: fake)
    scorer = LocalCrossEncoderReranker("test-model")
    assert scorer.score("查询", ["甲", "乙"]) == [0.2, 0.9]
    assert fake.calls == [[("查询", "甲"), ("查询", "乙")]]
```

- [ ] **Step 2: 增加默认关闭配置**

```python
RERANK_BACKEND: Literal["disabled", "local"] = "disabled"
RERANK_MODEL: str = "BAAI/bge-reranker-base"
RERANK_CANDIDATE_K: int = Field(default=30, ge=5, le=100)
```

`.env.example` 明确：启用本地模型会从 Hugging Face 下载模型；生产或比赛镜像启用前必须完成来源、许可证、文件哈希、供应链风险和离线缓存审计，并取得用户确认。

- [ ] **Step 3: 实现惰性适配器**

```python
class LocalCrossEncoderReranker:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def score(self, query: str, documents: list[str]) -> list[float]:
        if self._model is None:
            self._model = _load_cross_encoder(self.model_name)
        values = self._model.predict([(query, doc) for doc in documents])
        return [float(value) for value in values]
```

不得在模块导入、测试或默认服务启动时加载/下载模型。

- [ ] **Step 4: 将适配器接入 `retrieve()`**

`retrieve()` 对融合后的前 `RERANK_CANDIDATE_K` 个候选调用一次 `score()`，并把方法传给现有 `rerank_results()`。捕获模型加载和评分异常，记录 `rerank_error_code`，随后使用 `scorer=None` 保留 RRF 顺序。

- [ ] **Step 5: 验证并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rag_reranker.py a03-contract-audit/backend/tests/test_rag_hybrid.py a03-contract-audit/backend/tests/test_rag_retrieval_fixes_20260915.py -q`

Commit: `git commit -m "feat: wire optional local cross-encoder reranking"`

### Task 4: 集成查询计划、父法条回填和一次纠错

- [ ] **Step 1: 添加集成测试**

测试必须证明：多路查询的候选以稳定顺序去重；同一 `legal_article_id` 只占一个位置；返回 `content` 为完整父法条、`matched_content` 为命中子块；首轮不支持时只重写一次；两次失败后状态为人工复核。

- [ ] **Step 2: 实现计划执行器**

```python
@dataclass(frozen=True)
class RetrievalAttempt:
    query_kind: str
    query: str
    rewrite: int
    result_ids: tuple[str, ...]
    retrieval_mode: str
    rerank_mode: str

@dataclass(frozen=True)
class QueryPlanResult:
    sources: tuple[dict, ...]
    attempts: tuple[RetrievalAttempt, ...]
    support_status: str

def execute_query_plan(plan, search, validate, rewrite):
    attempts: list[RetrievalAttempt] = []
    merged: list[dict] = []
    seen: set[str] = set()

    def run(query: EvidenceQuery, rewrite_number: int) -> None:
        results = search(query)
        for item in results:
            key = str(item.get("chunk_id") or item.get("source"))
            if key not in seen:
                seen.add(key)
                merged.append(item)
        trace = results[0].get("retrieval_trace", {}) if results else {}
        attempts.append(RetrievalAttempt(
            query_kind=query.kind,
            query=query.text,
            rewrite=rewrite_number,
            result_ids=tuple(str(item.get("chunk_id")) for item in results),
            retrieval_mode=str(results[0].get("retrieval_mode", "none")) if results else "none",
            rerank_mode=str(trace.get("rerank_mode", "none")),
        ))

    for query in plan.queries:
        run(query, 0)
    validation = validate(merged)
    if validation.status == "supported" or plan.max_rewrites == 0:
        return QueryPlanResult(tuple(merged), tuple(attempts), validation.status)

    for query in plan.queries:
        rewritten = rewrite(query, validation.reason_code)
        if rewritten is not None and rewritten.text != query.text:
            run(rewritten, 1)
    validation = validate(merged)
    return QueryPlanResult(tuple(merged), tuple(attempts), validation.status)
```

`rewrite()` 只接受受控失败原因码并返回 `EvidenceQuery | None`；不得根据模型自由文本无限生成查询。

- [ ] **Step 3: 替换 `_ground_risks()` 的字符串拼接查询**

保留现有 `retrieval_attempts` API 字段，但每项增加 `query_kind`、`rewrite`、`routes`、`rerank_mode`、`applicability_status`。旧客户端忽略新增键。

- [ ] **Step 4: 回归与提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rag_query_planner.py a03-contract-audit/backend/tests/test_rag_grounding.py a03-contract-audit/backend/tests/test_rag_evidence_persistence.py a03-contract-audit/backend/tests/test_rag_hybrid.py -q`

Commit: `git commit -m "feat: execute claim-aware retrieval plans"`

### Task 5: RAG 阶段验收

- [ ] Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rag_hybrid.py a03-contract-audit/backend/tests/test_rag_legal_retrieval.py a03-contract-audit/backend/tests/test_retrieval_metrics.py a03-contract-audit/backend/tests/test_evaluation_cli.py -q`
- [ ] Run: `git diff --check`
- [ ] 使用同一金标生成 BM25、RRF 和 RRF+Cross-Encoder 三组预测；没有经过审计的本地模型时只完成前两组，并明确标记精排未实测。
- [ ] Commit: `git commit -m "test: verify applicable reranked retrieval"`
