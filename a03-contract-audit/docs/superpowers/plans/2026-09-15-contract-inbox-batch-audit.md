# 待审合同批量审查 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在零勾选时一键审查全部就绪合同，同时保留选择部分合同和表头全选能力。

**Architecture:** `import-inbox` store 作为就绪集合与显式选择的唯一事实来源，提供提交目标和全选状态；`ContractInbox.vue` 仅渲染动态操作文案与选择控件；`AuditView.vue` 在点击时读取 ID 快照并调用既有批量接口。后端接口、权限和状态校验保持不变。

**Tech Stack:** Vue 3、TypeScript、Pinia、Element Plus、Playwright、Vite

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `frontend/src/stores/import-inbox.ts` | 计算就绪 ID、提交目标、全选与半选状态 |
| `frontend/tests/import-inbox-store.spec.ts` | 单元验证目标集合、全选和状态变化 |
| `frontend/src/components/audit/ContractInbox.vue` | 渲染表头全选、范围提示和动态主按钮 |
| `frontend/src/views/AuditView.vue` | 使用点击瞬间的目标 ID 快照提交审查 |
| `frontend/tests/contract-inbox-workflow-e2e.spec.ts` | 浏览器验证零选择、部分选择和无就绪项 |

### Task 1: Store 提供审查目标与全选状态

**Files:**
- Modify: `frontend/src/stores/import-inbox.ts:58-69,175-180,237-259`
- Test: `frontend/tests/import-inbox-store.spec.ts`

- [x] **Step 1: 写失败测试**

在 `frontend/tests/import-inbox-store.spec.ts` 增加第二个就绪项 fixture，并加入以下测试：

```ts
const secondReadyItem: ImportItem = {
  ...readyItem,
  id: 4,
  contract_id: 14,
  filename: '服务合同.pdf',
}

test('uses all ready items when there is no explicit selection', async () => {
  const store = createImportInboxStore(api({
    getImport: async () => ({
      ...batchFixture,
      total: 4,
      ready: 2,
      items: [...batchFixture.items, secondReadyItem],
    }),
  }), 'all-ready-targets')()

  await store.resume(batchFixture.id)

  expect(store.auditTargetIds).toEqual([readyItem.id, secondReadyItem.id])
  expect(store.allReadySelected).toBe(false)
  expect(store.someReadySelected).toBe(false)
})

test('uses only explicitly selected ready items', async () => {
  const store = createImportInboxStore(api({
    getImport: async () => ({
      ...batchFixture,
      total: 4,
      ready: 2,
      items: [...batchFixture.items, secondReadyItem],
    }),
  }), 'selected-targets')()

  await store.resume(batchFixture.id)
  store.toggleSelected(secondReadyItem.id)

  expect(store.auditTargetIds).toEqual([secondReadyItem.id])
  expect(store.allReadySelected).toBe(false)
  expect(store.someReadySelected).toBe(true)
})

test('toggles all ready items without selecting failed items', async () => {
  const store = createImportInboxStore(api({
    getImport: async () => ({
      ...batchFixture,
      total: 4,
      ready: 2,
      items: [...batchFixture.items, secondReadyItem],
    }),
  }), 'toggle-all-ready')()

  await store.resume(batchFixture.id)
  store.toggleAllReady()

  expect(store.selectedIds).toEqual([readyItem.id, secondReadyItem.id])
  expect(store.allReadySelected).toBe(true)
  expect(store.someReadySelected).toBe(false)

  store.toggleAllReady()
  expect(store.selectedIds).toEqual([])
})
```

- [x] **Step 2: 运行测试并确认失败**

Run:

```powershell
Set-Location frontend
npx.cmd playwright test tests/import-inbox-store.spec.ts
```

Expected: FAIL，提示 `auditTargetIds` 或 `toggleAllReady` 不存在。

- [x] **Step 3: 实现最小 store 能力**

在 `selectableIds` 后增加稳定顺序的就绪列表和派生状态：

```ts
const readyIds = computed(() => (
  batch.value?.items.filter((item) => item.status === 'ready').map((item) => item.id) ?? []
))
const selectableIds = computed(() => new Set(readyIds.value))
const auditTargetIds = computed(() => (
  selectedIds.value.length ? [...selectedIds.value] : [...readyIds.value]
))
const allReadySelected = computed(() => (
  readyIds.value.length > 0 && selectedIds.value.length === readyIds.value.length
))
const someReadySelected = computed(() => (
  selectedIds.value.length > 0 && !allReadySelected.value
))
```

