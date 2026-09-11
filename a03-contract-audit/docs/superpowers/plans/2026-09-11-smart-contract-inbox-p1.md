# 智能合同收件箱 P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有单份/批量两套上传流程合并为可恢复的智能合同收件箱，使混合类型合同能够逐份识别、确认、处理失败项并批量进入审查。

**Architecture:** 新增独立的 `ImportBatch`/`ImportBatchItem` 持久化边界，负责加密收件、异步解析、合同类型建议和人工确认；现有 `AuditBatch` 只从已就绪导入项创建审查任务。前端通过独立 API、Pinia store 和队列组件展示服务端状态，`AuditView.vue` 只负责组合收件箱与现有结果区。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy、Alembic、Celery、Pytest、Vue 3、TypeScript、Pinia、Element Plus、Playwright

**Scope:** 本计划仅实施设计文档中的 P1。复合合同辅助类型、疑似合并文件识别、批量筛选增强、分类阈值后台配置和运营指标分别留到 P2/P3。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/app/services/imports/classifier.py` | 根据文件名、解析文本和可用类型返回建议类型、置信度及依据 |
| `backend/app/services/imports/service.py` | 导入项状态机、汇总、权限、确认、移出和软删除规则 |
| `backend/app/tasks/import_tasks.py` | 异步解析合同并写回类型建议与导入项状态 |
| `backend/app/api/v1/endpoints/imports.py` | 创建/查询导入批次、确认、重试、移出和软删除端点 |
| `backend/app/schemas/import_batch.py` | 导入批次请求和响应模型 |
| `backend/app/api/v1/endpoints/batches.py` | 保留旧批量接口，并新增从已就绪导入项创建审查批次的端点 |
| `backend/app/api/deps.py` | 解析用户授权部门集合并提供统一权限判断 |
| `frontend/src/api/imports.ts` | 导入收件箱 API 和 TypeScript 契约 |
| `frontend/src/stores/import-inbox.ts` | 服务端批次恢复、轮询、确认、重试、移出与提交动作 |
| `frontend/src/components/audit/ContractInbox.vue` | 上传区、状态摘要、合同队列、行级操作和批量审查入口 |
| `frontend/src/views/AuditView.vue` | 组合新收件箱和现有审查结果区，移除旧上传卡片与批量弹窗 |

## Task 1：后端合同类型分类器

**Files:**
- Create: `backend/app/services/imports/__init__.py`
- Create: `backend/app/services/imports/classifier.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_contract_type_classifier.py`

- [ ] **Step 1: 编写分类器失败测试**

```python
from app.services.imports.classifier import classify_contract_type


TYPES = ["采购合同", "软件开发外包合同", "劳动合同", "租赁合同", "保密协议"]


def test_classifies_purchase_contract_with_high_confidence():
    result = classify_contract_type(
        filename="设备采购合同.pdf",
        text="甲方向乙方采购服务器设备，乙方负责供货和验收。",
        available_types=TYPES,
    )
    assert result.suggested_type == "采购合同"
    assert result.confidence >= 0.85
    assert "采购" in result.evidence


def test_returns_no_selection_when_evidence_is_too_weak():
    result = classify_contract_type(
        filename="扫描件03.pdf",
        text="双方经协商一致订立本文件。",
        available_types=TYPES,
    )
    assert result.suggested_type == ""
    assert result.confidence < 0.60


def test_only_returns_an_available_contract_type():
    result = classify_contract_type(
        filename="系统开发协议.docx",
        text="交付源代码并完成软件系统开发。",
        available_types=["技术开发合同", "采购合同"],
    )
    assert result.suggested_type == "技术开发合同"
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_contract_type_classifier.py -q`

Expected: FAIL，提示 `app.services.imports.classifier` 不存在。

- [ ] **Step 3: 实现确定性的分类器**

```python
# backend/app/services/imports/classifier.py
from dataclasses import dataclass


@dataclass(frozen=True)
class TypeSuggestion:
    suggested_type: str
    confidence: float
    evidence: list[str]


_FAMILIES = (
    (("采购", "购置", "供货", "设备"), ("采购",)),
    (("软件开发", "系统开发", "源代码", "技术开发"), ("软件开发", "技术开发")),
    (("劳动合同", "劳动关系", "试用期"), ("劳动",)),
    (("租赁", "出租方", "承租方"), ("租赁",)),
    (("保密", "商业秘密", "保密义务"), ("保密",)),
)


def classify_contract_type(*, filename: str, text: str, available_types: list[str]) -> TypeSuggestion:
    material = f"{filename}\n{text[:8000]}".lower()
    best_type = ""
    best_hits: list[str] = []
    for keywords, type_aliases in _FAMILIES:
        candidate = next(
            (value for value in available_types if any(alias in value for alias in type_aliases)),
            "",
        )
        if not candidate:
            continue
        hits = [keyword for keyword in keywords if keyword.lower() in material]
        if len(hits) > len(best_hits):
            best_type, best_hits = candidate, hits
    if not best_hits:
        return TypeSuggestion("", 0.0, [])
    confidence = {1: 0.58, 2: 0.76}.get(len(best_hits), 0.90)
    return TypeSuggestion(best_type, confidence, best_hits)
```

在 `Settings` 中集中定义交互阈值，后续 P3 只增加管理界面，不改变调用方契约：

```python
CONTRACT_TYPE_CONFIRM_THRESHOLD: float = 0.60
CONTRACT_TYPE_READY_THRESHOLD: float = 0.85
CONTRACT_TRASH_RETENTION_DAYS: int = 30
```

- [ ] **Step 4: 运行分类器测试并确认绿灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_contract_type_classifier.py -q`

Expected: `3 passed`。

- [ ] **Step 5: 提交分类器**

```powershell
git add backend/app/services/imports backend/app/core/config.py backend/tests/test_contract_type_classifier.py
git commit -m "feat: add contract type classifier"
```

