# Full Civil Code Frontend Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员从现有知识库导入弹窗上传官方《民法典》文件，完成 1260 条校验、父子切片、Embedding、原子替换和可视化验收。

**Architecture:** 通用文件导入保持不变；新增 `legal_import.py` 负责权威法源预检令牌和应用编排，复用 `legal_sources.py`、`legal_sync.py` 与 `retriever.py`。前端在现有弹窗内根据预检结果切换为权威法源确认视图，服务端始终重新校验文件和替换范围。

**Tech Stack:** FastAPI、SQLAlchemy、Pydantic、Python HMAC、Vue 3、TypeScript、Element Plus、pytest、Playwright

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/resources/legal_sources/manifest.json` | 将民法典受控范围声明为 1—1260 条 |
| `backend/app/services/rag/legal_import.py` | 文件识别、预览、短期令牌、应用和验收摘要 |
| `backend/app/api/v1/endpoints/knowledge.py` | 管理员预览/应用 HTTP 接口和审计入口 |
| `backend/app/services/rag/retriever.py` | 合同审查领域的 RRF 轻量加权 |
| `frontend/src/api/knowledge.ts` | 权威法源预览和应用类型及请求函数 |
| `frontend/src/views/KnowledgeView.vue` | 复用现有导入弹窗展示预览、确认、进度和结果 |
| `backend/tests/test_legal_import.py` | 预览、令牌、回滚、幂等和验收测试 |
| `backend/tests/test_rag_legal_retrieval.py` | 合同领域优先级回归 |
| `frontend/tests/legal-import.spec.ts` | 前端状态与错误展示测试 |
| `frontend/tests/legal-import-e2e.spec.ts` | 浏览器导入流程和响应式验收 |

### Task 1: 将正式民法典范围扩展为 1260 条

**Files:**
- Modify: `backend/resources/legal_sources/manifest.json`
- Modify: `backend/tests/test_legal_sources.py`

- [ ] **Step 1: 写正式法源完整性失败测试**

```python
def test_official_manifest_contains_complete_civil_code():
    specs = load_manifest(OFFICIAL_MANIFEST)
    civil_code = next(spec for spec in specs if spec.source_id == "civil-code-2020")
    text = verify_source_file(civil_code, OFFICIAL_MANIFEST.parent)
    articles = parse_articles(civil_code, text)
    validate_article_set(civil_code, articles)
    assert civil_code.included_ranges == ((1, 1260),)
    assert len(articles) == 1260
    assert articles[0].article_number == "第一条"
    assert articles[-1].article_number == "第一千二百六十条"
```

- [ ] **Step 2: 运行测试确认现有 802 条清单失败**

Run: `python -m pytest tests/test_legal_sources.py::test_official_manifest_contains_complete_civil_code -q`

Expected: FAIL，清单范围仍为三个定向区间。

- [ ] **Step 3: 只修改清单选择范围和预期数**

```json
"included_ranges": [[1, 1260]],
"expected_article_count": 1260
```

不得修改 `civil-code.txt` 或其 SHA-256。

- [ ] **Step 4: 运行法源校验**

Run: `python scripts/verify_legal_sources.py --manifest resources/legal_sources/manifest.json`

Expected: 民法典 1260 条、司法解释 69 条，无缺条、重条或越界条号。

- [ ] **Step 5: 提交**

```powershell
git add backend/resources/legal_sources/manifest.json backend/tests/test_legal_sources.py
git commit -m "data: expand civil code source to all articles"
```

### Task 2: 实现上传文件预检与受控令牌

**Files:**
- Create: `backend/app/services/rag/legal_import.py`
- Create: `backend/tests/test_legal_import.py`

- [ ] **Step 1: 写识别、完整性和只读预览测试**

测试必须断言：官方 TXT 返回 1260 条；缺第 1260 条、重条、哈希不一致均 `allowed=False`；预览前后数据库计数不变。

```python
preview = preview_legal_import(
    db,
    filename="中华人民共和国民法典.txt",
    content=official_bytes,
    user_id=admin.id,
)
assert preview.allowed is True
assert preview.source_id == "civil-code-2020"
assert preview.article_count == 1260
assert preview.file_sha256 == OFFICIAL_SHA256
assert preview.token
```

- [ ] **Step 2: 运行测试确认模块尚不存在**

Run: `python -m pytest tests/test_legal_import.py -q`

Expected: FAIL with `ModuleNotFoundError`。

- [ ] **Step 3: 实现不可变预览数据和 HMAC 令牌**

```python
@dataclass(frozen=True)
class LegalImportPreview:
    allowed: bool
    source_id: str | None
    title: str | None
    file_sha256: str
    hash_matches: bool
    article_count: int
    chunk_count: int
    replace_article_count: int
    replace_chunk_count: int
    errors: tuple[str, ...]
    token: str | None

