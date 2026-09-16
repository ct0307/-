# Contract Ingestion Edge-Case Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不增加外部依赖、不放宽人工复核边界的前提下，完成 TXT 严格解码、图片型 DOCX 质量门、合同类型规则数据化以及管理员界面闭环。

**Architecture:** 解码和解析质量保持为纯服务，预检与正式解析复用同一实现。合同类型分类器不直接访问数据库，由配置仓储提供不可变 profile；管理 API 和 Vue 界面共用严格的版本化协议。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy、Alembic、Pydantic、python-docx、Vue 3、TypeScript、Element Plus、Playwright、pytest。

---

## File Structure

| 路径 | 职责 |
|---|---|
| `backend/app/services/parser/text_decoder.py` | TXT 严格解码和候选质量比较 |
| `backend/app/services/parser/extractor.py` | 调用共用解码器，识别图片型 DOCX |
| `backend/app/services/imports/file_validation.py` | 上传预检复用共用解码器 |
| `backend/app/services/imports/type_profiles.py` | profile 清洗、数据库加载和规则版本更新 |
| `backend/app/services/imports/classifier.py` | 消费 profile，识别明示类型和冲突 |
| `backend/app/models/models.py` | `ContractTypeProfile` ORM 模型 |
| `backend/app/schemas/contract.py` | profile 读写 API 协议 |
| `backend/app/api/v1/endpoints/lookup.py` | 管理员 profile 查询与版本化更新 |
| `backend/alembic/versions/20260916_01_contract_type_profiles.py` | 生产迁移和当前硬编码信号种子 |
| `backend/app/db/init_db.py` | SQLite 轻量迁移与开发种子 |
| `frontend/src/api/admin.ts` | profile 前端类型与 API |
| `frontend/src/views/AdminView.vue` | 合同类型规则编辑抽屉 |
| `frontend/tests/admin-contract-type-profile.spec.ts` | 管理界面正常、空、冲突和响应式状态 |

### Task 1: 共用 TXT 严格解码器

**Files:**
- Create: `backend/app/services/parser/text_decoder.py`
- Modify: `backend/app/services/imports/file_validation.py`
- Modify: `backend/app/services/parser/extractor.py`
- Create: `backend/tests/test_text_decoder.py`
- Test: `backend/tests/test_import_file_validation.py`
- Test: `backend/tests/test_parser_contracts.py`

- [ ] **Step 1: Write failing decoder tests**

```python
def test_gb18030_round_trips_without_character_loss():
    source = "合同类型：采购合同\n甲方向乙方采购设备。"
    decoded = decode_text_bytes(source.encode("gb18030"))
    assert decoded.text == source
    assert decoded.encoding == "gb18030"

def test_invalid_or_empty_text_uses_stable_error_codes():
    with pytest.raises(TextDecodeError, match="TEXT_ENCODING_ERROR"):
        decode_text_bytes(b"\x00\xff\xfe")
    with pytest.raises(TextDecodeError, match="TEXT_EMPTY"):
        decode_text_bytes(b" \r\n\t")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_text_decoder.py -q`

Expected: collection fails because `app.services.parser.text_decoder` does not exist.

- [ ] **Step 3: Implement the strict decoder**

```python
@dataclass(frozen=True)
class DecodedText:
    text: str
    encoding: Literal["utf-8-sig", "utf-8", "gb18030"]

class TextDecodeError(ValueError):
    def __init__(self, code: Literal["TEXT_ENCODING_ERROR", "TEXT_EMPTY"]):
        self.code = code
        super().__init__(code)

def decode_text_bytes(content: bytes) -> DecodedText:
    if not content or b"\x00" in content:
        raise TextDecodeError("TEXT_ENCODING_ERROR")
    encodings = ("utf-8-sig",) if content.startswith(b"\xef\xbb\xbf") else ("utf-8", "gb18030")
    candidates = []
    for encoding in encodings:
        try:
            candidates.append(DecodedText(content.decode(encoding, errors="strict"), encoding))
        except UnicodeDecodeError:
            pass
    if not candidates:
        raise TextDecodeError("TEXT_ENCODING_ERROR")
    chosen = max(candidates, key=_text_quality_key)
    if not any(char.isprintable() and not char.isspace() for char in chosen.text):
        raise TextDecodeError("TEXT_EMPTY")
    return chosen
```

`_text_quality_key()` 按“控制字符更少、可打印比例更高、CJK 比例更高、平局时 UTF-8 优先”返回稳定 tuple，不使用容错解码。