## Task 2：导入批次、类型确认与软删除数据模型

**Files:**
- Modify: `backend/app/models/models.py`
- Create: `backend/alembic/versions/20260911_02_smart_contract_inbox.py`
- Test: `backend/tests/test_import_models.py`

- [ ] **Step 1: 编写模型失败测试**

```python
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.models import Contract, ImportBatch, ImportBatchItem, User


def test_import_batch_persists_file_level_classification():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="legal", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(
            filename="采购合同.pdf", storage_path="storage/a.pdf", uploaded_by=user.id,
            department="采购中心", suggested_type="采购合同", type_confidence=0.90,
        )
        batch = ImportBatch(owner_id=user.id, idempotency_key="import-model-1", total=1)
        batch.items.append(ImportBatchItem(filename=contract.filename, contract=contract, status="awaiting_confirmation"))
        db.add(batch)
        db.commit()

        saved = db.get(ImportBatch, batch.id)
        assert saved.items[0].contract.suggested_type == "采购合同"
        assert saved.items[0].contract.type_confidence == 0.90


def test_contract_soft_delete_fields_are_nullable_and_recoverable():
    deleted_at = datetime.now(timezone.utc)
    contract = Contract(
        filename="draft.pdf", storage_path="storage/draft.pdf", uploaded_by=1,
        deleted_at=deleted_at, deleted_by=1,
    )
    assert contract.deleted_at == deleted_at
    assert contract.deleted_by == 1
```

