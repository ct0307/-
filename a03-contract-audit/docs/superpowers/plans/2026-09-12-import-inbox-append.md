# 合同收件箱连续追加实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在同一待审收件箱中连续追加合同，同时保证上传和审查请求的幂等语义正确。

**Architecture:** 后端新增面向现有导入批次的追加端点，并以请求指纹及唯一约束区分安全重试和错误复用。前端 store 在已有批次时调用追加端点，保留有效选择并管理每次用户动作的独立幂等键。

**Tech Stack:** FastAPI、SQLAlchemy、SQLite/PostgreSQL、Vue 3、Pinia、TypeScript、Playwright、pytest

---

## 文件结构

- `backend/app/models/models.py`：保存创建请求指纹与追加请求幂等记录。
- `backend/app/db/init_db.py`：为现有 SQLite 开发库补齐请求指纹字段。
- `backend/app/api/v1/endpoints/imports.py`：集中处理文件校验、持久化、追加和请求指纹校验。
- `backend/tests/test_import_api.py`：覆盖创建冲突、追加、重试、超限、重名与权限。
- `backend/tests/test_merge_readiness_unittest.py`：验证开发库迁移后结构完整。
- `frontend/src/api/imports.ts`：暴露追加合同 API。
- `frontend/src/stores/import-inbox.ts`：区分首次创建和后续追加，维护选择与轮询。
- `frontend/src/stores/batch.ts`：修正不同审查动作复用幂等键的问题。
- `frontend/src/views/AuditView.vue`：使用本次接收数量显示成功消息。
- `frontend/tests/import-inbox-store.spec.ts`：覆盖追加状态机和上传幂等键生命周期。
- `frontend/tests/batch-store.spec.ts`：覆盖审查动作幂等键生命周期。
- `frontend/tests/contract-inbox-workflow-e2e.spec.ts`：覆盖连续添加的页面行为。

### Task 1: 导入请求幂等数据模型

**Files:**
- Modify: `backend/app/models/models.py:147-195`
- Modify: `backend/app/db/init_db.py:42-134`
- Test: `backend/tests/test_import_models.py`
- Test: `backend/tests/test_merge_readiness_unittest.py`

- [ ] **Step 1: 写失败测试**

在模型测试中断言 `ImportBatch.request_fingerprint` 可持久化，并创建两条相同 `(batch_id, idempotency_key)` 的 `ImportAppendRequest` 时触发唯一约束。迁移测试断言旧 SQLite 的 `import_batches` 会新增 `request_fingerprint`，且 `import_append_requests` 表存在。

```python
batch = ImportBatch(owner_id=user.id, idempotency_key="create-key", request_fingerprint="a" * 64)
db.add(batch)
db.commit()
db.add(ImportAppendRequest(batch_id=batch.id, idempotency_key="append-key", request_fingerprint="b" * 64))
db.commit()
db.add(ImportAppendRequest(batch_id=batch.id, idempotency_key="append-key", request_fingerprint="b" * 64))
with pytest.raises(IntegrityError):
    db.commit()
```