在 `toggleSelected` 后加入全选切换：

```ts
function toggleAllReady() {
  selectedIds.value = allReadySelected.value ? [] : [...readyIds.value]
}
```

从 store 返回 `readyIds`、`auditTargetIds`、`allReadySelected`、`someReadySelected` 和 `toggleAllReady`。保留现有 `updateSelection()`，确保状态变化时移除不再就绪的 ID。

- [x] **Step 4: 运行 store 测试并确认通过**

Run:

```powershell
Set-Location frontend
npx.cmd playwright test tests/import-inbox-store.spec.ts
```

Expected: 全部测试 PASS，0 failed。

- [ ] **Step 5: 提交 Task 1**

```powershell
git add frontend/src/stores/import-inbox.ts frontend/tests/import-inbox-store.spec.ts
git commit -m "feat: add batch audit target selection"
```

### Task 2: 收件箱渲染双模式操作

**Files:**
- Modify: `frontend/src/components/audit/ContractInbox.vue:8-25,43-48,169-177,287-296,353-415`
- Modify: `frontend/src/views/AuditView.vue:185-198,377-391`
- Test: `frontend/tests/contract-inbox-workflow-e2e.spec.ts`

- [ ] **Step 1: 写零选择提交全部的失败 E2E 测试**

将测试路由记录 `/batches/from-import` 的请求体，并把既有工作流改为不勾选两行直接提交：

```ts
interface PrepareOptions {
  failContract11Result?: boolean
  failBatchCreate?: boolean
  onBatchCreate?: (body: { import_item_ids: number[]; dimensions: string[] }) => void
}

// /batches/from-import 既有路由分支的开头
if (path.endsWith('/batches/from-import') && method === 'POST') {
  options.onBatchCreate?.(
    route.request().postDataJSON() as { import_item_ids: number[]; dimensions: string[] },
  )
  if (options.failBatchCreate) {
    return fulfillJson(route, { detail: '审查服务暂不可用' }, 503)
  }
  return fulfillJson(route, {
    id: 88,
    status: 'partial_failed',
    total: 2,
    completed: 2,
    failed: 1,
    created_at: '2026-09-11T10:00:00Z',
    updated_at: '2026-09-11T10:00:00Z',
    items: [
      { id: 501, contract_id: 11, filename: '采购合同.txt', status: 'done', error: null, attempts: 0, started_at: null, finished_at: '2026-09-11T10:01:00Z' },
      { id: 502, contract_id: 12, filename: '开发协议.txt', status: 'failed', error: '模型服务暂不可用', attempts: 1, started_at: null, finished_at: '2026-09-11T10:01:00Z' },
    ],
  }, 202)
}

test('audits every ready contract without requiring row selection', async ({ page }) => {
  let submittedIds: number[] = []
  await prepare(page, {
    onBatchCreate: (body) => { submittedIds = body.import_item_ids },
  })
  await page.goto(`${baseUrl}/audit`)
  await page.locator('input[type="file"]').setInputFiles([
    { name: '采购合同.txt', mimeType: 'text/plain', buffer: Buffer.from('采购服务器设备') },
    { name: '开发协议.txt', mimeType: 'text/plain', buffer: Buffer.from('交付软件源代码') },
    { name: '扫描件.txt', mimeType: 'text/plain', buffer: Buffer.from('') },
  ])
  await page.getByRole('combobox', { name: '开发协议.txt 的合同类型' }).click()
  await page.getByRole('option', { name: '软件开发外包合同' }).click()
  await page.getByRole('button', { name: '确认 开发协议.txt' }).click()

  await expect(page.getByRole('button', { name: '审查全部 2 份就绪合同' })).toBeEnabled()
  await page.getByRole('button', { name: '审查全部 2 份就绪合同' }).click()

  expect(submittedIds).toEqual([1, 2])
})
```

- [ ] **Step 2: 运行 E2E 并确认失败**

Run:

```powershell
Set-Location frontend
npx.cmd playwright test tests/contract-inbox-workflow-e2e.spec.ts
```

Expected: FAIL，找不到“审查全部 2 份就绪合同”按钮。

- [ ] **Step 3: 扩展组件契约与动态文案**

给 `ContractInbox.vue` 增加 props 和事件：

