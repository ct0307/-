import { expect, test, type Page, type Route } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
  ?? `http://127.0.0.1:${process.env.E2E_PORT ?? '41739'}`

type ItemStatus = 'reviewing' | 'validating' | 'review_required' | 'failed'

const filename = '超长文件名用于验证移动端状态与查看按钮不会重叠的合同.pdf'
const unexpectedRequestsByPage = new WeakMap<Page, string[]>()

test.afterEach(async ({ page }) => {
  expect(unexpectedRequestsByPage.get(page) ?? [], '存在未声明的 API 请求').toEqual([])
})

function importBatch() {
  return {
    id: 42,
    status: 'ready',
    total: 1,
    ready: 1,
    failed: 0,
    created_at: '2026-09-13T10:00:00Z',
    updated_at: '2026-09-13T10:00:00Z',
    items: [{
      id: 7,
      contract_id: 77,
      filename,
      status: 'ready',
      error_code: null,
      error_message: null,
      suggested_type: '采购合同',
      confidence: 0.96,
      confirmed_type: '采购合同',
      department: '法务部',
      requires_review: false,
    }],
  }
}

function auditBatch(itemStatus: ItemStatus) {
  const batchStatus = itemStatus === 'review_required'
    ? 'review_required'
    : itemStatus === 'failed'
      ? 'failed'
      : 'running'
  return {
    id: 88,
    status: batchStatus,
    total: 1,
    completed: ['review_required', 'failed'].includes(itemStatus) ? 1 : 0,
    failed: itemStatus === 'failed' ? 1 : 0,
    created_at: '2026-09-13T10:01:00Z',
    updated_at: '2026-09-13T10:01:00Z',
    items: [{
      id: 501,
      contract_id: 77,
      filename,
      status: itemStatus,
      error: itemStatus === 'failed' ? '模型服务暂不可用' : null,
      error_code: itemStatus === 'failed' ? 'MODEL_UNAVAILABLE' : null,
      attempts: 1,
      started_at: '2026-09-13T10:01:00Z',
      finished_at: ['review_required', 'failed'].includes(itemStatus)
        ? '2026-09-13T10:02:00Z'
        : null,
      requires_review: itemStatus === 'review_required',
      ocr_confidence: 0.98,
      review_reason: itemStatus === 'review_required'
        ? '二次复核发现证据支持关系存在冲突'
        : null,
    }],
  }
}

function restoredBatch(id: number, restoredFilename: string) {
  const source = auditBatch('review_required')
  return {
    ...source,
    id,
    items: source.items.map((item) => ({
      ...item,
      id: id * 10 + 1,
      filename: restoredFilename,
    })),
  }
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

interface PrepareOptions {
  requestedStatusJobs?: Array<string | null>
  requestedRiskJobs?: Array<string | null>
}

async function prepare(page: Page, itemStatus: ItemStatus, options: PrepareOptions = {}) {
  const batch = auditBatch(itemStatus)
  const unexpectedRequests: string[] = []
  unexpectedRequestsByPage.set(page, unexpectedRequests)
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('authorized_departments', JSON.stringify(['法务部']))
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-13T10:00:00Z' })
    }
    if (path.includes('/admin/lookups/')) return fulfillJson(route, [])
    if (path.endsWith('/imports/42') && method === 'GET') return fulfillJson(route, importBatch())
    if (path.endsWith('/batches/from-import') && method === 'POST') {
      return fulfillJson(route, batch, 202)
    }
    if (path.endsWith('/batches/88') && method === 'GET') return fulfillJson(route, batch)
    if (path.endsWith('/contracts/77/audit-status') && method === 'GET') {
      const requestedJob = new URL(route.request().url()).searchParams.get('job_id')
      options.requestedStatusJobs?.push(requestedJob)
      return fulfillJson(route, {
        contract_id: 77,
        status: 'review_required',
        job_id: requestedJob ? Number(requestedJob) : 999,
        risk_count: 1,
        cross_checks: [],
        requires_review: true,
        review_reason: '旧代次需要人工复核',
      })
    }
    if (path.endsWith('/contracts/77/risks') && method === 'GET') {
      const requestedJob = new URL(route.request().url()).searchParams.get('job_id')
      options.requestedRiskJobs?.push(requestedJob)
      return fulfillJson(route, [{
        id: requestedJob === '501' ? 701 : 799,
        agent: 'legal',
        level: 'high',
        category: requestedJob === '501' ? '旧代次风险' : '最新代次风险',
        original_text: '验收后付款',
        risk_reason: '付款期限不明确',
        basis: '合同约定',
        suggestion: '补充明确期限',
        confidence: 91,
        tier: 'red',
        review_status: 'pending',
        rag_sources: [],
        evidence_status: 'supported',
        original_text_verified: true,
        requires_manual_review: true,
        support_relation_status: 'supported',
        support_validation_reason: '',
        support_validator_version: 'test-v1',
        secondary_review_status: 'manual_required',
        secondary_review_reason: '旧代次需要人工复核',
      }])
    }
    unexpectedRequests.push(`${method} ${route.request().url()}`)
    return route.abort('failed')
  })

  await page.goto(`${baseUrl}/audit?import=42`)
  await page.getByRole('checkbox', { name: `选择${filename}` }).check()
  await page.getByRole('button', { name: '审查就绪项' }).click()
  await expect(page).toHaveURL(/\bbatch=88\b/)
  const region = page.getByRole('region', { name: '审查批次 88' })
  await expect(region).toBeVisible()
  return region
}