- [ ] **Step 2: 验证测试因字段和模型不存在而失败**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_import_models.py backend/tests/test_merge_readiness_unittest.py -q`

Expected: FAIL，错误指向 `request_fingerprint` 或 `ImportAppendRequest` 尚不存在。

- [ ] **Step 3: 实现最小模型与迁移**

在 `ImportBatch` 增加可兼容旧记录的字段：

```python
request_fingerprint: Mapped[str] = mapped_column(String(64), default="")
```

新增模型：

```python
class ImportAppendRequest(Base):
    __tablename__ = "import_append_requests"
    __table_args__ = (
        UniqueConstraint("batch_id", "idempotency_key", name="uq_import_append_batch_key"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

在 `_DEV_COLUMNS["import_batches"]` 增加 `("request_fingerprint", "VARCHAR(64) DEFAULT '' NOT NULL")`。新表由 `Base.metadata.create_all` 创建。

- [ ] **Step 4: 验证模型与迁移测试通过**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_import_models.py backend/tests/test_merge_readiness_unittest.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/models/models.py backend/app/db/init_db.py backend/tests/test_import_models.py backend/tests/test_merge_readiness_unittest.py
git commit -m "feat: persist import request idempotency"
```

### Task 2: 后端连续追加端点

**Files:**
- Modify: `backend/app/api/v1/endpoints/imports.py:1-195`
- Test: `backend/tests/test_import_api.py`

- [ ] **Step 1: 写失败的业务回归测试**

新增测试并直接调用端点函数：

```python
created = imports.create_import([_file("first.txt", b"first")], "create-key", "法务部", db, legal)
appended = imports.append_import_items(
    created.id, [_file("second.txt", b"second")], "append-key", db, legal
)
assert appended.id == created.id
assert [item.filename for item in appended.items] == ["first.txt", "second.txt"]
assert db.query(Contract).count() == 2
```

同时增加以下断言：相同追加键和相同内容只产生两个合同；相同键不同内容返回 `409/IDEMPOTENCY_CONFLICT`；创建请求同键不同内容返回冲突；累计 200 后追加返回 `409/IMPORT_BATCH_LIMIT_EXCEEDED`；跨请求同名文件产生失败项；其他用户追加返回 403。

- [ ] **Step 2: 验证端点测试失败**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_import_api.py -q`

Expected: FAIL，至少包含 `append_import_items` 不存在或创建冲突未抛出。

- [ ] **Step 3: 提取可复用上传准备与指纹逻辑**

新增内部不可变数据结构和函数：

```python
@dataclass(frozen=True)
class PreparedUpload:
    filename: str
    extension: str
    content: bytes
    content_sha256: str

def _prepare_uploads(files: list[UploadFile]) -> list[PreparedUpload]: ...
def _request_fingerprint(department: str, uploads: list[PreparedUpload]) -> str: ...
def _validate_idempotency_key(value: str) -> str: ...
```

指纹 JSON 使用确定性序列化，包含部门和按上传顺序排列的 `filename`、`size`、`content_sha256`，最终计算 SHA-256。

- [ ] **Step 4: 复用一个事务函数写入导入项**

实现：

```python
def _append_prepared_uploads(
    batch: ImportBatch,
    uploads: list[PreparedUpload],
    *,
    department: str,
    operation_key: str,
    db: Session,
) -> tuple[list[ImportBatchItem], list[str]]: ...
```

函数以批次已有非删除项文件名初始化重名集合；逐文件创建失败项或加密合同；`Contract.upload_idempotency_key` 使用 `sha256(f"{operation_key}:{index}")`；返回本次新增项和文件路径供提交后派发及异常清理。

- [ ] **Step 5: 实现创建冲突检查与追加端点**

创建请求遇到旧批次时比较非空 `request_fingerprint`；不同则抛出：

```python
raise HTTPException(
    status.HTTP_409_CONFLICT,
    {"code": "IDEMPOTENCY_CONFLICT", "message": "幂等键已用于其他合同上传请求"},
)
```

追加端点签名：

```python
@router.post("/{batch_id}/items", response_model=ImportBatchOut, status_code=status.HTTP_202_ACCEPTED)
def append_import_items(
    batch_id: int,
    files: list[UploadFile] = File(...),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportBatchOut: ...
```

端点锁定所属批次、校验累计数量、处理追加请求幂等记录、提交后仅派发本次新增的 queued 项。超限结构化错误为 `IMPORT_BATCH_LIMIT_EXCEEDED`。

- [ ] **Step 6: 验证后端回归测试通过**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_import_api.py backend/tests/test_import_service.py backend/tests/test_import_tasks.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add backend/app/api/v1/endpoints/imports.py backend/tests/test_import_api.py
git commit -m "feat: append contracts to import inbox"
```

### Task 3: 前端收件箱追加状态机

**Files:**
- Modify: `frontend/src/api/imports.ts:38-54`
- Modify: `frontend/src/stores/import-inbox.ts:9-126`
- Modify: `frontend/src/views/AuditView.vue:112-120`
- Test: `frontend/tests/import-inbox-store.spec.ts`

- [ ] **Step 1: 写失败的 store 测试**

扩展 `ImportApi` fake，记录创建/追加调用和幂等键：

```typescript
appendImport(batchId, files, key) {
  appendCalls.push({ batchId, files, key })
  return Promise.resolve(appendedBatch)
}
```

断言第一次 `create([first])` 调用创建接口，第二次 `create([second])` 调用追加接口且两个键不同；追加后 `batch.items` 有两项，原 ready 项的选中状态保留。增加失败用例，断言 API 抛错后原 `batch`、`selectedIds` 不变。

- [ ] **Step 2: 验证 store 测试失败**

Run: `npm.cmd --prefix frontend test -- import-inbox-store.spec.ts`

Expected: FAIL，错误指向 `appendImport` 接口缺失或第二次仍调用 `createImport`。

- [ ] **Step 3: 增加追加 API**

```typescript
export function appendImport(
  batchId: number,
  files: File[],
  idempotencyKey: string,
): Promise<ImportBatch> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  return client.post(`/imports/${batchId}/items`, form, {
    headers: { 'Idempotency-Key': idempotencyKey },
    timeout: 300_000,
  })
}
```

- [ ] **Step 4: 实现 store 动作级幂等键与追加**

`create()` 每次进入时生成本次局部键；没有批次时调用 `createImport`，已有批次时调用 `appendImport`。只在 API 成功后替换 `batch`。首次创建清空选择，追加时调用 `updateSelection()` 保留仍有效选择。追加后的活动项触发 `startPolling()`。

```typescript
const actionKey = crypto.randomUUID()
const next = batch.value
  ? await api.appendImport(batch.value.id, files, actionKey)
  : await api.createImport(files, department, actionKey)
batch.value = next
```

移除跨调用持久化的上传 `idempotencyKey`。请求库本身不自动重试，同一次调用只有一个键；服务端保留显式重试能力。

- [ ] **Step 5: 修正成功提示**

让 `create()` 返回 `{ batch, accepted }`，其中 `accepted` 为本次选择数量；`AuditView.uploadFiles()` 用 `accepted` 显示“已接收 N 份合同”，路由仍写当前批次 ID。

- [ ] **Step 6: 验证 store 与类型检查通过**

Run: `npm.cmd --prefix frontend test -- import-inbox-store.spec.ts auth-inbox-reset.spec.ts`

Expected: PASS。

Run: `npm.cmd --prefix frontend run type-check`

Expected: exit code 0。

- [ ] **Step 7: 提交**

```powershell
git add frontend/src/api/imports.ts frontend/src/stores/import-inbox.ts frontend/src/views/AuditView.vue frontend/tests/import-inbox-store.spec.ts
git commit -m "fix: append files to active import inbox"
```

### Task 4: 审查动作幂等键修复

**Files:**
- Modify: `frontend/src/stores/batch.ts:84-119`
- Test: `frontend/tests/batch-store.spec.ts`

- [ ] **Step 1: 写失败测试**

连续调用两次 `createFromImport()`，记录 fake API 接收的键并断言不同：

```typescript
await store.createFromImport([1])
await store.createFromImport([2])
expect(keys).toHaveLength(2)
expect(keys[0]).not.toBe(keys[1])
```

对文件审查 `create()` 增加同样断言，防止另一路径继续复用旧任务。

- [ ] **Step 2: 验证测试失败**

Run: `npm.cmd --prefix frontend test -- batch-store.spec.ts`

Expected: FAIL，两个键当前相同。

- [ ] **Step 3: 使用动作局部键**

删除 store 级 `idempotencyKey`，在每个 `create()` 和 `createFromImport()` 调用开始时生成 `const actionKey = crypto.randomUUID()`，同一次 API 调用只传该键；`reset()` 不再管理无效的共享键。

- [ ] **Step 4: 验证测试通过**

Run: `npm.cmd --prefix frontend test -- batch-store.spec.ts`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add frontend/src/stores/batch.ts frontend/tests/batch-store.spec.ts
git commit -m "fix: scope audit idempotency to one action"
```

### Task 5: 页面回归与完整验收

**Files:**
- Modify: `frontend/tests/contract-inbox-workflow-e2e.spec.ts`

- [ ] **Step 1: 写连续添加的失败 E2E 测试**

路由 mock 第一次返回含 `first.txt` 的批次，`POST /imports/42/items` 返回含 `first.txt`、`second.txt` 的同一批次。页面依次上传两个文件后断言两行可见、总数为 2、追加 URL 正确且两次幂等键不同。

```typescript
await fileInput.setInputFiles({ name: 'first.txt', mimeType: 'text/plain', buffer: Buffer.from('first') })
await fileInput.setInputFiles({ name: 'second.txt', mimeType: 'text/plain', buffer: Buffer.from('second') })
await expect(page.getByText('first.txt')).toBeVisible()
await expect(page.getByText('second.txt')).toBeVisible()
await expect(page.getByText('全部 2')).toBeVisible()
```

- [ ] **Step 2: 验证 E2E 测试先失败**

Run: `$env:E2E_BASE_URL='http://127.0.0.1:5173'; npm.cmd --prefix frontend test -- contract-inbox-workflow-e2e.spec.ts`

Expected: FAIL，第二次请求未调用追加端点或第二行不可见。

- [ ] **Step 3: 根据真实交互修正测试夹具并通过**

保持生产代码行为不再扩张，仅让 mock 响应、轮询状态与新增接口一致。

- [ ] **Step 4: 运行针对性测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_import_api.py backend/tests/test_import_models.py backend/tests/test_import_service.py backend/tests/test_import_tasks.py backend/tests/test_merge_readiness_unittest.py -q`

Expected: PASS，无失败。

Run: `npm.cmd --prefix frontend test -- import-inbox-store.spec.ts batch-store.spec.ts auth-inbox-reset.spec.ts contract-inbox-workflow-e2e.spec.ts`

Expected: PASS，无失败。

- [ ] **Step 5: 构建与完整质量门禁**

Run: `npm.cmd --prefix frontend run build`

Expected: TypeScript 与 Vite 构建 exit code 0。

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1`

Expected: 所有项目质量门禁通过；如存在与本改动无关的环境门禁，记录精确失败项，不声称全部通过。

- [ ] **Step 6: 浏览器实测**

测试流程：`/audit` 登录状态页面 -> 上传第一份合同 -> 继续添加第二份 -> 两行同时显示且总数为 2 -> 刷新页面 -> 两行恢复。检查正常、无效文件、服务端错误和桌面/移动视口；确认无框架错误层和相关控制台错误。

- [ ] **Step 7: 提交 E2E 回归测试**

```powershell
git add frontend/tests/contract-inbox-workflow-e2e.spec.ts
git commit -m "test: cover consecutive contract uploads"
```