def preview_legal_import(
    db: Session, *, filename: str, content: bytes, user_id: int
) -> LegalImportPreview: ...

def verify_preview_token(
    token: str, *, content: bytes, user_id: int, now: datetime | None = None
) -> dict: ...
```

令牌 payload 固定包含 `source_id`、`file_sha256`、`user_id`、`expires_at`，使用 `JWT_SECRET` 派生的 HMAC-SHA256 签名；有效期 10 分钟。比较签名使用 `hmac.compare_digest`。

- [ ] **Step 4: 实现 TXT/DOCX/PDF 文本提取复用**

从 `knowledge.py` 提取现有 `_extract_text` 为可复用函数，限制与现有上传接口一致。预览只接受单文件，不落盘。

- [ ] **Step 5: 覆盖令牌篡改、过期和用户不匹配**

```python
with pytest.raises(LegalImportError, match="预检令牌"):
    verify_preview_token(tampered, content=official_bytes, user_id=admin.id)
```

- [ ] **Step 6: 运行并提交**

Run: `python -m pytest tests/test_legal_import.py tests/test_legal_sources.py -q`

```powershell
git add backend/app/services/rag/legal_import.py backend/tests/test_legal_import.py backend/app/api/v1/endpoints/knowledge.py
git commit -m "feat: preview authoritative legal imports"
```

### Task 3: 实现管理员原子应用接口

**Files:**
- Modify: `backend/app/services/rag/legal_import.py`
- Modify: `backend/app/api/v1/endpoints/knowledge.py`
- Modify: `backend/tests/test_legal_import.py`
- Modify: `backend/tests/test_knowledge_split.py`

- [ ] **Step 1: 写应用、回滚、幂等和普通导入兼容测试**

```python
result = apply_legal_import(
    db,
    filename="中华人民共和国民法典.txt",
    content=official_bytes,
    token=preview.token,
    user_id=admin.id,
)
assert result.article_count == 1260
assert result.first_article_ok
assert result.article_585_ok
assert result.last_article_ok
```

Embedding 异常、事务异常后断言旧 `LegalArticle` 和 `KnowledgeChunk` 内容不变；重复导入断言复用向量且数量不增长；通用 `_smart_split` 测试继续通过。

- [ ] **Step 2: 运行新增测试确认应用函数和接口缺失**

Run: `python -m pytest tests/test_legal_import.py tests/test_knowledge_split.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现应用服务**

```python
@dataclass(frozen=True)
class LegalImportResult:
    source_id: str
    article_count: int
    chunk_count: int
    reused_embeddings: int
    rebuilt_embeddings: int
    embedding_model: str
    embedding_dimension: int
    embedding_signature: str
    first_article_ok: bool
    article_585_ok: bool
    last_article_ok: bool

def apply_legal_import(..., token: str, user_id: int) -> LegalImportResult: ...
```

应用必须重新计算哈希和解析结果，复用 `prepare_documents` 的签名缓存，并在向量全部成功后进入单一事务。只替换 `civil-code-2020` 的父法条和关联子切片，不删除司法解释、规则、模板、案例或无父旧知识。

- [ ] **Step 4: 新增管理员 HTTP 接口**

```python
@router.post("/legal-import/preview")
def preview_legal_source(
    file: UploadFile = File(...),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
): ...

@router.post("/legal-import/apply")
def apply_legal_source(
    file: UploadFile = File(...),
    token: str = Form(...),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
): ...
```

预检错误返回 422，令牌错误返回 409，Embedding 不可用返回 503；成功后写一条不含正文的审计日志。

- [ ] **Step 5: 运行并提交**

Run: `python -m pytest tests/test_legal_import.py tests/test_knowledge_split.py tests/test_audit_evidence.py -q`

```powershell
git add backend/app/services/rag/legal_import.py backend/app/api/v1/endpoints/knowledge.py backend/tests/test_legal_import.py backend/tests/test_knowledge_split.py
git commit -m "feat: apply authoritative legal imports atomically"
```

### Task 4: 增加合同领域检索优先级

**Files:**
- Modify: `backend/app/services/rag/retriever.py`
- Modify: `backend/tests/test_rag_legal_retrieval.py`

- [ ] **Step 1: 写领域加权失败测试**

构造相同 RRF 分数的合同编和非合同编法条，查询包含合同风险术语时断言合同编优先；明确条号查询不受加权影响；普通非合同查询不强制合同编优先。

```python
results = retrieve("合同违约责任如何承担", top_k=2, categories=["law"])
assert results[0]["article_number"] == "第五百七十七条"
```