async function switchBatchQuery(page: Page, batchId: number | null) {
  await page.evaluate(async (nextBatchId) => {
    const root = document.querySelector('#app') as (Element & {
      __vue_app__?: {
        config: {
          globalProperties: {
            $router?: {
              push(location: { path: string; query: Record<string, string> }): Promise<void>
            }
          }
        }
      }
    }) | null
    const router = root?.__vue_app__?.config.globalProperties.$router
    if (!router) throw new Error('Vue Router 未挂载')
    const query = Object.fromEntries(new URLSearchParams(window.location.search))
    if (nextBatchId === null) delete query.batch
    else query.batch = String(nextBatchId)
    await router.push({ path: window.location.pathname, query })
  }, batchId)
}

for (const scenario of [
  { status: 'reviewing', label: '审查中' },
  { status: 'validating', label: '结果校验中' },
  { status: 'review_required', label: '需人工复核' },
  { status: 'failed', label: '失败' },
] as const) {
  test(`shows ${scenario.status} as ${scenario.label}`, async ({ page }) => {
    const region = await prepare(page, scenario.status)

    await expect(region.getByText(scenario.label, { exact: true }).last()).toBeVisible()
  })
}

test('review_required exposes the reason and partial result without retry', async ({ page }) => {
  const region = await prepare(page, 'review_required')

  await expect(region.getByText('二次复核发现证据支持关系存在冲突')).toBeVisible()
  await expect(region.getByRole('button', { name: `查看 ${filename} 的审查结果` })).toBeVisible()
  await expect(region.getByRole('button', { name: '重试失败项' })).toHaveCount(0)
})

test('failed is the only quality state that offers batch retry', async ({ page }) => {
  const region = await prepare(page, 'failed')

  await expect(region.getByText('模型服务暂不可用')).toBeVisible()
  await expect(region.getByRole('button', { name: '重试失败项' })).toBeVisible()
})

test('restores an active quality-state batch from the url after reload', async ({ page }) => {
  await prepare(page, 'validating')
  await expect(page).toHaveURL(/\bimport=42\b/)
  await expect(page).toHaveURL(/\bbatch=88\b/)

  await page.reload()

  const region = page.getByRole('region', { name: '审查批次 88' })
  await expect(region.getByText('结果校验中', { exact: true })).toBeVisible()
})

test('opens the selected historical batch generation instead of the latest contract result', async ({ page }) => {
  const requestedStatusJobs: Array<string | null> = []
  const requestedRiskJobs: Array<string | null> = []
  const region = await prepare(page, 'review_required', {
    requestedStatusJobs,
    requestedRiskJobs,
  })

  await region.getByRole('button', { name: `查看 ${filename} 的审查结果` }).click()

  await expect.poll(() => requestedStatusJobs).toEqual(['501'])
  await expect.poll(() => requestedRiskJobs).toEqual(['501'])
  await expect(page.getByText('旧代次风险', { exact: true })).toBeVisible()
  await expect(page.getByText('最新代次风险', { exact: true })).toHaveCount(0)
})

test('hides the previous batch immediately when the route target fails', async ({ page }) => {
  const previous = await prepare(page, 'review_required')
  let failedTargetCalls = 0
  await page.route('**/api/v1/batches/99', async (route) => {
    failedTargetCalls += 1
    await new Promise((resolve) => setTimeout(resolve, 150))
    return fulfillJson(route, { detail: '目标批次不存在' }, 404)
  })

  await switchBatchQuery(page, 99)

  await expect(previous).toHaveCount(0)
  await expect.poll(() => failedTargetCalls).toBe(1)
  await expect(page.getByRole('region', { name: '审查批次 99' })).toHaveCount(0)
})

test('reacts to batch query changes and clears the batch when the query is removed', async ({ page }) => {
  await prepare(page, 'review_required')
  const next = restoredBatch(99, '路由切换后的批次.pdf')
  await page.route('**/api/v1/batches/99', (route) => fulfillJson(route, next))

  await switchBatchQuery(page, 99)

  await expect(page.getByRole('region', { name: '审查批次 99' })).toContainText('路由切换后的批次.pdf')
  await expect(page.getByRole('region', { name: '审查批次 88' })).toHaveCount(0)

  await switchBatchQuery(page, null)
  await expect(page.getByRole('region', { name: '审查批次 99' })).toHaveCount(0)
})

test('keeps only the newest batch when an older route request finishes late', async ({ page }) => {
  await prepare(page, 'review_required')
  let slowRequestStarted = false
  await page.route('**/api/v1/batches/*', async (route) => {
    const id = Number(new URL(route.request().url()).pathname.split('/').at(-1))
    if (id === 90) {
      slowRequestStarted = true
      await new Promise((resolve) => setTimeout(resolve, 300))
      return fulfillJson(route, restoredBatch(90, '迟到的批次A.pdf'))
    }
    if (id === 99) return fulfillJson(route, restoredBatch(99, '最新目标批次B.pdf'))
    return route.fallback()
  })

  await switchBatchQuery(page, 90)
  await expect.poll(() => slowRequestStarted).toBe(true)
  await switchBatchQuery(page, 99)

  await expect(page.getByRole('region', { name: '审查批次 99' })).toContainText('最新目标批次B.pdf')
  await page.waitForTimeout(400)
  await expect(page.getByRole('region', { name: '审查批次 99' })).toContainText('最新目标批次B.pdf')
  await expect(page.getByRole('region', { name: '审查批次 90' })).toHaveCount(0)
})
