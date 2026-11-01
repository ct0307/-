import { expect, test, type Page, type Route } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 frontend 后设置 E2E_BASE_URL')

function importItem(status: 'parsing' | 'ready' | 'failed', overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    contract_id: status === 'failed' ? null : 41,
    filename: '可靠性测试合同.pdf',
    status,
    error_code: status === 'failed' ? 'MODEL_TIMEOUT' : null,
    error_message: status === 'failed' ? '模型响应超时，请稍后重试' : null,
    suggested_type: '软件开发外包合同',
    confidence: status === 'failed' ? null : 0.96,
    confirmed_type: status === 'failed' ? '' : '软件开发外包合同',
    department: status === 'failed' ? '' : '法务部',
    requires_review: false,
    ...overrides,
  }
}

function importBatch(status: 'parsing' | 'ready' | 'failed') {
  const item = importItem(status)
  return {
    id: 42,
    status: status === 'parsing' ? 'processing' : status === 'ready' ? 'ready' : 'needs_attention',
    total: 1,
    ready: status === 'ready' ? 1 : 0,
    failed: status === 'failed' ? 1 : 0,
    created_at: '2026-09-11T08:00:00Z',
    updated_at: '2026-09-11T08:00:00Z',
    items: [item],
  }
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function openAudit(page: Page, path = '/audit') {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('authorized_departments', JSON.stringify(['法务部']))
  })
  await page.goto(`${baseUrl}${path}`)
  await page.waitForLoadState('networkidle')
}

function auditBatch(overrides: Record<string, unknown> = {}) {
  return {
    id: 77,
    status: 'running',
    total: 2,
    completed: 0,
    failed: 0,
    progress: 43,
    created_at: '2026-09-14T08:00:00Z',
    updated_at: '2026-09-14T08:00:00Z',
    items: [
      {
        id: 701,
        contract_id: 901,
        filename: '正在审查的超长合同文件名用于验证移动端换行不遮挡.pdf',
        status: 'reviewing',
        progress: 43,
        progress_stage: 'reviewing',
        error: null,
        attempts: 1,
        started_at: '2026-09-14T08:00:00Z',
        finished_at: null,
      },
      {
        id: 702,
        contract_id: 902,
        filename: '失败合同.pdf',
        status: 'failed',
        progress: 68,
        progress_stage: 'failed',
        error: '模型响应超时，请稍后重试',
        attempts: 1,
        started_at: '2026-09-14T08:00:00Z',
        finished_at: '2026-09-14T08:01:00Z',
      },
    ],
    ...overrides,
  }
}

test('restores authoritative batch and item progress after reload without a success state', async ({ page }) => {
  let batchGetCalls = 0

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-14T08:00:00Z' })
    }
    if (isLookup(path)) return fulfillJson(route, [])
    if (path.endsWith('/batches/77')) {
      batchGetCalls += 1
      return fulfillJson(route, auditBatch({ failed: 1 }))
    }
    return fulfillJson(route, [])
  })

  await page.setViewportSize({ width: 375, height: 800 })
  await openAudit(page, '/audit?batch=77')

  const batchProgress = page.locator('.batch-result > .batch-result-progress')
  await expect(batchProgress).toHaveAttribute('aria-valuenow', '43')
  await expect(batchProgress).not.toHaveClass(/is-success/)
  await expect(page.getByText('正在审查', { exact: true })).toBeVisible()
  const itemProgressRow = page.locator('.batch-result-item')
    .filter({ hasText: '正在审查的超长合同文件名用于验证移动端换行不遮挡.pdf' })
    .locator('.batch-result-item-progress-row')
  await expect(itemProgressRow.locator('.el-progress')).toHaveAttribute('aria-valuenow', '43')
  await expect(itemProgressRow.getByText('43%', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

  await page.reload()
  await page.waitForLoadState('networkidle')

  await expect(batchProgress).toHaveAttribute('aria-valuenow', '43')
  await expect(batchProgress).not.toHaveClass(/is-success/)
  const failedProgressRow = page.locator('.batch-result-item')
    .filter({ hasText: '失败合同.pdf' })
    .locator('.batch-result-item-progress-row')
  await expect(failedProgressRow.locator('.el-progress')).toHaveAttribute('aria-valuenow', '68')
  await expect(failedProgressRow.getByText('68%', { exact: true })).toBeVisible()
  await expect(failedProgressRow.getByText('审查失败', { exact: true })).toBeVisible()
  expect(batchGetCalls).toBeGreaterThanOrEqual(2)
})