```ts
const props = defineProps<{
  // 保留既有字段
  readyIds: number[]
  allReadySelected: boolean
  someReadySelected: boolean
}>()

const emit = defineEmits<{
  // 保留既有事件
  toggleAllReady: []
}>()

const auditButtonLabel = computed(() => {
  if (!counts.value.ready) return '暂无就绪合同'
  if (props.selectedIds.length) return `审查选中的 ${props.selectedIds.length} 份合同`
  return `审查全部 ${counts.value.ready} 份就绪合同`
})
```

把“选择”表头替换为带可访问名称的复选框：

```vue
<span class="select-header" role="columnheader">
  <input
    class="row-checkbox"
    type="checkbox"
    :checked="allReadySelected"
    :indeterminate.prop="someReadySelected"
    :disabled="readyIds.length === 0 || loading"
    aria-label="全选就绪合同"
    @change="emit('toggleAllReady')"
  >
</span>
```

把操作栏改为：

```vue
<footer class="action-bar">
  <span class="audit-scope-hint">
    {{ selectedIds.length ? `已选 ${selectedIds.length} 份就绪合同` : '待确认和失败合同不会进入审查' }}
  </span>
  <el-button
    type="primary"
    :loading="loading"
    :disabled="counts.ready === 0"
    :aria-label="auditButtonLabel"
    @click="emit('auditReady')"
  >{{ auditButtonLabel }}</el-button>
</footer>
```

增加必要样式，保证表头复选框居中、移动端按钮和提示可换行：

```css
.select-header { display: flex; align-items: center; justify-content: center; }
.audit-scope-hint { min-width: 0; overflow-wrap: anywhere; }

@media (max-width: 640px) {
  .action-bar { align-items: center; flex-wrap: wrap; }
  .action-bar :deep(.el-button) { flex: none; max-width: 100%; white-space: normal; }
}
```

- [ ] **Step 4: 视图提交目标 ID 快照**

修改 `AuditView.vue`：

```ts
async function auditReadyItems() {
  const targetIds = [...inbox.auditTargetIds]
  if (!targetIds.length) return
  try {
    const created = await batchStore.createFromImport(
      targetIds,
      dimensions.value.filter((item) => item.on).map((item) => item.key),
    )
    await router.replace({ query: { ...route.query, batch: String(created.id) } })
    ElMessage.success(`已提交 ${created.total} 份合同`)
    await inbox.pollOnce()
  } catch {
    ElMessage.error(batchStore.error || '审查批次提交失败')
  }
}
```

向 `ContractInbox` 传入并绑定：

```vue
:ready-ids="inbox.readyIds"
:all-ready-selected="inbox.allReadySelected"
:some-ready-selected="inbox.someReadySelected"
@toggle-all-ready="inbox.toggleAllReady"
```

- [ ] **Step 5: 更新既有 E2E 工作流断言**

在 `submitAndCompleteBatch()` 删除两次逐行 `.check()`，改为点击动态按钮：

```ts
await page.getByRole('button', { name: '审查全部 2 份就绪合同' }).click()
```

保留批次部分失败、重试、查看风险结果和空风险结果的既有断言，证明主流程没有回归。

- [ ] **Step 6: 运行相关 E2E 并确认通过**

Run:

```powershell
Set-Location frontend
npx.cmd playwright test tests/contract-inbox-workflow-e2e.spec.ts
```

Expected: 全部测试 PASS，0 failed。

- [ ] **Step 7: 提交 Task 2**

```powershell
git add frontend/src/components/audit/ContractInbox.vue frontend/src/views/AuditView.vue frontend/tests/contract-inbox-workflow-e2e.spec.ts
git commit -m "feat: audit all ready contracts by default"
```

### Task 3: 覆盖部分选择与无就绪状态

**Files:**
- Test: `frontend/tests/contract-inbox-workflow-e2e.spec.ts`
- Modify only if a test exposes a defect: `frontend/src/components/audit/ContractInbox.vue`
- Modify only if a test exposes a defect: `frontend/src/stores/import-inbox.ts`

- [ ] **Step 1: 增加部分选择测试**