- [ ] **Step 4: Route validation and extraction through the shared decoder**

`_validate_text()` 将 `TextDecodeError.code` 映射为 `FileValidationError`；`extract_document()` 的 `.txt` 分支改为：

```python
if lower.endswith(".txt"):
    return DocumentParseResult(decode_text_bytes(data).text, "native")
```

- [ ] **Step 5: Verify GREEN and scan for silent decode**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_text_decoder.py tests/test_import_file_validation.py tests/test_parser_contracts.py -q`

Run: `rg -n 'decode\([^\n]*errors=("|\x27)(ignore|replace)' backend/app/services`

Expected: tests pass; no production TXT path uses `ignore` or `replace`.

- [ ] **Step 6: Commit the slice**

```powershell
git add backend/app/services/parser/text_decoder.py backend/app/services/imports/file_validation.py backend/app/services/parser/extractor.py backend/tests/test_text_decoder.py backend/tests/test_import_file_validation.py backend/tests/test_parser_contracts.py
git commit -m "fix: unify strict text decoding"
```

### Task 2: 图片型 DOCX 质量门

**Files:**
- Modify: `backend/app/services/parser/extractor.py`
- Test: `backend/tests/test_parser_contracts.py`
- Test: `backend/tests/test_import_tasks.py`

- [ ] **Step 1: Write failing DOCX quality tests**

用 `python-docx` 测试工具生成三类文档：只含 1600×2200 图片、正常正文加 300×100 Logo、纯空文档。断言：

```python
assert image_only.requires_review is True
assert image_only.review_reason == "DOCX 疑似图片型文档，未提取到足够正文"
assert normal_with_logo.requires_review is False
assert empty.review_reason == "DOCX 正文为空"
```

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_parser_contracts.py -k "docx and (image or logo or empty)" -q`

Expected: image-only and empty quality assertions fail.

- [ ] **Step 3: Implement image metrics without a new dependency**

```python
@dataclass(frozen=True)
class _DocxImageMetrics:
    image_count: int
    meaningful_image_count: int

def _docx_image_metrics(document) -> _DocxImageMetrics:
    parts = tuple(document.part.package.image_parts)
    meaningful = 0
    for part in parts:
        image = Image.from_blob(part.blob)
        pixels = int(image.px_width or 0) * int(image.px_height or 0)
        if pixels >= 1_500_000 and min(image.px_width or 0, image.px_height or 0) >= 900:
            meaningful += 1
    return _DocxImageMetrics(len(parts), meaningful)
```

当有效正文少于 200 字且 `meaningful_image_count > 0` 时标记图片型；无大图且正文为空时使用独立空文档原因。继续由现有预检承担 ZIP 安全边界。

- [ ] **Step 4: Verify parser and import-state behavior**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_parser_contracts.py tests/test_import_tasks.py -q`

Expected: image-only DOCX enters `awaiting_confirmation`; normal DOCX with Logo remains on the existing path.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/parser/extractor.py backend/tests/test_parser_contracts.py backend/tests/test_import_tasks.py
git commit -m "fix: flag image-based docx for review"
```

### Task 3: 合同类型 profile 模型与双轨迁移

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/db/init_db.py`
- Create: `backend/alembic/versions/20260916_01_contract_type_profiles.py`
- Test: `backend/tests/test_import_models.py`
- Create: `backend/tests/test_db_migrations.py`

- [ ] **Step 1: Write failing model and migration tests**

```python
def test_contract_type_profile_is_one_to_one_with_lookup(db):
    lookup = LookupItem(category="contract_type", value="居间合同", sort_order=0)
    db.add(lookup); db.flush()
    db.add(ContractTypeProfile(lookup_item_id=lookup.id, aliases_json="[]", positive_signals_json="[]", negative_signals_json="[]"))
    db.commit()
    assert lookup.contract_type_profile.version == 1
```

迁移测试要断言当前 14 类的 profile 被种入，且删除 lookup 后 profile 不残留。

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_import_models.py tests/test_db_migrations.py -q`

Expected: `ContractTypeProfile` and the new revision are missing.

- [ ] **Step 3: Add the ORM model**