- [ ] **Step 2: 运行模型测试并确认红灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_import_models.py -q`

Expected: FAIL，提示 `ImportBatch`/`ImportBatchItem` 尚未定义。

- [ ] **Step 3: 增加 ORM 模型**

在 `User` 增加 `authorized_departments_json`；在 `Contract` 增加类型建议、确认和软删除字段；新增导入批次模型：

```python
class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key", name="uq_import_batches_owner_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="processing", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    ready: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    items: Mapped[list["ImportBatchItem"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class ImportBatchItem(Base):
    __tablename__ = "import_batch_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    batch: Mapped["ImportBatch"] = relationship(back_populates="items")
    contract: Mapped["Contract | None"] = relationship(lazy="joined")
```

`Contract` 字段使用以下签名：

```python
suggested_type: Mapped[str] = mapped_column(String(64), default="", server_default="")
type_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
type_evidence_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
type_confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
type_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
```

同时在 `AuditBatchItem` 增加来源追踪字段。它允许同一导入项在审查失败后创建新的重试任务，因此不加唯一约束：

```python
import_item_id: Mapped[int | None] = mapped_column(
    ForeignKey("import_batch_items.id"), nullable=True, index=True
)
```

- [ ] **Step 4: 编写并执行 Alembic 迁移**

迁移必须先创建两个导入表，再为 `audit_batch_items` 增加可空 `import_item_id` 外键及索引，并增加其余新列；`upgrade()` 将已有非空 `contracts.contract_type` 视为历史人工确认，填入 `type_confirmed_at=created_at`。`downgrade()` 按外键和索引逆序删除。

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m alembic upgrade head; .\.venv\Scripts\python.exe -m alembic current`

Expected: 当前 revision 为 `20260911_02 (head)`。

- [ ] **Step 5: 运行模型与迁移相关测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_import_models.py backend/tests/test_db_backend_selection.py -q`

Expected: 全部 PASS。

- [ ] **Step 6: 提交数据模型**

```powershell
git add backend/app/models/models.py backend/alembic/versions/20260911_02_smart_contract_inbox.py backend/tests/test_import_models.py
git commit -m "feat: persist contract import batches"
```

## Task 3：授权部门规则与登录上下文

**Files:**
- Modify: `backend/app/api/deps.py`
- Modify: `backend/app/api/v1/endpoints/auth.py`
- Modify: `backend/app/api/v1/endpoints/admin.py`
- Modify: `backend/app/schemas/contract.py`
- Modify: `backend/scripts/seed_demo.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/stores/auth.ts`
- Modify: `frontend/src/api/admin.ts`
- Modify: `frontend/src/views/AdminView.vue`
- Test: `backend/tests/test_department_access.py`
- Test: `frontend/tests/department-scope.spec.ts`

- [ ] **Step 1: 编写部门权限失败测试**

```python
import json
import pytest
from fastapi import HTTPException

from app.api.deps import allowed_departments, require_department_access
from app.models.models import User


def user(role: str, department: str, grants: list[str]) -> User:
    return User(
        username=role, password_hash="x", role=role, department=department,
        authorized_departments_json=json.dumps(grants, ensure_ascii=False),
    )


def test_business_user_is_limited_to_own_department():
    actor = user("business", "采购中心", ["法务部"])
    assert allowed_departments(actor) == {"采购中心"}


def test_legal_user_uses_configured_departments_and_keeps_own_department():
    actor = user("legal", "法务部", ["采购中心", "研发部"])
    assert allowed_departments(actor) == {"法务部", "采购中心", "研发部"}


def test_department_guard_rejects_out_of_scope_department():
    actor = user("legal", "法务部", ["采购中心"])
    with pytest.raises(HTTPException) as error:
        require_department_access(actor, "财务部")
    assert error.value.status_code == 403
```

- [ ] **Step 2: 运行权限测试并确认红灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_department_access.py -q`

Expected: FAIL，提示 `allowed_departments` 不存在。

- [ ] **Step 3: 实现统一权限函数与管理端点**

```python
# backend/app/api/deps.py
def allowed_departments(user: User) -> set[str]:
    if user.role == "business":
        return {user.department} if user.department else set()
    try:
        configured = json.loads(user.authorized_departments_json or "[]")
    except (TypeError, ValueError):
        configured = []
    return {user.department, *configured} - {""}


def require_department_access(user: User, department: str) -> None:
    if user.role == "admin":
        return
    if department not in allowed_departments(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作该数据归属部门")
```

登录响应增加 `authorized_departments`。管理端只新增部门授权所需的最小契约，不扩展为完整用户管理：

```python
class DepartmentScopeUserOut(BaseModel):
    id: int
    username: str
    role: str
    department: str
    authorized_departments: list[str]


class DepartmentScopeUpdate(BaseModel):
    departments: list[str] = Field(default_factory=list, max_length=100)
```

新增 `GET /admin/users/department-scopes` 和 `PUT /admin/users/{user_id}/departments`。列表只返回 `id/username/role/department/authorized_departments`；更新端点校验部门均存在于 `LookupItem(category="department")` 后写入 JSON，并记录 `department_scope_update` 审计日志。

- [ ] **Step 4: 前端保存授权部门并提供管理员编辑入口**

`LoginResult` 增加 `authorized_departments: string[]`，`auth` store 同步存入 `localStorage`。`admin.ts` 增加 `getDepartmentScopeUsers()` 和 `updateUserDepartments(userId, departments)`；`AdminView.vue` 在现有基础配置区域增加用户授权部门多选，不新增依赖。

- [ ] **Step 5: 增加前端权限上下文测试并运行**

```typescript
import { expect, test } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 frontend 后设置 E2E_BASE_URL')

test('persists authorized departments returned by login', async ({ page }) => {
  await page.route('**/api/v1/auth/login', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      access_token: 'test-token', token_type: 'bearer', role: 'legal',
      username: 'legal', department: '法务部',
      authorized_departments: ['法务部', '采购中心'],
    }),
  }))
  await page.goto(`${baseUrl}/login`)
  await page.locator('input[name="username"]').fill('legal')
  await page.locator('input[name="password"]').fill('legal123')
  await page.getByRole('button', { name: '登 录' }).click()
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('authorized_departments') || '[]')))
    .toEqual(['法务部', '采购中心'])
})
```

先在一个终端启动：`Set-Location frontend; npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort`

另一个终端运行：`Set-Location frontend; $env:E2E_BASE_URL='http://127.0.0.1:5173'; npm.cmd test -- department-scope.spec.ts`

Expected: PASS。

- [ ] **Step 6: 运行后端权限测试与前端类型检查**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_department_access.py backend/tests/test_admin_api.py -q`

Run: `Set-Location frontend; npm.cmd run type-check`

Expected: 全部 PASS，类型检查退出码为 0。

- [ ] **Step 7: 提交部门权限**

```powershell
git add backend/app/api/deps.py backend/app/api/v1/endpoints/auth.py backend/app/api/v1/endpoints/admin.py backend/app/schemas/contract.py backend/scripts/seed_demo.py frontend/src/api/types.ts frontend/src/stores/auth.ts frontend/src/api/admin.ts frontend/src/views/AdminView.vue backend/tests/test_department_access.py frontend/tests/department-scope.spec.ts
git commit -m "feat: enforce contract department scopes"
```

## Task 4：导入批次领域服务与异步解析任务

**Files:**
- Create: `backend/app/services/imports/service.py`
- Create: `backend/app/tasks/import_tasks.py`
- Modify: `backend/app/tasks/dispatcher.py`
- Modify: `backend/app/tasks/celery_app.py`
- Test: `backend/tests/test_import_service.py`
- Test: `backend/tests/test_import_tasks.py`

- [ ] **Step 1: 编写状态汇总和确认规则失败测试**

```python
import pytest
from app.services.imports.service import ImportConflict, summarize_import, target_status


def test_import_summary_separates_ready_confirmation_and_failures():
    result = summarize_import(["ready", "awaiting_confirmation", "failed", "parsing"])
    assert result.total == 4
    assert result.ready == 1
    assert result.failed == 1
    assert result.status == "processing"


@pytest.mark.parametrize(
    ("suggested_type", "confidence", "expected"),
    [("采购合同", 0.85, "ready"), ("采购合同", 0.84, "awaiting_confirmation"), ("", 0.20, "awaiting_confirmation")],
)
def test_target_status_uses_confidence_threshold(suggested_type, confidence, expected):
    assert target_status(suggested_type, confidence) == expected


def test_only_failed_import_item_can_retry():
    with pytest.raises(ImportConflict):
        target_status("采购合同", 0.9, current_status="ready", retry=True)
```

- [ ] **Step 2: 运行服务测试并确认红灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_import_service.py -q`

Expected: FAIL，提示服务模块不存在。

- [ ] **Step 3: 实现导入状态服务**

```python
IMPORT_ITEM_STATUSES = frozenset({"queued", "parsing", "awaiting_confirmation", "ready", "failed", "auditing", "done", "deleted"})


@dataclass(frozen=True)
class ImportSummary:
    total: int
    ready: int
    failed: int
    status: str


class ImportConflict(ValueError):
    pass


def target_status(suggested_type: str, confidence: float, *, current_status: str = "parsing", retry: bool = False) -> str:
    if retry and current_status != "failed":
        raise ImportConflict("仅失败导入项可以重试")
    return "ready" if suggested_type and confidence >= settings.CONTRACT_TYPE_READY_THRESHOLD else "awaiting_confirmation"


def summarize_import(statuses: list[str]) -> ImportSummary:
    visible = [value for value in statuses if value != "deleted"]
    ready = visible.count("ready")
    failed = visible.count("failed")
    active = any(value in {"queued", "parsing", "auditing"} for value in visible)
    status = "processing" if active else "needs_attention" if failed or "awaiting_confirmation" in visible else "ready"
    return ImportSummary(len(visible), ready, failed, status)
```

- [ ] **Step 4: 编写异步解析任务失败测试**

测试创建加密 TXT 合同和 `ImportBatchItem(status="queued")`，替换 `extract_document` 后执行 `parse_import_item.run(item.id)`，断言：

```python
assert item.status == "ready"
assert item.contract.status == "parsed"
assert item.contract.suggested_type == "采购合同"
assert item.contract.contract_type == "采购合同"
assert item.contract.type_confirmed_at is None
```

另一个测试让解析器抛出异常，断言 `status="failed"`、`error_code="PARSE_FAILED"`，并且错误响应不包含文件路径、密钥或异常原文。

- [ ] **Step 5: 实现异步解析任务和调度函数**

`parse_import_item` 依次执行：锁定导入项→状态改为 `parsing`→解析文件→读取 `LookupItem` 类型→调用分类器→写入 `elements_json`、类型建议、置信度和依据→按阈值写 `ready/awaiting_confirmation`。异常只写稳定错误码和用户可读文案。

```python
@celery_app.task(name="import.parse_item", bind=True)
def parse_import_item(self, item_id: int) -> dict:
    with SessionLocal() as db:
        item = db.get(ImportBatchItem, item_id)
        if not item or item.status in {"ready", "awaiting_confirmation", "deleted"}:
            return {"item_id": item_id, "status": "unchanged"}
        item.status = "parsing"
        item.attempts += 1
        db.commit()
        try:
            parsed = extract_document(item.contract.storage_path)
            elements = extract_elements(parsed.text)
            available = [row.value for row in db.query(LookupItem).filter(LookupItem.category == "contract_type")]
            suggestion = classify_contract_type(filename=item.filename, text=parsed.text, available_types=available)
            item.contract.elements_json = json.dumps(elements, ensure_ascii=False)
            item.contract.suggested_type = suggestion.suggested_type
            item.contract.type_confidence = suggestion.confidence
            item.contract.type_evidence_json = json.dumps(suggestion.evidence, ensure_ascii=False)
            item.contract.contract_type = (
                suggestion.suggested_type
                if suggestion.confidence >= settings.CONTRACT_TYPE_CONFIRM_THRESHOLD
                else ""
            )
            item.contract.status = "parsed"
            item.status = target_status(suggestion.suggested_type, suggestion.confidence)
            item.error_code = item.error_message = None
        except Exception:
            item.status = "failed"
            item.error_code = "PARSE_FAILED"
            item.error_message = "合同解析失败，请重新解析或删除草稿"
        refresh_import_batch(item.batch)
        db.commit()
        return {"item_id": item.id, "status": item.status}
```

- [ ] **Step 6: 运行服务与任务测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_import_service.py backend/tests/test_import_tasks.py -q`

Expected: 全部 PASS。

- [ ] **Step 7: 提交导入领域服务**

```powershell
git add backend/app/services/imports/service.py backend/app/tasks/import_tasks.py backend/app/tasks/dispatcher.py backend/app/tasks/celery_app.py backend/tests/test_import_service.py backend/tests/test_import_tasks.py
git commit -m "feat: process contract imports asynchronously"
```

## Task 5：导入收件箱 API

**Files:**
- Create: `backend/app/schemas/import_batch.py`
- Create: `backend/app/api/v1/endpoints/imports.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/test_import_api.py`

- [ ] **Step 1: 编写创建、恢复和失败隔离的失败测试**

```python
def test_create_import_keeps_valid_files_when_one_file_is_invalid(monkeypatch, tmp_path):
    result = imports.create_import(
        files=[upload("采购合同.txt", b"采购设备"), upload("病毒.exe", b"bad")],
        idempotency_key="mixed-import-1", department="采购中心", db=db, user=legal,
    )
    assert result.total == 2
    assert [item.status for item in result.items] == ["queued", "failed"]
    assert result.items[1].error_code == "UNSUPPORTED_FILE_TYPE"
    assert db.query(Contract).count() == 1


def test_create_import_is_idempotent_per_owner(monkeypatch, tmp_path):
    first = imports.create_import([upload("合同.txt", b"正文")], "stable-key", "法务部", db, legal)
    second = imports.create_import([upload("合同.txt", b"正文")], "stable-key", "法务部", db, legal)
    assert second.id == first.id
    assert db.query(ImportBatch).count() == 1


def test_get_import_rejects_an_unrelated_user():
    with pytest.raises(HTTPException) as error:
        imports.get_import(batch.id, db=db, user=other_department_business_user)
    assert error.value.status_code == 403
```

- [ ] **Step 2: 编写确认、重试和删除语义失败测试**

覆盖以下断言：

```python
assert confirm_item(..., body=ConfirmImportItem(contract_type="采购合同", department="采购中心"), ...).status == "ready"
assert db.get(Contract, contract.id).type_confirmed_by == legal.id
assert retry_item(failed_item.id, ...).status == "queued"
assert remove_failed_upload(upload_failed_item.id, ...).status_code == 204
assert delete_contract_draft(parse_failed_item.id, ...).status == "deleted"
assert db.get(Contract, contract.id).deleted_at is not None
assert db.query(AuditLog).filter(AuditLog.action == "contract_draft_delete").count() == 1
```

审查中的合同调用删除端点必须返回 `409 CONTRACT_BUSY`。

- [ ] **Step 3: 运行 API 测试并确认红灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_import_api.py -q`

Expected: FAIL，提示 `imports` 端点模块不存在。

- [ ] **Step 4: 定义稳定响应契约**

```python
ImportItemStatus = Literal["queued", "parsing", "awaiting_confirmation", "ready", "failed", "auditing", "done", "deleted"]


class ImportItemOut(BaseModel):
    id: int
    contract_id: int | None
    filename: str
    status: ImportItemStatus
    error_code: str | None = None
    error_message: str | None = None
    suggested_type: str = ""
    confidence: float | None = None
    confirmed_type: str = ""
    department: str = ""
    requires_review: bool = False


class ImportBatchOut(BaseModel):
    id: int
    status: Literal["processing", "needs_attention", "ready"]
    total: int
    ready: int
    failed: int
    created_at: datetime
    updated_at: datetime
    items: list[ImportItemOut] = Field(default_factory=list)


class ConfirmImportItem(BaseModel):
    contract_type: str = Field(min_length=1, max_length=64)
    department: str = Field(min_length=1, max_length=64)
```

端点使用显式映射函数组装嵌套合同字段，不依赖 Pydantic 自动跨关系猜测：

```python
def _item_out(item: ImportBatchItem) -> ImportItemOut:
    contract = item.contract
    return ImportItemOut(
        id=item.id, contract_id=item.contract_id, filename=item.filename, status=item.status,
        error_code=item.error_code, error_message=item.error_message,
        suggested_type=contract.suggested_type if contract else "",
        confidence=contract.type_confidence if contract else None,
        confirmed_type=contract.contract_type if contract else "",
        department=contract.department if contract else "",
        requires_review=contract.requires_review if contract else False,
    )
```

- [ ] **Step 5: 实现端点和逐文件上传规则**

新增路由：

```text
POST   /api/v1/imports
GET    /api/v1/imports/{batch_id}
PATCH  /api/v1/imports/{batch_id}/items/{item_id}
POST   /api/v1/imports/{batch_id}/items/{item_id}/retry
DELETE /api/v1/imports/{batch_id}/items/{item_id}/record
DELETE /api/v1/imports/{batch_id}/items/{item_id}/draft
POST   /api/v1/imports/{batch_id}/items/{item_id}/restore
```

创建端点逐文件校验扩展名、空文件、单文件大小、同批重名和 500MB 总量。合法文件写入加密存储和 `Contract`；非法文件只生成 `ImportBatchItem(status="failed", contract_id=None)`。数据库提交成功后才派发解析任务；派发失败保持 `queued` 并写 `DISPATCH_PENDING`，不删除已提交文件。

`record` 端点只允许删除 `contract_id is None` 的失败项；`draft` 端点只允许未审查合同，写 `deleted_at/deleted_by` 和审计日志；`restore` 仅管理员可调用且必须在 `settings.CONTRACT_TRASH_RETENTION_DAYS` 窗口内。该配置已在 Task 1 定义，默认值为 30。

- [ ] **Step 6: 运行导入 API 测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_import_api.py backend/tests/test_import_tasks.py -q`

Expected: 全部 PASS。

- [ ] **Step 7: 提交导入 API**

```powershell
git add backend/app/schemas/import_batch.py backend/app/api/v1/endpoints/imports.py backend/app/api/v1/router.py backend/tests/test_import_api.py
git commit -m "feat: add recoverable contract import api"
```

## Task 6：从就绪导入项创建审查批次

**Files:**
- Modify: `backend/app/schemas/batch.py`
- Modify: `backend/app/services/audit/jobs.py`
- Modify: `backend/app/api/v1/endpoints/batches.py`
- Modify: `backend/app/tasks/audit_tasks.py`
- Test: `backend/tests/test_batch_from_import.py`
- Modify: `backend/tests/test_batch_api.py`

- [ ] **Step 1: 编写混合类型审查批次失败测试**

```python
def test_create_audit_batch_from_ready_mixed_import_items(monkeypatch):
    result = batches.create_batch_from_import(
        body=BatchFromImportRequest(
            import_item_ids=[purchase_item.id, software_item.id],
            dimensions=["legal", "payment"],
        ),
        idempotency_key="audit-from-import-1",
        db=db,
        user=legal,
    )
    assert result.total == 2
    saved_types = [db.get(Contract, item.contract_id).contract_type for item in result.items]
    assert saved_types == ["采购合同", "软件开发外包合同"]


def test_batch_from_import_rejects_non_ready_item():
    with pytest.raises(HTTPException) as error:
        batches.create_batch_from_import(
            BatchFromImportRequest(import_item_ids=[awaiting_item.id], dimensions=[]),
            "not-ready-key", db, legal,
        )
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "IMPORT_ITEM_NOT_READY"
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_batch_from_import.py -q`

Expected: FAIL，提示 `BatchFromImportRequest` 或端点不存在。

- [ ] **Step 3: 定义请求并实现事务性批次创建**

```python
class BatchFromImportRequest(BaseModel):
    import_item_ids: list[int] = Field(min_length=1, max_length=200)
    dimensions: list[str] = Field(default_factory=list)
```

新增 `POST /api/v1/batches/from-import`。在单个数据库事务中锁定所有导入项，校验：属于当前用户可访问范围、状态均为 `ready`、合同未软删除、确认类型非空且没有活跃审查。随后创建一个 `AuditBatch` 和多个带 `import_item_id` 的 `AuditBatchItem`，逐份保留合同自身 `contract_type`，并将导入项改为 `auditing`。提交后派发任务，沿用现有 `DISPATCH_PENDING` 恢复策略。

幂等指纹由排序后的导入项 ID、各合同确认类型和审查维度共同生成；同一幂等键配不同请求返回 409。

- [ ] **Step 4: 回写导入项的审查状态**

`audit_tasks.py` 在审查成功事务中把来源导入项改为 `done`；任务失败时改回 `ready`，审查错误仍保存在 `AuditBatchItem`，用户无需重新上传即可重新创建审查任务。每次回写后调用 `refresh_import_batch`。

在 `test_batch_from_import.py` 增加以下断言：

```python
run_contract_audit.run(contract.id, ["legal"], audit_item.id)
db.refresh(import_item)
assert import_item.status == "done"

failed_result = run_contract_audit.run(failing_contract.id, ["legal"], failing_audit_item.id)
db.refresh(failing_import_item)
assert failed_result["status"] == "failed"
assert failing_import_item.status == "ready"
```

- [ ] **Step 5: 保留旧 `/batches` 文件上传端点兼容性**

旧端点继续通过现有测试，但前端不再调用。补充弃用说明到 docstring，不删除路由，避免历史调用方立即中断。

- [ ] **Step 6: 运行审查批次回归测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_batch_from_import.py backend/tests/test_batch_api.py backend/tests/test_batch_service.py -q`

Expected: 全部 PASS。

- [ ] **Step 7: 提交批次解耦**

```powershell
git add backend/app/schemas/batch.py backend/app/services/audit/jobs.py backend/app/api/v1/endpoints/batches.py backend/app/tasks/audit_tasks.py backend/tests/test_batch_from_import.py backend/tests/test_batch_api.py
git commit -m "feat: create audits from ready import items"
```

## Task 7：前端导入 API 与 Pinia store

**Files:**
- Create: `frontend/src/api/imports.ts`
- Create: `frontend/src/stores/import-inbox.ts`
- Modify: `frontend/src/api/batches.ts`
- Modify: `frontend/src/stores/batch.ts`
- Test: `frontend/tests/import-inbox-store.spec.ts`
- Modify: `frontend/tests/batch-store.spec.ts`

- [ ] **Step 1: 编写 store 失败测试**

```typescript
import { expect, test } from '@playwright/test'
import { createPinia, setActivePinia } from 'pinia'
import { createImportInboxStore, type ImportApi } from '../src/stores/import-inbox'

test.beforeEach(() => setActivePinia(createPinia()))

test('keeps failed items while allowing ready items to be selected', async () => {
  const api: ImportApi = {
    createImport: async () => batchFixture,
    getImport: async () => batchFixture,
    confirmItem: async () => batchFixture.items[0],
    retryItem: async () => batchFixture.items[1],
    removeFailedRecord: async () => undefined,
    deleteDraft: async () => batchFixture.items[1],
  }
  const store = createImportInboxStore(api, 'test-import')()
  await store.resume(12)
  store.toggleSelected(readyItem.id)
  store.toggleSelected(failedItem.id)
  expect(store.selectedIds).toEqual([readyItem.id])
  expect(store.summary).toEqual({ total: 2, ready: 1, needsConfirmation: 0, failed: 1 })
})


test('removes an upload failure through the record endpoint only', async () => {
  let removed = 0
  const store = createImportInboxStore({ ...apiFixture, removeFailedRecord: async () => { removed += 1 } }, 'remove-import')()
  await store.resume(12)
  await store.removeRecord(failedWithoutContract.id)
  expect(removed).toBe(1)
  expect(store.batch?.items).not.toContainEqual(expect.objectContaining({ id: failedWithoutContract.id }))
})
```

- [ ] **Step 2: 运行 store 测试并确认红灯**

Run: `Set-Location frontend; npm.cmd test -- import-inbox-store.spec.ts`

Expected: FAIL，提示 store 不存在。

- [ ] **Step 3: 定义前端 API 契约**

```typescript
export type ImportItemStatus = 'queued' | 'parsing' | 'awaiting_confirmation' | 'ready' | 'failed' | 'auditing' | 'done' | 'deleted'

export interface ImportItem {
  id: number
  contract_id: number | null
  filename: string
  status: ImportItemStatus
  error_code: string | null
  error_message: string | null
  suggested_type: string
  confidence: number | null
  confirmed_type: string
  department: string
  requires_review: boolean
}

export interface ImportBatch {
  id: number
  status: 'processing' | 'needs_attention' | 'ready'
  total: number
  ready: number
  failed: number
  created_at: string
  updated_at: string
  items: ImportItem[]
}
```

实现 `createImport`、`getImport`、`confirmItem`、`retryItem`、`removeFailedRecord` 和 `deleteDraft`。错误展示统一读取 `{detail: {code, message}}`，无法识别时回退为“操作失败，请稍后重试”。

- [ ] **Step 4: 实现 store 状态和轮询**

store 以服务端批次为事实来源，只把 `selectedIds` 和当前轮询控制保存在内存。创建成功后把 `importId` 写入 URL 查询参数，由 `AuditView` 在刷新时恢复；不把合同文件或服务端状态复制到 `localStorage`。

```typescript
const selectableIds = computed(() => new Set(
  batch.value?.items.filter(item => item.status === 'ready').map(item => item.id) ?? [],
))

function toggleSelected(id: number) {
  if (!selectableIds.value.has(id)) return
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter(value => value !== id)
    : [...selectedIds.value, id]
}
```

只要存在 `queued/parsing/auditing` 项就每 1.5 秒轮询；全部进入稳定状态后停止。登出调用 `reset()` 停止计时器。

- [ ] **Step 5: 扩展审查批次 store**

`batches.ts` 新增 `createBatchFromImport(importItemIds, dimensions, idempotencyKey)`；`batch.ts` 新增 `createFromImport`，保留原 `create(files, contractType, dimensions)` 供旧代码和兼容测试使用。

- [ ] **Step 6: 运行 store 测试和类型检查**

Run: `Set-Location frontend; npm.cmd test -- import-inbox-store.spec.ts batch-store.spec.ts; npm.cmd run type-check`

Expected: 测试全部 PASS，类型检查退出码 0。

- [ ] **Step 7: 提交前端数据层**

```powershell
git add frontend/src/api/imports.ts frontend/src/stores/import-inbox.ts frontend/src/api/batches.ts frontend/src/stores/batch.ts frontend/tests/import-inbox-store.spec.ts frontend/tests/batch-store.spec.ts
git commit -m "feat: add contract import inbox store"
```

## Task 8：合同收件箱队列组件

**Files:**
- Create: `frontend/src/components/audit/ContractInbox.vue`
- Test: `frontend/tests/contract-inbox-e2e.spec.ts`

- [ ] **Step 1: 编写空状态、混合状态和行级操作失败测试**

```typescript
test('shows one upload entry and file-level mixed contract types', async ({ page }) => {
  await mockImportApis(page, mixedBatchFixture)
  await openAudit(page)
  await expect(page.getByRole('heading', { name: '待审合同' })).toBeVisible()
  await expect(page.getByText('批量上传（支持50份以上）')).toHaveCount(0)
  await expect(page.getByText('采购合同.pdf')).toBeVisible()
  await expect(page.getByText('软件开发协议.docx')).toBeVisible()
  await expect(page.getByRole('combobox', { name: '采购合同.pdf 的合同类型' })).toHaveValue('采购合同')
  await expect(page.getByRole('combobox', { name: '软件开发协议.docx 的合同类型' })).toHaveValue('软件开发外包合同')
})


test('uses different actions for upload and parse failures', async ({ page }) => {
  await mockImportApis(page, failureBatchFixture)
  await openAudit(page)
  await expect(page.getByRole('button', { name: '移出 病毒.exe' })).toBeVisible()
  await expect(page.getByRole('button', { name: '重新解析 扫描件.pdf' })).toBeVisible()
  await expect(page.getByRole('button', { name: '删除合同草稿 扫描件.pdf' })).toBeVisible()
})
```

- [ ] **Step 2: 运行组件 E2E 并确认红灯**

先启动前端：`Set-Location frontend; npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort`

另一个终端运行：`Set-Location frontend; $env:E2E_BASE_URL='http://127.0.0.1:5173'; npm.cmd test -- contract-inbox-e2e.spec.ts`

Expected: FAIL，找不到“待审合同”。

- [ ] **Step 3: 实现组件公开契约**

```typescript
const props = defineProps<{
  items: ImportItem[]
  contractTypes: string[]
  departments: string[]
  selectedIds: number[]
  canChangeDepartment: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  upload: [files: File[]]
  confirm: [itemId: number, contractType: string, department: string]
  retry: [itemId: number]
  removeRecord: [itemId: number]
  deleteDraft: [itemId: number]
  toggleSelected: [itemId: number]
  auditReady: []
}>()
```

组件包含：唯一拖拽上传区、状态摘要、桌面表格式队列、移动端纵向布局和底部批量操作栏。类型下拉始终允许修改；中置信度显示“待确认”；部门仅在法务/财务/管理员下可编辑。所有图标按钮使用 Element Plus 已注册图标，并提供 `aria-label` 和 tooltip。

- [ ] **Step 4: 实现删除确认边界**

`移出记录` 直接 emit，不弹窗；`删除合同草稿` 使用 `ElMessageBox.confirm`，正文明确“合同草稿进入回收站 30 天，尚未产生审查结果”。上传中和审查中不渲染删除按钮。

- [ ] **Step 5: 运行组件 E2E 与响应式检查**

Run: `Set-Location frontend; $env:E2E_BASE_URL='http://127.0.0.1:5173'; npm.cmd test -- contract-inbox-e2e.spec.ts`

Expected: 全部 PASS；390×844 视口断言 `documentElement.scrollWidth - innerWidth <= 0`。

- [ ] **Step 6: 提交收件箱组件**

```powershell
git add frontend/src/components/audit/ContractInbox.vue frontend/tests/contract-inbox-e2e.spec.ts
git commit -m "feat: build smart contract inbox queue"
```

## Task 9：在审查页接入统一收件箱

**Files:**
- Modify: `frontend/src/views/AuditView.vue`
- Modify: `frontend/src/stores/auth.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/tests/contract-upload-session.spec.ts`
- Modify: `frontend/tests/enterprise-ui.spec.ts`
- Test: `frontend/tests/contract-inbox-workflow-e2e.spec.ts`

- [ ] **Step 1: 编写完整工作流失败测试**

```typescript
test('uploads mixed contracts, confirms one exception and audits ready items', async ({ page }) => {
  await routeInboxWorkflow(page)
  await openAudit(page)
  await page.locator('input[type="file"]').setInputFiles([
    file('采购合同.txt', '采购服务器设备'),
    file('开发协议.txt', '交付软件源代码'),
    file('扫描件.txt', ''),
  ])
  await expect(page.getByText('可以审查', { exact: true })).toBeVisible()
  await expect(page.getByText('待确认', { exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: '开发协议.txt 的合同类型' }).click()
  await page.getByRole('option', { name: '软件开发外包合同' }).click()
  await page.getByRole('button', { name: '确认 开发协议.txt' }).click()
  await page.getByRole('checkbox', { name: '选择采购合同.txt' }).check()
  await page.getByRole('checkbox', { name: '选择开发协议.txt' }).check()
  await page.getByRole('button', { name: '审查就绪项' }).click()
  await expect(page.getByText('已提交 2 份合同')).toBeVisible()
})


test('restores import batch from the url after reload', async ({ page }) => {
  await routeInboxWorkflow(page)
  await page.goto(`${baseUrl}/audit?import=42`)
  await expect(page.getByText('采购合同.txt')).toBeVisible()
  await page.reload()
  await expect(page.getByText('采购合同.txt')).toBeVisible()
})
```

- [ ] **Step 2: 运行工作流测试并确认红灯**

Run: `Set-Location frontend; $env:E2E_BASE_URL='http://127.0.0.1:5173'; npm.cmd test -- contract-inbox-workflow-e2e.spec.ts`

Expected: FAIL，页面仍使用旧上传流程。

- [ ] **Step 3: 替换旧页面组合逻辑**

在 `AuditView.vue` 中删除旧单份上传卡片、页面级 `contractType`、`batchOpen` 弹窗和相关 CSS。引入 `ContractInbox`、`useImportInboxStore` 和现有 `useBatchStore`：

```typescript
async function uploadFiles(files: File[]) {
  const batch = await inbox.create(files, auth.department)
  await router.replace({ query: { ...route.query, import: String(batch.id) } })
}

async function auditReadyItems() {
  if (!inbox.selectedIds.length) return
  const batch = await batchStore.createFromImport(
    inbox.selectedIds,
    dimensions.value.filter(item => item.on).map(item => item.key),
  )
  ElMessage.success(`已提交 ${batch.total} 份合同`)
  await inbox.pollOnce()
}
```

进入页面时若查询参数存在合法 `import` ID，则恢复导入批次；卸载页面和退出登录时停止轮询。保留现有审查结果、风险复核、整改和报告功能，不重写其业务逻辑。

- [ ] **Step 4: 更新旧测试断言**

`contract-upload-session.spec.ts` 改为新服务端导入状态契约；`enterprise-ui.spec.ts` 断言“待审合同”和唯一上传入口，不再查找“批量上传（支持50份以上）”。`client.ts` 和 `auth.ts` 在 401/退出时清理授权部门并停止导入轮询。

- [ ] **Step 5: 运行所有相关前端测试**

Run: `Set-Location frontend; $env:E2E_BASE_URL='http://127.0.0.1:5173'; npm.cmd test -- contract-inbox-e2e.spec.ts contract-inbox-workflow-e2e.spec.ts contract-upload-session.spec.ts enterprise-ui.spec.ts batch-store.spec.ts import-inbox-store.spec.ts`

Expected: 全部 PASS。

- [ ] **Step 6: 运行类型检查与构建**

Run: `Set-Location frontend; npm.cmd run type-check; npm.cmd run build`

Expected: 两个命令退出码均为 0。

- [ ] **Step 7: 浏览器人工验证**

启动后端和前端，分别检查：

1. 正常：上传两种合同、确认低置信度项、仅审查已选就绪项。
2. 空状态：无合同记录时只有明确导入入口，无必填错误。
3. 错误：上传失败可直接移出；解析失败可重试或删除草稿。
4. 恢复：刷新页面后导入批次仍在。
5. 响应式：1440×900、768×1024、390×844 无重叠和横向溢出。

- [ ] **Step 8: 提交页面集成**

```powershell
git add frontend/src/views/AuditView.vue frontend/src/stores/auth.ts frontend/src/api/client.ts frontend/tests/contract-upload-session.spec.ts frontend/tests/enterprise-ui.spec.ts frontend/tests/contract-inbox-workflow-e2e.spec.ts
git commit -m "feat: integrate smart contract inbox"
```

## Task 10：端到端验收、文档同步与完整质量门禁

**Files:**
- Modify: `backend/.env.example`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-11-smart-contract-inbox-design.md`（仅当实现产生已确认差异）
- Test: `backend/tests/test_import_api.py`
- Test: `frontend/tests/contract-inbox-workflow-e2e.spec.ts`

- [ ] **Step 1: 补充 52 文件边界回归测试**

后端接口测试创建 52 个小型 TXT 文件，至少覆盖采购、技术开发、劳动、租赁和无法识别五类；断言总数为 52、单个非法文件不阻断其余项、每个合法文件具有独立合同记录。该测试只验证批量行为，不宣称真实合同分类准确率达到 90%。

```python
assert result.total == 52
assert len(result.items) == 52
assert sum(item.contract_id is not None for item in result.items) == 51
assert sum(item.error_code == "UNSUPPORTED_FILE_TYPE" for item in result.items) == 1
```

- [ ] **Step 2: 更新配置与启动说明**

在 `.env.example` 增加：

```dotenv
# 合同草稿进入回收站后的默认保留天数
CONTRACT_TRASH_RETENTION_DAYS=30
```

README 说明：单份和批量均从“待审合同”入口进入；查询参数 `?import=<id>` 用于恢复当前收件箱；旧 `/batches` 文件上传接口保留兼容但新界面不再调用。

- [ ] **Step 3: 运行后端完整测试**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests -q`

Expected: 全部 PASS，0 failures。

- [ ] **Step 4: 运行前端完整测试、类型检查与构建**

Run: `Set-Location frontend; npm.cmd test; npm.cmd run type-check; npm.cmd run build`

Expected: 全部退出码为 0。未设置 `E2E_BASE_URL` 时服务型 E2E 明确 SKIP，不得误报为已实测。

- [ ] **Step 5: 运行带真实服务的项目质量门禁**

先确认 `127.0.0.1:8000` 和 `127.0.0.1:5173` 未被其他进程占用，再运行：

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1 -IncludeE2E`

Expected: `evaluation`、`backend`、`frontend`、`type-check`、`build` 全部为 `passed`；`.quality-gate/summary.json` 中 `status` 为 `passed`。

- [ ] **Step 6: 核对需求与工作区**

Run: `git diff --check; git status --short; git log --oneline -10`

确认 P1 验收项逐项有测试证据；不提交 `.env`、数据库、合同文件、日志、`outputs/`、`.quality-gate/` 或 `.superpowers/`。

- [ ] **Step 7: 提交验收与文档更新**

```powershell
git add backend/.env.example README.md backend/tests/test_import_api.py frontend/tests/contract-inbox-workflow-e2e.spec.ts
git commit -m "test: verify smart contract inbox workflow"
```

## 最终验收矩阵

| P1 要求 | 实施任务 | 验证证据 |
|---|---|---|
| 单份/批量统一入口 | Task 8、9 | `contract-inbox-e2e.spec.ts` |
| 文件级自动分类与人工修正 | Task 1、4、5、8 | 分类器测试、导入 API 测试、组件 E2E |
| 混合类型创建审查批次 | Task 6、9 | `test_batch_from_import.py`、工作流 E2E |
| 单项失败不阻断整批 | Task 5、10 | 导入 API 的部分失败与 52 文件测试 |
| 上传失败可移出 | Task 5、7、8 | API 删除语义测试、组件 E2E |
| 解析失败可重试或删除草稿 | Task 4、5、8 | 任务、API 和组件测试 |
| 部门自动带出与授权修改 | Task 3、8、9 | 部门权限测试、前端权限测试 |
| 刷新恢复与上传幂等 | Task 5、7、9 | API 幂等测试、恢复 E2E |
| 已落库操作审计留痕 | Task 3、5、6 | 审计日志断言 |
| 正常/空/错误/响应式状态 | Task 8、9、10 | 服务型 Playwright 和人工截图复核 |
