# Batch Result Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户从批次完成列表一次点击即可在审查页查看对应合同的风险详情并继续人工复核。

**Architecture:** 在 `audit-session` store 中增加只读恢复已完成审查结果的方法，通过现有审查状态和风险接口先完整取数、再原子更新会话。`AuditView` 将图标按钮替换为文字按钮，负责调用 store、展示加载/错误状态并滚动到结果区；历史页保持独立查询职责。

**Tech Stack:** Vue 3、TypeScript、Pinia、Element Plus、Playwright

---

## 文件结构

- Modify: `frontend/src/stores/audit-session.ts`：提供 `loadCompletedAudit(contractId, filename)`，恢复审查状态、质量信息、协同检查和风险。
- Modify: `frontend/src/views/AuditView.vue`：提供可识别的结果按钮、忙碌状态、结果区定位和真实空状态。
- Modify: `frontend/tests/contract-inbox-workflow-e2e.spec.ts`：覆盖批次完成后直接查看、切换合同、空结果和加载错误。

### Task 1: 先用端到端测试定义“一次点击直达结果”

**Files:**
- Modify: `frontend/tests/contract-inbox-workflow-e2e.spec.ts`

- [x] **Step 1: 为完成合同补齐审查状态和风险接口桩**

在 `prepare()` 的路由处理器中加入：

```ts
if (path.endsWith('/contracts/11/audit-status')) {
  return fulfillJson(route, {
    contract_id: 11,
    status: 'done',
    job_id: 501,
    risk_count: 1,
    cross_checks: [],
    requires_review: false,
    ocr_confidence: 0.96,
    review_reason: null,
  })
}
if (path.endsWith('/contracts/11/risks')) {
  return fulfillJson(route, [{
    id: 701,
    agent: 'legal',
    level: 'high',
    category: '付款条款',
    original_text: '验收后一次性付款',
    risk_reason: '缺少明确付款期限',
    basis: '《中华人民共和国民法典》第五百零九条',
    suggestion: '约定验收后十个工作日内付款',
    confidence: 0.94,
    tier: 'red',
    review_status: 'pending',
    rag_sources: [],
    evidence_status: 'supported',
    original_text_verified: true,
    requires_manual_review: true,
    support_relation_status: 'supported',
    support_validation_reason: '依据支持结论',
    support_validator_version: 'test',
  }])
}
```

- [x] **Step 2: 把旧的历史页跳转断言改为同页结果断言**

```ts
await page.getByRole('button', { name: '查看 采购合同.txt 的审查结果' }).click()
await expect(page).toHaveURL(/\/audit/)
await expect(page.getByText('当前查看')).toBeVisible()
await expect(page.getByRole('heading', { name: '采购合同.txt' })).toBeVisible()
await expect(page.getByText('付款条款', { exact: true })).toBeVisible()
await expect(page.getByText('进入复核', { exact: true })).toBeVisible()
```

- [x] **Step 3: 运行测试并确认因尚未实现而失败**

Run:

```powershell
Set-Location frontend
$env:E2E_BASE_URL='http://127.0.0.1:5173'
npx.cmd playwright test tests/contract-inbox-workflow-e2e.spec.ts --grep "uploads mixed contracts"
```

Expected: FAIL，点击后 URL 仍进入 `/history`，或审查详情未出现。

- [x] **Step 4: 提交测试基线**

```powershell
git add frontend/tests/contract-inbox-workflow-e2e.spec.ts
git commit -m "test: define direct batch result interaction"
```

### Task 2: 在审查会话中恢复已完成结果

**Files:**
- Modify: `frontend/src/stores/audit-session.ts`

- [x] **Step 1: 增加只读恢复方法**

在 store 中加入并导出以下方法。接口全部成功后才更新页面状态，失败时保留当前会话：

```ts
async function loadCompletedAudit(selectedContractId: number, selectedFilename: string) {
  if (busy.value) throw new Error('当前任务处理中，请稍后再试')
  busy.value = true
  try {
    const initial = await getAuditStatus(selectedContractId)
    const result = await waitForAuditTerminal(
      async () => initial,
      { intervalMs: 0, maxAttempts: 1 },
    )
    const loadedRisks = await getRisks(selectedContractId, result.job_id)

    contractId.value = selectedContractId
    filename.value = selectedFilename
    elements.value = null
    applyQuality(result)
    crossChecks.value = result.cross_checks ?? []
    risks.value = loadedRisks
    step.value = 2
    return result
  } finally {
    busy.value = false
  }
}
```

- [x] **Step 2: 运行类型检查**

Run:

```powershell
Set-Location frontend
npm.cmd run type-check
```

Expected: PASS，无 TypeScript 错误。

- [x] **Step 3: 提交 store 改动**

```powershell
git add frontend/src/stores/audit-session.ts
git commit -m "feat: restore completed audit results"
```

### Task 3: 将批次入口改为同页直达并补齐状态 UI

**Files:**
- Modify: `frontend/src/views/AuditView.vue`

- [x] **Step 1: 改造点击处理器和结果区定位**

引入 `nextTick`，增加当前加载项，并让按钮调用 store：