```python
class ContractTypeProfile(Base):
    __tablename__ = "contract_type_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lookup_item_id: Mapped[int] = mapped_column(ForeignKey("lookup_items.id", ondelete="CASCADE"), unique=True, index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    positive_signals_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    negative_signals_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 4: Add Alembic and SQLite-init parity**

迁移使用参数化 JSON 种子，将 `_TRADE_SIGNALS` 与 `_TYPE_FAMILY_ALIASES` 的当前值按 lookup value 写入。`init_db.py` 创建同构表，并只为缺失 profile 的现有合同类型补种子。

- [ ] **Step 5: Verify upgrade, downgrade, and fresh SQLite initialization**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_import_models.py tests/test_db_migrations.py -q`

Run: `cd backend && ./.venv/Scripts/python.exe -m alembic upgrade head`

Expected: tests pass and migration exits 0 against the configured development database without losing lookup items.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/models/models.py backend/app/db/init_db.py backend/alembic/versions/20260916_01_contract_type_profiles.py backend/tests/test_import_models.py backend/tests/test_db_migrations.py
git commit -m "feat: persist contract type profiles"
```

### Task 4: Profile 规则服务与数据驱动分类

**Files:**
- Create: `backend/app/services/imports/type_profiles.py`
- Modify: `backend/app/services/imports/classifier.py`
- Modify: `backend/app/tasks/import_tasks.py`
- Test: `backend/tests/test_contract_type_classifier.py`
- Test: `backend/tests/test_import_tasks.py`

- [ ] **Step 1: Write failing profile-driven classifier tests**

```python
def test_new_type_is_reachable_from_database_profile():
    profiles = {"居间合同": TypeProfile(aliases=("居间协议",), positive_signals=("居间服务", "委托方"), negative_signals=())}
    result = classify_contract_type(filename="文件.docx", text="受托方提供居间服务", available_types=["居间合同"], profiles=profiles)
    assert result.suggested_type == "居间合同"

def test_type_without_profile_does_not_gain_semantic_candidate():
    result = classify_contract_type(filename="文件.docx", text="普通描述", available_types=["新类型"], profiles={})
    assert result.suggested_type == ""
```

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_contract_type_classifier.py -q`

Expected: classifier does not accept `profiles` and cannot reach the custom semantic type.

- [ ] **Step 3: Implement immutable profile loading and normalization**

```python
@dataclass(frozen=True)
class TypeProfile:
    aliases: tuple[str, ...] = ()
    positive_signals: tuple[str, ...] = ()
    negative_signals: tuple[str, ...] = ()

def normalize_terms(values: Sequence[str], *, max_items: int = 32, max_length: int = 64) -> tuple[str, ...]:
    cleaned = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
    if len(cleaned) > max_items or any(len(value) > max_length for value in cleaned):
        raise ValueError("合同类型规则超出长度或数量限制")
    return cleaned
```

`load_type_profiles(db, available_types)` 只返回已启用且归属于当前 `contract_type` lookup 的 profile。

- [ ] **Step 4: Replace hard-coded runtime signals**

`classify_contract_type(*, filename: str, text: str, available_types: list[str], profiles: Mapping[str, TypeProfile]) -> TypeSuggestion` 使用 profile 的 alias/positive/negative 计分，不再读取 `_TRADE_SIGNALS` 和 `_TYPE_FAMILY_ALIASES`。任务层在同一 DB session 中加载 lookup 和 profile，再将纯数据传入分类器。

- [ ] **Step 5: Verify the existing 14-type baseline**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_contract_type_classifier.py tests/test_import_tasks.py -q`

Expected: existing title, material-document, tie and safety tests remain green; new type is reachable only through configured evidence.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/imports/type_profiles.py backend/app/services/imports/classifier.py backend/app/tasks/import_tasks.py backend/tests/test_contract_type_classifier.py backend/tests/test_import_tasks.py
git commit -m "feat: drive contract classification from profiles"
```

### Task 5: 明示类型和冲突降级

**Files:**
- Modify: `backend/app/services/imports/classifier.py`
- Test: `backend/tests/test_contract_type_classifier.py`
- Test: `backend/tests/test_import_api.py`

- [ ] **Step 1: Write failing explicit-type tests**