test('keeps import and audit progress when navigating away and back', async ({ page }) => {
  let importGetCalls = 0
  let batchGetCalls = 0

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-16T08:00:00Z' })
    }
    if (isLookup(path)) return fulfillJson(route, [])
    if (path.endsWith('/imports/42')) {
      importGetCalls += 1
      return fulfillJson(route, importBatch('parsing'))
    }
    if (path.endsWith('/batches/77')) {
      batchGetCalls += 1
      return fulfillJson(route, auditBatch())
    }
    return fulfillJson(route, [])
  })

  await openAudit(page, '/audit?import=42&batch=77')
  await expect(page.getByText('批次 #77', { exact: true })).toBeVisible()
  await expect(page.getByText('可靠性测试合同.pdf', { exact: true })).toBeVisible()

  await page.getByRole('menuitem', { name: '工作台' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await page.getByRole('menuitem', { name: '合同审查' }).click()
  await expect(page).toHaveURL(/\/audit$/)

  await expect(page.getByText('批次 #77', { exact: true })).toBeVisible()
  await expect(page.getByText('可靠性测试合同.pdf', { exact: true })).toBeVisible()
  expect(importGetCalls).toBeGreaterThanOrEqual(2)
  expect(batchGetCalls).toBeGreaterThanOrEqual(2)
})

test('renders an active batch progress in the neutral state without failed items', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-14T08:00:00Z' })
    }
    if (isLookup(path)) return fulfillJson(route, [])
    if (path.endsWith('/batches/77')) {
      return fulfillJson(route, auditBatch({
        total: 1,
        items: [auditBatch().items[0]],
      }))
    }
    return fulfillJson(route, [])
  })

  await openAudit(page, '/audit?batch=77')

  const batchProgress = page.locator('.batch-result > .batch-result-progress')
  await expect(batchProgress).toHaveAttribute('aria-valuenow', '43')
  await expect(batchProgress.getByText('43%', { exact: true })).toBeVisible()
  await expect(batchProgress).not.toHaveClass(/is-success/)
  await expect(batchProgress).not.toHaveClass(/is-exception/)
})

for (const [stage, label] of [
  ['discovering', '正在发现风险'],
  ['enriching', '正在补充理由与建议'],
] as const) {
  for (const width of [375, 1280]) {
    test(`renders ${stage} at ${width}px with the unchanged completed-work percentage`, async ({ page }) => {
      await page.route('**/api/v1/**', async (route) => {
        const path = new URL(route.request().url()).pathname
        if (path.endsWith('/runtime/status')) {
          return fulfillJson(route, { status: 'online', checked_at: '2026-11-01T08:00:00Z' })
        }
        if (isLookup(path)) return fulfillJson(route, [])
        if (path.endsWith('/batches/77')) {
          return fulfillJson(route, auditBatch({
            total: 1, progress: 15,
            items: [{ ...auditBatch().items[0], progress: 15, progress_stage: stage }],
          }))
        }
        return fulfillJson(route, [])
      })

      await page.setViewportSize({ width, height: 800 })
      await openAudit(page, '/audit?batch=77')
      const row = page.locator('.batch-result-item-progress-row')
      await expect(row.getByText(label, { exact: true })).toBeVisible()
      await expect(row.locator('.el-progress')).toHaveAttribute('aria-valuenow', '15')
      await expect(row.locator('.el-progress')).not.toHaveClass(/is-success/)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    })
  }
}