```ts
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const openingContractId = ref<number | null>(null)

async function openBatchResult(contractId: number, filename: string) {
  openingContractId.value = contractId
  try {
    await session.loadCompletedAudit(contractId, filename)
    await nextTick()
    document.querySelector<HTMLElement>('[data-audit-detail]')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (error) {
    const detail = error instanceof Error ? `：${error.message}` : ''
    ElMessage.error(`审查结果加载失败${detail}`)
  } finally {
    openingContractId.value = null
  }
}
```

- [x] **Step 2: 用文字按钮替代圆形图标按钮**

```vue
<el-button
  v-if="item.status === 'done'"
  class="batch-result-action"
  type="primary"
  plain
  :icon="View"
  :loading="openingContractId === item.contract_id"
  :disabled="openingContractId !== null && openingContractId !== item.contract_id"
  :aria-label="`查看 ${item.filename} 的审查结果`"
  @click="openBatchResult(item.contract_id, item.filename)"
>
  查看审查结果
</el-button>
```

- [x] **Step 3: 只展示真实存在的数据并增加风险空状态**

给详情根节点添加 `data-audit-detail`。当 `session.risks.length === 0` 时显示：

```vue
<el-empty
  v-if="session.risks.length === 0"
  :image-size="72"
  description="该合同未检出风险"
/>
```

仅当 `session.elements` 存在时显示“合同关键要素”列；否则风险清单占满可用宽度，避免把未加载的要素错误显示为“未检出”。

- [x] **Step 4: 补充桌面和移动端稳定布局**

```css
.batch-result-action {
  flex: none;
  min-width: 118px;
}
.result-two-col.single-col {
  grid-template-columns: minmax(0, 1fr);
}
@media (max-width: 640px) {
  .batch-result-action {
    width: 100%;
  }
}
```

- [x] **Step 5: 运行目标端到端测试并确认通过**

Run:

```powershell
Set-Location frontend
$env:E2E_BASE_URL='http://127.0.0.1:5173'
npx.cmd playwright test tests/contract-inbox-workflow-e2e.spec.ts --grep "uploads mixed contracts"
```

Expected: PASS；URL 保持 `/audit`，一次点击显示对应风险和复核入口。

- [x] **Step 6: 提交 UI 改动**

```powershell
git add frontend/src/views/AuditView.vue
git commit -m "feat: open batch audit results inline"
```

### Task 4: 补齐切换、空结果和错误回归

**Files:**
- Modify: `frontend/tests/contract-inbox-workflow-e2e.spec.ts`
- Modify: `frontend/src/views/AuditView.vue`（仅在测试暴露问题时）

- [x] **Step 1: 增加合同切换和空结果断言**

为合同 12 返回 `done` 状态和空风险数组，点击第二份合同后断言：

```ts
await page.getByRole('button', { name: '查看 开发协议.txt 的审查结果' }).click()
await expect(page.getByRole('heading', { name: '开发协议.txt' })).toBeVisible()
await expect(page.getByText('该合同未检出风险')).toBeVisible()
await expect(page.getByText('付款条款', { exact: true })).toHaveCount(0)
```

- [x] **Step 2: 增加加载失败断言**

让一次 `/contracts/11/audit-status` 请求返回 500，断言页面显示“审查结果加载失败”，批次区域仍然可见且原有详情不被半成品覆盖。

```ts
await expect(page.locator('.el-message').last()).toContainText('审查结果加载失败')
await expect(page.getByRole('region', { name: '审查批次 88' })).toBeVisible()
```

- [x] **Step 3: 运行完整文件测试**

Run:

```powershell
Set-Location frontend
$env:E2E_BASE_URL='http://127.0.0.1:5173'
npx.cmd playwright test tests/contract-inbox-workflow-e2e.spec.ts
```

Expected: PASS，文件内全部用例通过。

- [x] **Step 4: 提交回归测试**

```powershell
git add frontend/tests/contract-inbox-workflow-e2e.spec.ts frontend/src/views/AuditView.vue
git commit -m "test: cover batch result states"
```

### Task 5: 完成质量门禁和浏览器验收

**Files:**
- Verify only

- [x] **Step 1: 运行前端类型检查和构建**

```powershell
Set-Location frontend
npm.cmd run type-check
npm.cmd run build
```

Expected: 两条命令均以退出码 0 完成。

- [x] **Step 2: 运行项目完整质量门禁**

```powershell
Set-Location ..
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1
```

Expected: 质量门禁通过；若存在与本次改动无关的既有失败，记录具体命令和错误，不宣称全量通过。

- [x] **Step 3: 浏览器实测桌面和移动端**

桌面宽度 `1440x900`、移动端宽度 `390x844` 分别验证：

```text
正常：完成项按钮 -> 同页详情 -> 风险抽屉 -> 确认/忽略入口
空状态：无风险合同展示“该合同未检出风险”
错误：接口失败提示明确，批次汇总不消失
响应式：文件名、状态标签和按钮不重叠，按钮文字不溢出
```

- [x] **Step 4: 检查最终差异**

```powershell
git diff --check
git status --short
```

Expected: 无空白错误；只包含计划内文件或已明确说明的用户既有改动。