```python
@pytest.mark.parametrize("label", ["合同类型", "协议类型", "文件类型"])
def test_explicit_dictionary_value_is_high_weight_evidence(label):
    result = classify_contract_type(filename="x.docx", text=f"{label}：居间合同\n正文", available_types=["居间合同"], profiles={})
    assert result.suggested_type == "居间合同"
    assert "explicit_type:居间合同" in result.evidence

def test_explicit_type_conflict_never_auto_readies():
    result = classify_contract_type(filename="采购合同.docx", text="合同类型：销售合同\n采购人采购设备", available_types=["采购合同", "销售合同"], profiles=profiles)
    assert result.auto_ready_eligible is False
    assert result.conflict is True
```

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_contract_type_classifier.py -k "explicit or conflict" -q`

- [ ] **Step 3: Add controlled header parsing and conflict metadata**

```python
_EXPLICIT_TYPE_RE = re.compile(r"^(?:合同类型|协议类型|文件类型)\s*[:：]\s*(?P<value>[^\r\n]{1,64})$")
```

只扫描前 40 个非空行且不超过前 1800 字；字段值必须精确匹配当前字典。为 `TypeSuggestion` 增加 `conflict: bool = False`，明示类型与可信标题或强交易信号不一致时，将置信度限制为 `0.40` 并设置 `auto_ready_eligible=False`。

- [ ] **Step 4: Verify API state remains awaiting confirmation**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_contract_type_classifier.py tests/test_import_api.py -q`

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/imports/classifier.py backend/tests/test_contract_type_classifier.py backend/tests/test_import_api.py
git commit -m "feat: detect explicit contract types safely"
```

### Task 6: 管理员 profile API 与审计

**Files:**
- Modify: `backend/app/schemas/contract.py`
- Modify: `backend/app/api/v1/endpoints/lookup.py`
- Modify: `backend/app/services/imports/type_profiles.py`
- Test: `backend/tests/test_contract_quality_api.py`

- [ ] **Step 1: Write failing API tests**

覆盖：管理员可读写、非管理员仅可读普通 lookup 不可读写 profile、空值/重复值被清洗、超限返回 `422`、旧 version 返回 `409`、审计日志不包含合同正文。

- [ ] **Step 2: Verify RED**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_contract_quality_api.py -k "type_profile" -q`

- [ ] **Step 3: Add strict request/response schemas**

```python
class ContractTypeProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    aliases: list[str] = Field(default_factory=list, max_length=32)
    positive_signals: list[str] = Field(default_factory=list, max_length=32)
    negative_signals: list[str] = Field(default_factory=list, max_length=32)
    enabled: bool
    version: int = Field(ge=1)

class ContractTypeProfileOut(ContractTypeProfileUpdate):
    lookup_item_id: int
    value: str
```

- [ ] **Step 4: Implement endpoints and optimistic update**

```python
@router.get("/lookups/contract_type/profiles", response_model=list[ContractTypeProfileOut])
def list_contract_type_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"])),
) -> list[ContractTypeProfileOut]:
    return [profile_to_out(row) for row in load_profile_rows(db)]

@router.put("/lookups/{item_id}/profile", response_model=ContractTypeProfileOut)
def update_contract_type_profile(
    item_id: int,
    body: ContractTypeProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"])),
) -> ContractTypeProfileOut:
    row = update_profile(db, item_id=item_id, expected_version=body.version, values=body)
    audit_log.record(db, user_id=current_user.id, action="contract_type_profile_update", target=f"lookup:{item_id}", detail=profile_audit_detail(row))
    db.commit()
    return profile_to_out(row)
```

更新使用 `WHERE lookup_item_id=:id AND version=:expected` 的条件 `UPDATE`，影响行数为 0 时返回 `409`。审计详情只记录 lookup ID、版本、各数组项数和 enabled。

- [ ] **Step 5: Verify GREEN**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_contract_quality_api.py -k "lookup or type_profile" -q`

- [ ] **Step 6: Commit**

```powershell
git add backend/app/schemas/contract.py backend/app/api/v1/endpoints/lookup.py backend/app/services/imports/type_profiles.py backend/tests/test_contract_quality_api.py
git commit -m "feat: manage contract type profiles"
```

### Task 7: 管理员规则编辑界面

**Files:**
- Modify: `frontend/src/api/admin.ts`
- Modify: `frontend/src/views/AdminView.vue`
- Create: `frontend/tests/admin-contract-type-profile.spec.ts`

- [ ] **Step 1: Write failing Playwright tests**

测试使用路由 mock 覆盖：

```typescript
await page.getByRole('button', { name: '编辑采购合同规则' }).click()
await expect(page.getByRole('dialog', { name: '采购合同分类规则' })).toBeVisible()
await page.getByLabel('正向信号').fill('采购\n供货\n设备')
await page.getByRole('button', { name: '保存规则' }).click()
expect(updateBody.version).toBe(3)
```

另覆盖空 profile、API 500、409 版本冲突后刷新、390px 视口无水平溢出。

- [ ] **Step 2: Verify RED**

Run: `cd frontend && npm.cmd test -- admin-contract-type-profile.spec.ts`

Expected: rule-edit button and dialog are missing.

- [ ] **Step 3: Add API types and methods**

```typescript
export interface ContractTypeProfile {
  lookup_item_id: number
  value: string
  aliases: string[]
  positive_signals: string[]
  negative_signals: string[]
  enabled: boolean
  version: number
}

