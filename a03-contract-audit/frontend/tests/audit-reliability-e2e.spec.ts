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

async function openAudit(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('authorized_departments', JSON.stringify(['法务部']))
  })
  await page.goto(`${baseUrl}/audit`)
  await page.waitForLoadState('networkidle')
}

function isLookup(path: string) {
  return path.includes('/admin/lookups/')
}

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
