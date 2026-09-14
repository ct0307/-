# Audit Real-Time Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为批量合同审查增加后端持久化、真实里程碑驱动、刷新可恢复的百分比进度，并在现有 Vue 批次页面展示批次与单项进度条。

**Architecture:** `AuditBatchItem` 保存权威单项百分比与阶段；独立进度服务用 generation/execution-token 条件更新保证单调和防陈旧 worker。审查 runner 与 auditor 只在解析完成、顶层窗口完成、核验完成和最终持久化等真实里程碑上报；批次 API 聚合“活跃项实际进度 + 终态项 100% 处理贡献”，前端继续每 1.5 秒轮询。

**Tech Stack:** Python 3.13、FastAPI、SQLAlchemy、Alembic、Pytest、Vue 3、TypeScript、Pinia、Element Plus、Playwright。

---

## 文件结构

- 新建 `backend/app/services/audit/progress.py`：纯进度计算与带执行围栏的数据库更新。
- 新建 `backend/alembic/versions/20260914_01_audit_item_progress.py`：生产数据库字段、回填和降级。
- 修改 `backend/app/models/models.py`、`backend/app/db/init_db.py`：ORM 字段与 SQLite 开发热迁移。
- 修改 `backend/app/services/audit/auditor.py`、`backend/app/services/audit/runner.py`、`backend/app/tasks/audit_tasks.py`：真实里程碑上报和终态一致性。
- 修改 `backend/app/services/batch/service.py`、`backend/app/schemas/batch.py`：单项回退和批次处理进度聚合。
- 修改 `frontend/src/api/batches.ts`、`frontend/src/stores/batch.ts`、`frontend/src/utils/audit-progress.ts`、`frontend/src/views/AuditView.vue`：类型、阶段文案和进度条。
- 修改后端及前端既有测试文件：先失败、再最小实现、最后回归。

### Task 1: 进度领域规则与数据库结构

**Files:**
- Create: `backend/app/services/audit/progress.py`
- Create: `backend/alembic/versions/20260914_01_audit_item_progress.py`
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/db/init_db.py`
- Test: `backend/tests/test_batch_service.py`
- Test: `backend/tests/test_merge_readiness_unittest.py`

- [ ] **Step 1: 写进度归一化和批次贡献的失败测试**

```python
def test_progress_is_clamped_and_never_reaches_100_before_success():
    assert normalize_progress(-1, terminal_success=False) == 0
    assert normalize_progress(100, terminal_success=False) == 99
    assert normalize_progress(100, terminal_success=True) == 100

def test_terminal_failure_counts_as_processed_without_faking_item_success():
    progress = summarize(
        ["reviewing", "failed"],
        progresses=[50, 35],
    )
    assert progress.progress == 75
```

- [ ] **Step 2: 运行测试并确认因 API 不存在而失败**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_batch_service.py -q`

Expected: FAIL，提示 `normalize_progress` 不存在或 `BatchProgress` 没有 `progress`。

- [ ] **Step 3: 实现纯规则与 ORM 字段**

```python
ProgressStage = Literal[
    "queued", "claimed", "parsing", "reviewing",
    "verifying", "persisting", "completed", "failed",
]

def normalize_progress(value: int, *, terminal_success: bool = False) -> int:
    return max(0, min(100 if terminal_success else 99, int(value)))

def item_contribution(status: str, progress: int) -> int:
    if status in TERMINAL_ITEM_STATUSES:
        return 100
    return normalize_progress(progress)
```

在 `AuditBatchItem` 增加：

```python
progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
progress_stage: Mapped[str] = mapped_column(
    String(24), default="queued", server_default="queued",
)
```

迁移新增非空字段并按状态回填：`queued=0`、`parsing=5`、`reviewing=15`、`validating=90`、`done/review_required=100`、`failed=0`；SQLite 热迁移声明相同默认值。

- [ ] **Step 4: 运行领域和迁移测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_batch_service.py backend/tests/test_merge_readiness_unittest.py -q`

Expected: PASS。

### Task 2: 带执行围栏的单调进度写入

**Files:**
- Modify: `backend/app/services/audit/progress.py`
- Modify: `backend/app/tasks/audit_tasks.py`
- Test: `backend/tests/test_audit_job_service.py`

- [ ] **Step 1: 写单调、同值去重和陈旧 worker 失败测试**

```python
def test_publish_progress_is_monotonic_and_fenced(db, claimed_item):
    assert publish_progress(db, item_id=claimed_item.id, contract_id=claimed_item.contract_id,
        generation=1, execution_token="owner", progress=40, stage="reviewing")
    assert not publish_progress(db, item_id=claimed_item.id, contract_id=claimed_item.contract_id,
        generation=1, execution_token="owner", progress=40, stage="reviewing")
    assert publish_progress(db, item_id=claimed_item.id, contract_id=claimed_item.contract_id,
        generation=1, execution_token="owner", progress=20, stage="verifying")
    assert claimed_item.progress == 40
    assert claimed_item.progress_stage == "verifying"
    assert not publish_progress(db, item_id=claimed_item.id, contract_id=claimed_item.contract_id,
        generation=1, execution_token="stale", progress=80, stage="reviewing")