export const getContractTypeProfiles = () => client.get('/admin/lookups/contract_type/profiles')
export const updateContractTypeProfile = (id: number, body: Omit<ContractTypeProfile, 'lookup_item_id' | 'value'>) =>
  client.put(`/admin/lookups/${id}/profile`, body)
```

- [ ] **Step 4: Implement the compact editor**

在现有合同类型列表的每个条目后增加带 tooltip 的设置图标按钮。抽屉包含启用开关和三个“每行一项”的 textarea；保存时在前端去空、去重，但后端仍作最终校验。`409` 时保留抽屉，显示“规则已被更新，请刷新后重试”并重新加载 profile。

- [ ] **Step 5: Verify normal, empty, error, and responsive states**

Run: `cd frontend && npm.cmd run type-check`

Run: `cd frontend && npm.cmd test -- admin-contract-type-profile.spec.ts`

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/api/admin.ts frontend/src/views/AdminView.vue frontend/tests/admin-contract-type-profile.spec.ts
git commit -m "feat: edit contract type profiles in admin"
```

### Task 8: 导入链路和冻结集回归

**Files:**
- Modify: `backend/evaluation/ingestion_reliability.py`
- Modify: `backend/tests/test_ingestion_reliability.py`
- Modify: `backend/tests/test_import_api.py`
- Modify: `backend/tests/test_import_tasks.py`

- [ ] **Step 1: Add end-to-end fixtures and failing assertions**

增加 GB18030 TXT、纯图片 DOCX、正文+Logo DOCX、明示类型一致和冲突各一份生成式 fixture。不将真实合同原文纳入仓库。

- [ ] **Step 2: Verify the new checks fail before final wiring**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_ingestion_reliability.py tests/test_import_api.py tests/test_import_tasks.py -q`

- [ ] **Step 3: Wire reliability output and preserve safety claims**

评测输出增加 `text_round_trip_equal`、`image_docx_reviewed`、`explicit_type_reachable`、`type_conflict_auto_ready_count`，不将模拟结果表述为真实业务准确率。

- [ ] **Step 4: Run all ingestion-related tests**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_text_decoder.py tests/test_import_file_validation.py tests/test_parser_contracts.py tests/test_contract_type_classifier.py tests/test_import_models.py tests/test_import_tasks.py tests/test_import_api.py tests/test_ingestion_reliability.py tests/test_contract_quality_api.py -q`

- [ ] **Step 5: Run frontend checks**

Run: `cd frontend && npm.cmd run type-check`

Run: `cd frontend && npm.cmd test -- admin-contract-type-profile.spec.ts department-scope-admin-e2e.spec.ts`

- [ ] **Step 6: Commit the regression slice**

```powershell
git add backend/evaluation/ingestion_reliability.py backend/tests/test_ingestion_reliability.py backend/tests/test_import_api.py backend/tests/test_import_tasks.py
git commit -m "test: cover hardened contract ingestion"
```

### Task 9: 完整验收

**Files:**
- Test: `scripts/quality_gate.ps1`
- Test: `frontend/tests/admin-contract-type-profile.spec.ts`
- Test: `backend/tests/test_ingestion_reliability.py`

- [ ] **Step 1: Run the complete quality gate**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1`

Expected: backend tests, evaluation checks, frontend Playwright and type checking all exit 0.

- [ ] **Step 2: Start services for UI verification**

Run backend: `cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`

Run frontend: `cd frontend && npm.cmd run dev -- --host 127.0.0.1 --port 5173`

- [ ] **Step 3: Browser-check the admin workflow**

验证合同类型列表、空 profile、加载、保存、409、500 和 390px/1440px 视口；确认按钮、抽屉、输入和错误文案无重叠或溢出。

- [ ] **Step 4: Record factual acceptance results**

将真实执行命令、通过数、未执行项和剩余风险写入项目进度记录；未完成的真实样本验证不得写成达标。