test('advances persisted progress through polling without reloading the page', async ({ page }) => {
  let batchGetCalls = 0
  const reviewingItem = auditBatch().items[0]
  const responses = [
    auditBatch({
      total: 1,
      items: [{ ...reviewingItem, progress: 43 }],
    }),
    auditBatch({
      total: 1,
      progress: 72,
      items: [{ ...reviewingItem, progress: 72 }],
    }),
    auditBatch({
      status: 'done',
      total: 1,
      completed: 1,
      progress: 100,
      items: [{
        ...reviewingItem,
        status: 'done',
        progress: 100,
        progress_stage: 'completed',
        finished_at: '2026-09-14T08:03:00Z',
      }],
    }),
  ]

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-14T08:00:00Z' })
    }
    if (isLookup(path)) return fulfillJson(route, [])
    if (path.endsWith('/batches/77')) {
      const response = responses[Math.min(batchGetCalls, responses.length - 1)]
      batchGetCalls += 1
      return fulfillJson(route, response)
    }
    return fulfillJson(route, [])
  })

  await openAudit(page, '/audit?batch=77')

  const batchProgress = page.locator('.batch-result > .batch-result-progress')
  const itemProgressRow = page.locator('.batch-result-item-progress-row')
  const itemProgress = itemProgressRow.locator('.el-progress')
  await expect(batchProgress).toHaveAttribute('aria-valuenow', '43')
  await expect(itemProgress).toHaveAttribute('aria-valuenow', '43')
  await expect(itemProgressRow.getByText('正在审查', { exact: true })).toBeVisible()

  await expect(batchProgress).toHaveAttribute('aria-valuenow', '72', { timeout: 4_000 })
  await expect(itemProgress).toHaveAttribute('aria-valuenow', '72')
  await expect(itemProgressRow.getByText('正在审查', { exact: true })).toBeVisible()

  await expect(batchProgress).toHaveAttribute('aria-valuenow', '100', { timeout: 4_000 })
  await expect(batchProgress).toHaveClass(/is-success/)
  await expect(itemProgress).toHaveAttribute('aria-valuenow', '100')
  await expect(itemProgress).toHaveClass(/is-success/)
  await expect(itemProgressRow.getByText('审查完成', { exact: true })).toBeVisible()
  expect(batchGetCalls).toBeGreaterThanOrEqual(3)
})

test('keeps a failed item percentage and persisted failure detail visible', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-14T08:00:00Z' })
    }
    if (isLookup(path)) return fulfillJson(route, [])
    if (path.endsWith('/batches/77')) {
      return fulfillJson(route, auditBatch({
        status: 'partial_failed',
        completed: 1,
        failed: 1,
        progress: 84,
      }))
    }
    return fulfillJson(route, [])
  })

  await openAudit(page, '/audit?batch=77')

  await expect(page.getByText('审查失败', { exact: true })).toBeVisible()
  await expect(page.getByText('模型响应超时，请稍后重试', { exact: true })).toBeVisible()
  const failedProgressRow = page.locator('.batch-result-item')
    .filter({ hasText: '失败合同.pdf' })
    .locator('.batch-result-item-progress-row')
  const failedProgress = failedProgressRow.locator('.el-progress')
  await expect(failedProgress).toHaveAttribute('aria-valuenow', '68')
  await expect(failedProgressRow.getByText('68%', { exact: true })).toBeVisible()
})