```ts
test('audits only the explicitly selected ready contract', async ({ page }) => {
  let submittedIds: number[] = []
  await prepare(page, {
    onBatchCreate: (body) => { submittedIds = body.import_item_ids },
  })
  await page.goto(`${baseUrl}/audit`)
  await page.locator('input[type="file"]').setInputFiles([
    { name: '采购合同.txt', mimeType: 'text/plain', buffer: Buffer.from('采购服务器设备') },
    { name: '开发协议.txt', mimeType: 'text/plain', buffer: Buffer.from('交付软件源代码') },
  ])
  await page.getByRole('combobox', { name: '开发协议.txt 的合同类型' }).click()
  await page.getByRole('option', { name: '软件开发外包合同' }).click()
  await page.getByRole('button', { name: '确认 开发协议.txt' }).click()

  await page.getByRole('checkbox', { name: '选择采购合同.txt' }).check()
  await page.getByRole('button', { name: '审查选中的 1 份合同' }).click()

  expect(submittedIds).toEqual([1])
})
```

- [ ] **Step 2: 增加全选和无就绪状态测试**

```ts
test('selects only ready contracts from the table header', async ({ page }) => {
  await prepare(page)
  await page.goto(`${baseUrl}/audit`)
  await page.locator('input[type="file"]').setInputFiles([
    { name: '采购合同.txt', mimeType: 'text/plain', buffer: Buffer.from('采购服务器设备') },
    { name: '开发协议.txt', mimeType: 'text/plain', buffer: Buffer.from('交付软件源代码') },
    { name: '扫描件.txt', mimeType: 'text/plain', buffer: Buffer.from('') },
  ])

  await page.getByRole('checkbox', { name: '全选就绪合同' }).check()

  await expect(page.getByRole('checkbox', { name: '选择采购合同.txt' })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: '选择开发协议.txt' })).toBeDisabled()
  await expect(page.getByRole('checkbox', { name: '选择扫描件.txt' })).toBeDisabled()
})

test('disables the audit action when no contract is ready', async ({ page }) => {
  await prepare(page)
  await page.goto(`${baseUrl}/audit`)

  await expect(page.getByRole('button', { name: '暂无就绪合同' })).toBeDisabled()
})

test('keeps an explicit selection when batch creation fails', async ({ page }) => {
  await prepare(page, { failBatchCreate: true })
  await page.goto(`${baseUrl}/audit`)
  await page.locator('input[type="file"]').setInputFiles([
    { name: '采购合同.txt', mimeType: 'text/plain', buffer: Buffer.from('采购服务器设备') },
  ])
  const rowCheckbox = page.getByRole('checkbox', { name: '选择采购合同.txt' })
  await rowCheckbox.check()

  await page.getByRole('button', { name: '审查选中的 1 份合同' }).click()

  await expect(page.getByText('审查服务暂不可用')).toBeVisible()
  await expect(rowCheckbox).toBeChecked()
  await expect(page.getByRole('button', { name: '审查选中的 1 份合同' })).toBeEnabled()
})
```

- [ ] **Step 3: 运行相关测试，最小修复暴露的问题**

Run:

```powershell
Set-Location frontend
npx.cmd playwright test tests/import-inbox-store.spec.ts tests/contract-inbox-workflow-e2e.spec.ts
```

Expected: 全部测试 PASS，0 failed。若失败，只修复与目标集合、全选状态或动态文案直接相关的问题，不扩展范围。

- [ ] **Step 4: 运行前端静态验证与生产构建**

Run:

```powershell
Set-Location frontend
npm.cmd run type-check
npm.cmd run build
```

Expected: 两条命令退出码均为 0，无 TypeScript 或 Vite 构建错误。

- [ ] **Step 5: 浏览器验证桌面和移动端**

保持后端 `http://127.0.0.1:8000` 与前端 `http://127.0.0.1:5173` 运行，在 `1440x900` 和 `390x844` 验证：

```text
正常：零选择按钮显示“审查全部 N 份就绪合同”，点击提交全部就绪项
部分选择：按钮切换为“审查选中的 N 份合同”
空状态：显示“暂无就绪合同”且按钮禁用
错误/待确认：对应行不可选择，不进入提交集合
响应式：底部提示、按钮和复选框无重叠、截断或水平溢出
```

Expected: 两个视口无新增控制台错误，所有状态与设计文档一致。

- [ ] **Step 6: 运行项目完整质量门禁**

Run:

```powershell
Set-Location ..
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1
```

Expected: 质量门禁退出码为 0；如存在与本改动无关的既有失败，记录完整命令和失败项，不声明全部通过。

- [ ] **Step 7: 提交验收测试与必要修复**

```powershell
git add frontend/tests/contract-inbox-workflow-e2e.spec.ts frontend/src/components/audit/ContractInbox.vue frontend/src/stores/import-inbox.ts
git commit -m "test: cover batch audit selection modes"
```