- [ ] **Step 2: 实现有限加权**

在 RRF 后、父法条收敛前增加纯函数 `apply_contract_domain_boost(results, query)`。只有查询含合同审查术语时，给总则 1—204、担保物权 386—457、合同编 463—988 和合同司法解释稳定的小幅排序加分；不得过滤其他各编，不改变精确条号路径。

- [ ] **Step 3: 运行并提交**

Run: `python -m pytest tests/test_rag_legal_retrieval.py tests/test_rag_hybrid.py tests/test_rag_grounding.py -q`

```powershell
git add backend/app/services/rag/retriever.py backend/tests/test_rag_legal_retrieval.py
git commit -m "feat: prioritize contract law retrieval"
```

### Task 5: 增强现有前端导入弹窗

**Files:**
- Modify: `frontend/src/api/knowledge.ts`
- Modify: `frontend/src/views/KnowledgeView.vue`
- Create: `frontend/tests/legal-import.spec.ts`

- [ ] **Step 1: 写前端状态测试**

覆盖：选择官方民法典后展示 1260 父法条预览；哈希不符禁用确认；应用中按钮禁用且不显示虚构百分比；成功展示第 1、585、1260 条通过；普通文件仍使用 `importKnowledgeFile`。

- [ ] **Step 2: 运行测试确认缺少权威导入 UI**

Run: `npm.cmd test -- tests/legal-import.spec.ts`

Expected: FAIL。

- [ ] **Step 3: 增加 API 类型与函数**

```typescript
export interface LegalImportPreview {
  allowed: boolean
  source_id: string | null
  title: string | null
  file_sha256: string
  hash_matches: boolean
  article_count: number
  chunk_count: number
  replace_article_count: number
  replace_chunk_count: number
  errors: string[]
  token: string | null
}

export function previewLegalImport(file: File): Promise<LegalImportPreview> { ... }
export function applyLegalImport(file: File, token: string): Promise<LegalImportResult> { ... }
```

- [ ] **Step 4: 在现有弹窗实现状态机**

状态固定为 `idle | previewing | generic-ready | legal-ready | applying | success | error`。选择文件后先预检；后端判定非权威候选时回到现有通用导入。权威预览显示父法条、子切片、哈希和替换数量，应用前使用 `ElMessageBox.confirm` 明确确认替换范围。

- [ ] **Step 5: 运行前端验证并提交**

Run: `npm.cmd test -- tests/legal-import.spec.ts`

Run: `npm.cmd run type-check`

Run: `npm.cmd run build`

```powershell
git add frontend/src/api/knowledge.ts frontend/src/views/KnowledgeView.vue frontend/tests/legal-import.spec.ts
git commit -m "feat: import verified legal sources from knowledge UI"
```

### Task 6: 全链路数据库和浏览器验收

**Files:**
- Create: `frontend/tests/legal-import-e2e.spec.ts`
- Modify: `PROGRESS.md`（仅合并主工作区现有用户内容后记录新鲜证据）
- Generate ignored: `outputs/legal-knowledge-sync/full-import-acceptance.json`

- [ ] **Step 1: 运行完整质量门禁**

Run: `python -m pytest -q`

Run: `npm.cmd test`

Run: `npm.cmd run type-check`

Run: `npm.cmd run build`

Expected: 所有非环境依赖测试通过。

- [ ] **Step 2: 对真实开发库执行预览**

从前端上传 `backend/resources/legal_sources/civil-code.txt`，保存预览证据。必须显示 1260 条、哈希一致、允许应用；此步骤不写数据库。

- [ ] **Step 3: 应用前再次获得用户授权并备份**

报告数据库绝对路径、备份路径、预计替换父法条/子切片和需重建向量数量。获得明确授权后复制带时间戳备份；不得复用旧备份代替本次备份。

- [ ] **Step 4: 通过前端执行正式导入**

应用成功后只读核对：民法典父法条 1260、司法解释 69、总父法条 1329；所有新子切片父关联非空、维度 512、签名一致；非受控知识数量不减少。

- [ ] **Step 5: 浏览器验收**

在 1440x900 和 390x844 验证正常预览、成功、哈希错误、服务错误和无横向溢出。搜索第 1、585、1260 条，精确结果必须返回完整父法条；自然语言“违约金约定过高”使用 `hybrid` 并命中合同领域依据。

- [ ] **Step 6: 记录证据并提交测试**

```powershell
git add frontend/tests/legal-import-e2e.spec.ts
git commit -m "test: verify full civil code frontend import"
```

`PROGRESS.md` 只能记录实际通过的开发环境证据，不得扩展为 OpenClaw、类脑加速或 GPU 能效比已达标。