test('budget exhaustion shows the persisted machine code and does not offer automatic retry', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-11-01T08:00:00Z' })
    }
    if (isLookup(path)) return fulfillJson(route, [])
    if (path.endsWith('/batches/77')) {
      return fulfillJson(route, auditBatch({
        status: 'failed', total: 1, failed: 1, progress: 15,
        items: [{
          ...auditBatch().items[1], progress: 15,
          error_code: 'AUDIT_BUDGET_EXHAUSTED',
          error: '整单审查调用预算已用尽，请人工复核已有结果',
          retryable: false,
          error_action: '人工复核已有结果，或调整预算后创建新任务',
        }],
      }))
    }
    return fulfillJson(route, [])
  })

  await openAudit(page, '/audit?batch=77')
  await expect(page.getByText('错误码：AUDIT_BUDGET_EXHAUSTED', { exact: true })).toBeVisible()
  await expect(page.getByText('整单审查调用预算已用尽，请人工复核已有结果', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '重试失败项', exact: true })).toHaveCount(0)
})

function isLookup(path: string) {
  return path.includes('/admin/lookups/')
}

for (const width of [375, 1280]) {
test(`提交后定位结果，结果紧接审查操作且轮询不抢焦点 ${width}px`, async ({ page }) => {
  const imported = importBatch('ready')
  imported.items = Array.from({ length: 16 }, (_, i) => importItem('ready', { id: i + 1, filename: `反馈测试合同${i + 1}.pdf` }))
  imported.total = imported.ready = 16
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) return fulfillJson(route, { status: 'online' })
    if (path.endsWith('/imports/42')) return fulfillJson(route, imported)
    if (path.includes('/batches')) return fulfillJson(route, auditBatch({ failed: 0, items: [auditBatch().items[0]] }), route.request().method() === 'POST' ? 202 : 200)
    return fulfillJson(route, [])
  })
  await page.setViewportSize({ width, height: 800 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await openAudit(page, '/audit?import=42')
  await page.locator('.action-bar .el-button').click()
  const results = page.getByRole('region', { name: '智能审查结果', exact: true })
  await expect(results).toBeFocused()
  await expect(page.locator('.onboard')).toHaveCount(0)
  expect(await results.evaluate(el => el.previousElementSibling?.querySelector('.contract-inbox') !== null)).toBe(true)
  await expect(results.locator('.batch-result-head')).toBeInViewport()
  await expect(results.locator('.batch-result-item-progress-row')).toBeInViewport()
  await page.getByRole('button', { name: '返回审查设置', exact: true }).click()
  const setup = page.getByRole('region', { name: '审查设置', exact: true })
  await expect(setup).toBeFocused()
  await page.waitForTimeout(1800)
  await expect(setup).toBeFocused()
  expect(await setup.evaluate(el => Math.abs(el.getBoundingClientRect().top) < 160)).toBe(true)
})
}

test('失败批次隐藏上传引导并提供返回设置操作', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) return fulfillJson(route, { status: 'online' })
    if (path.endsWith('/batches/77')) return fulfillJson(route, auditBatch({ status: 'failed', failed: 2 }))
    return fulfillJson(route, [])
  })
  await page.setViewportSize({ width: 375, height: 800 })
  await openAudit(page, '/audit?batch=77')
  await expect(page.locator('.onboard')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '返回审查设置', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

async function uploadContract(page: Page, name = '可靠性测试合同.pdf') {
  await page.locator('input[type="file"]').setInputFiles({
    name,
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 reliability'),
  })
}

test('uses one import idempotency key and restores the inbox from the URL after reload', async ({ page }) => {
  let importKey = ''
  let allowCompletion = false

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T08:00:00Z' })
    }
    if (isLookup(path)) return fulfillJson(route, [])
    if (path.endsWith('/imports') && method === 'POST') {
      importKey = route.request().headers()['idempotency-key'] ?? ''
      return fulfillJson(route, importBatch('parsing'), 202)
    }
    if (path.endsWith('/imports/42') && method === 'GET') {
      return fulfillJson(route, importBatch(allowCompletion ? 'ready' : 'parsing'))
    }
    return fulfillJson(route, [])
  })

  await openAudit(page)
  await uploadContract(page)

  await expect(page).toHaveURL(/\/audit\?import=42$/)
  expect(importKey).toMatch(/^[0-9a-f-]{36}$/)

  allowCompletion = true
  await page.reload()

  await expect(page.getByText('可靠性测试合同.pdf')).toBeVisible()
  await expect(
    page.getByRole('table', { name: '待审合同队列' }).getByText('可以审查', { exact: true }),
  ).toBeVisible()
})