```

- [ ] **Step 2: 运行测试确认缺少写入函数而失败**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_audit_job_service.py -q`

Expected: FAIL，提示 `publish_progress` 不存在。

- [ ] **Step 3: 实现条件更新和任务侧 best-effort reporter**

```python
def publish_progress(db: Session, *, item_id: int, contract_id: int,
                     generation: int, execution_token: str,
                     progress: int, stage: ProgressStage) -> bool:
    candidate = normalize_progress(progress)
    updated = db.query(AuditBatchItem).filter(
        AuditBatchItem.id == item_id,
        AuditBatchItem.contract_id == contract_id,
        AuditBatchItem.audit_generation == generation,
        AuditBatchItem.execution_token == execution_token,
        AuditBatchItem.status.notin_(TERMINAL_ITEM_STATUSES),
        or_(AuditBatchItem.progress < candidate,
            AuditBatchItem.progress_stage != stage),
    ).update({
        AuditBatchItem.progress: case(
            (AuditBatchItem.progress < candidate, candidate),
            else_=AuditBatchItem.progress,
        ),
        AuditBatchItem.progress_stage: stage,
    }, synchronize_session=False)
    db.commit() if updated else db.rollback()
    return updated == 1
```

`run_contract_audit` 领取成功时在同一事务写 `progress=max(existing, 5)` 和 `progress_stage="claimed"`；构造独立短会话 reporter，捕获并记录数据库异常但不改变审查结果。失败终态只写 `progress_stage="failed"`，不覆盖 `progress`；重试改回 `queued` 阶段但保留数值。

- [ ] **Step 4: 运行任务与围栏测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_audit_job_service.py backend/tests/test_batch_api.py -q`

Expected: PASS。

### Task 3: 在真实审查里程碑上报进度

**Files:**
- Modify: `backend/app/services/audit/auditor.py`
- Modify: `backend/app/services/audit/runner.py`
- Modify: `backend/app/tasks/audit_tasks.py`
- Test: `backend/tests/test_audit_runner_quality.py`
- Test: `backend/tests/test_review_pipeline.py`

- [ ] **Step 1: 写里程碑顺序和窗口计数失败测试**

```python
def test_audit_reports_real_milestones(monkeypatch, contract):
    events = []
    run_audit(db, contract, progress_callback=lambda value, stage: events.append((value, stage)))
    assert events[0] == (15, "parsing")
    assert events == sorted(events, key=lambda event: event[0])
    assert (90, "verifying") in events

def test_top_level_windows_drive_review_progress(monkeypatch):
    events = []
    audit_contract(elements, text, progress_callback=lambda value, stage: events.append((value, stage)))
    reviewing = [value for value, stage in events if stage == "reviewing"]
    assert reviewing
    assert reviewing[-1] == 75
```

- [ ] **Step 2: 运行测试并确认 callback 参数缺失而失败**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_audit_runner_quality.py backend/tests/test_review_pipeline.py -q`

Expected: FAIL，提示不接受 `progress_callback`。

- [ ] **Step 3: 实现解析、窗口、核验和持久化里程碑**

新增回调类型并逐层透传：

```python
ProgressCallback = Callable[[int, ProgressStage], None]
```

`_compute_audit` 在 `extract_document` 成功后上报 `(15, "parsing")`；`audit_contract` 预先计算启用 Agent 数与顶层窗口总数，每个 `reviewer.review(...)` 完成并返回后递增：

```python
value = 15 + (60 * completed_units // planned_units)
progress_callback(value, "reviewing")
```

全部 Agent（含证据 grounding）结束后上报 82%，冲突检测和二次复核结束后上报 90%，阶段均为 `verifying`。runner 发布 `validating` 状态时在同一事务写 95%/`persisting`；最终结果事务对 `done`/`review_required` 原子写 100%/`completed`。