test('reuses the same import operation after an uncertain network response', async ({ page }) => {
  const importKeys: string[] = []
  let attempts = 0

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T08:00:00Z' })
    }
    if (isLookup(path)) return fulfillJson(route, [])
    if (path.endsWith('/imports') && method === 'POST') {
      importKeys.push(route.request().headers()['idempotency-key'] ?? '')
      attempts += 1
      if (attempts === 1) return route.abort('connectionreset')
      return fulfillJson(route, importBatch('ready'), 202)
    }
    return fulfillJson(route, [])
  })

  await openAudit(page)
  await uploadContract(page, '网络重试合同.pdf')
  await expect(page.getByText('网络异常，无法连接到服务器')).toBeVisible()

  await uploadContract(page, '网络重试合同.pdf')
  await expect(page.getByText('已接收 1 份合同')).toBeVisible()

  expect(importKeys).toHaveLength(2)
  expect(importKeys[1]).toBe(importKeys[0])
})

test('shows the persisted import failure instead of a fixed permission message', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T08:00:00Z' })
    }
    if (isLookup(path)) return fulfillJson(route, [])
    if (path.endsWith('/imports') && method === 'POST') {
      return fulfillJson(route, importBatch('failed'), 202)
    }
    return fulfillJson(route, [])
  })

  await openAudit(page)
  await uploadContract(page, '模型超时合同.pdf')

  await expect(page.getByText('模型响应超时，请稍后重试')).toBeVisible()
  await expect(page.getByText('审查失败（需 legal / finance 角色）')).toHaveCount(0)
})

test('leaving the audit page stops browser polling without cancelling backend work', async ({ page }) => {
  let statusCalls = 0
  const cancellationRequests: string[] = []

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T08:00:00Z' })
    }
    if (isLookup(path)) return fulfillJson(route, [])
    if (path.endsWith('/imports') && method === 'POST') {
      return fulfillJson(route, importBatch('parsing'), 202)
    }
    if (path.endsWith('/imports/42') && method === 'GET') {
      statusCalls += 1
      return fulfillJson(route, importBatch('parsing'))
    }
    if (/cancel|abort/.test(path)) cancellationRequests.push(`${method} ${path}`)
    return fulfillJson(route, [])
  })

  await openAudit(page)
  await uploadContract(page, '停止等待合同.pdf')

  await page.goto(`${baseUrl}/dashboard`)
  const callsAfterLeaving = statusCalls
  await page.waitForTimeout(1700)

  expect(statusCalls).toBe(callsAfterLeaving)
  expect(cancellationRequests).toEqual([])
})

test('clears an expired recovery record when the persisted job no longer exists', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('qijian-active-audit', JSON.stringify({
      owner: 'legal',
      contractId: 45,
      filename: '已删除任务合同.pdf',
      idempotencyKey: 'audit:expired-recovery',
      contractType: '采购合同',
      dimensions: ['legal'],
      jobId: 95,
      batchId: 85,
    }))
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T08:00:00Z' })
    }
    if (isLookup(path)) return fulfillJson(route, [])
    if (path.endsWith('/contracts/45/audit-status')) {
      return fulfillJson(route, { detail: '审查任务不存在' }, 404)
    }
    return fulfillJson(route, [])
  })

  await page.goto(`${baseUrl}/audit`)
  await page.waitForLoadState('networkidle')

  await expect(page.getByText('审查任务不存在')).toBeVisible()
  await expect.poll(
    () => page.evaluate(() => localStorage.getItem('qijian-active-audit')),
  ).toBeNull()
})