- [ ] **Step 4: 运行审查相关测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_audit_runner_quality.py backend/tests/test_review_pipeline.py backend/tests/test_secondary_review.py -q`

Expected: PASS。

### Task 4: 扩展批次 API 和历史兼容

**Files:**
- Modify: `backend/app/services/batch/service.py`
- Modify: `backend/app/schemas/batch.py`
- Modify: `backend/app/api/v1/endpoints/batches.py`
- Test: `backend/tests/test_batch_api.py`

- [ ] **Step 1: 写 API 字段和批次聚合失败测试**

```python
def test_batch_api_returns_item_and_batch_progress(client, batch):
    response = client.get(f"/api/v1/batches/{batch.id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["progress"] == 75
    assert body["items"][0]["progress"] == 50
    assert body["items"][0]["progress_stage"] == "reviewing"
```

- [ ] **Step 2: 运行 API 测试确认新字段缺失而失败**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_batch_api.py -q`

Expected: FAIL，JSON 没有 `progress` 或 `progress_stage`。

- [ ] **Step 3: 实现后端权威聚合**

`BatchItemOut` 增加受限整数 `progress` 与 `ProgressStage`；历史对象缺字段时使用状态回退。`BatchOut` 增加 `progress`，`_refresh_batch` 调用：

```python
summary = summarize(
    [item.status for item in batch.items],
    progresses=[item.progress for item in batch.items],
)
batch_progress = summary.progress
```

API 输出通过 schema validator 写入 `progress`，不新增 `AuditBatch.progress` 数据库字段。零项目返回 0。

- [ ] **Step 4: 运行批次后端测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_batch_service.py backend/tests/test_batch_api.py backend/tests/test_audit_job_service.py -q`

Expected: PASS。

### Task 5: 前端批次与单项进度条

**Files:**
- Modify: `frontend/src/api/batches.ts`
- Modify: `frontend/src/stores/batch.ts`
- Modify: `frontend/src/utils/audit-progress.ts`
- Modify: `frontend/src/views/AuditView.vue`
- Test: `frontend/tests/batch-store.spec.ts`
- Test: `frontend/tests/audit-progress.spec.ts`
- Test: `frontend/tests/audit-reliability-e2e.spec.ts`

- [ ] **Step 1: 写后端百分比透传、阶段文案和失败显示测试**

```typescript
test('store uses authoritative backend batch progress', async () => {
  const store = createBatchStore(api)
  await store.resume(7)
  expect(store.progress).toBe(43)
})

test('failed item keeps its last percentage and failure label', () => {
  expect(auditProgressDisplay({ progress: 68, progress_stage: 'failed' })).toEqual({
    label: '审查失败', percentage: 68, indeterminate: false,
  })
})
```

- [ ] **Step 2: 运行前端测试确认类型或断言失败**

Run: `npm.cmd --prefix frontend test -- --run frontend/tests/batch-store.spec.ts frontend/tests/audit-progress.spec.ts frontend/tests/audit-reliability-e2e.spec.ts`

Expected: FAIL，现有 store 仍计算 `completed / total` 且单项无字段。

- [ ] **Step 3: 实现类型、文案、模板与响应式样式**

```typescript
export type AuditProgressStage = 'queued' | 'claimed' | 'parsing' | 'reviewing'
  | 'verifying' | 'persisting' | 'completed' | 'failed'

export interface AuditBatchItem {
  // 既有字段
  progress: number
  progress_stage: AuditProgressStage
}

export interface AuditBatch {
  // 既有字段
  progress: number
}
```

store 的 `progress` 直接返回 `batch.value?.progress ?? 0`。页面顶部进度状态只在批次失败时为 `exception`；每个 item 的主体区加入 `el-progress`、百分比和阶段文案。失败项保持红色，不把百分比改成 100；CSS 用稳定 grid/flex 约束和 `min-width: 0`、`overflow-wrap: anywhere` 保证移动端不重叠。

- [ ] **Step 4: 运行前端测试、类型检查和构建**

Run: `npm.cmd --prefix frontend test -- --run frontend/tests/batch-store.spec.ts frontend/tests/audit-progress.spec.ts frontend/tests/audit-reliability-e2e.spec.ts`

Run: `npm.cmd --prefix frontend run type-check`

Run: `npm.cmd --prefix frontend run build`

Expected: 全部退出码 0。

### Task 6: 浏览器验收与完整质量门禁

**Files:**
- Modify when needed: preceding implementation/test files only
- Update: `.planning/audit-real-time-progress/progress.md`（被忽略的本地记录）

- [ ] **Step 1: 确认前后端服务与测试工具用法**

Run: `python C:\Users\chentao\.agents\skills\webapp-testing\scripts\with_server.py --help`

Expected: 帮助输出成功；若 8000/5173 已运行则直接复用，不重复启动。

- [ ] **Step 2: 浏览器验证关键状态**

用 Playwright 等待 `networkidle` 后验证桌面和移动端：正常运行中的批次、空状态、失败项、刷新恢复；记录截图与控制台错误。所有进度来自 API fixture 或真实后端响应，不使用前端定时伪造。

- [ ] **Step 3: 运行完整质量门禁**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1`

Expected: evaluation、backend、frontend、type-check、build 全部退出码 0。

- [ ] **Step 4: 检查最终差异和分支状态**

Run: `git diff --check; git status --short --branch; git diff --stat master...HEAD`

Expected: 无空白错误；只包含本功能设计、计划、代码、迁移和测试，不包含 `.env`、数据库、日志、输出或用户未跟踪文件。

## 自检结果

- 设计中的真实里程碑、单调更新、99% 上限、失败保留、终态处理贡献、现有轮询、刷新恢复和响应式要求均有对应任务。
- 无 `TBD`、`TODO`、占位实现或未定义接口。
- `progress`、`progress_stage`、`ProgressStage`、`progress_callback` 命名在后端、API、前端和测试中保持一致。
