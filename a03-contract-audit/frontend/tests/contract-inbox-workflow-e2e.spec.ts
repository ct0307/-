import { expect, test, type Page, type Route } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 frontend 后设置 E2E_BASE_URL')

const importItem = (overrides: Record<string, unknown>) => ({
  id: 1,
  contract_id: 11,
  filename: '采购合同.txt',
  status: 'ready',
  error_code: null,
  error_message: null,
  suggested_type: '采购合同',
  confidence: 0.91,
  confirmed_type: '采购合同',
  department: '法务部',
  requires_review: false,
  ...overrides,
})

const mixedBatch = {
  id: 42,
  status: 'needs_attention',
  total: 3,
  ready: 1,
  failed: 1,
  created_at: '2026-09-11T10:00:00Z',
  updated_at: '2026-09-11T10:00:00Z',
  items: [
    importItem({}),
    importItem({
      id: 2,
      contract_id: 12,
      filename: '开发协议.txt',
      status: 'awaiting_confirmation',
      suggested_type: '软件开发外包合同',
      confidence: 0.72,
      confirmed_type: '软件开发外包合同',
    }),
    importItem({
      id: 3,
      contract_id: null,
      filename: '扫描件.txt',
      status: 'failed',
      error_code: 'EMPTY_FILE',
      error_message: '文件为空',
      suggested_type: '',
      confidence: null,
      confirmed_type: '',
      department: '',
    }),
  ],
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

interface PrepareOptions {
  failContract11Result?: boolean
}

async function prepare(page: Page, options: PrepareOptions = {}) {
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
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T10:00:00Z' })
    }
    if (path.includes('/admin/lookups/department')) return fulfillJson(route, [{ value: '法务部' }])
    if (path.includes('/admin/lookups/contract_type')) {
      return fulfillJson(route, [{ value: '采购合同' }, { value: '软件开发外包合同' }])
    }
    if (path.endsWith('/imports') && method === 'POST') return fulfillJson(route, mixedBatch, 202)
    if (path.endsWith('/imports/42') && method === 'GET') return fulfillJson(route, mixedBatch)
    if (path.endsWith('/imports/42/items/2') && method === 'PATCH') {
      return fulfillJson(route, { ...mixedBatch.items[1], status: 'ready' })
    }
    if (path.endsWith('/batches/from-import') && method === 'POST') {
      return fulfillJson(route, {
        id: 88,
        status: 'partial_failed',
        total: 2,
        completed: 2,
        failed: 1,
        created_at: '2026-09-11T10:00:00Z',
        updated_at: '2026-09-11T10:00:00Z',
        items: [
          {
            id: 501,
            contract_id: 11,
            filename: '采购合同.txt',
            status: 'done',
            error: null,
            attempts: 0,
            started_at: null,
            finished_at: '2026-09-11T10:01:00Z',
          },
          {
            id: 502,
            contract_id: 12,
            filename: '开发协议.txt',
            status: 'failed',
            error: '模型服务暂不可用',
            attempts: 1,
            started_at: null,
            finished_at: '2026-09-11T10:01:00Z',
          },
        ],
      }, 202)
    }
    if (path.endsWith('/batches/88/retry') && method === 'POST') {
      return fulfillJson(route, { batch_id: 88, retried: 1, status: 'queued' })
    }
    if (path.endsWith('/batches/88') && method === 'GET') {
      return fulfillJson(route, {
        id: 88,
        status: 'done',
        total: 2,
        completed: 2,
        failed: 0,
        created_at: '2026-09-11T10:00:00Z',
        updated_at: '2026-09-11T10:02:00Z',
        items: [
          { id: 501, contract_id: 11, filename: '采购合同.txt', status: 'done', error: null, attempts: 0, started_at: null, finished_at: null },
          { id: 502, contract_id: 12, filename: '开发协议.txt', status: 'done', error: null, attempts: 2, started_at: null, finished_at: null },
        ],
      })
    }
    if (path.endsWith('/contracts/11/audit-status')) {
      if (options.failContract11Result) {
        return fulfillJson(route, { detail: '审查结果暂时不可用' }, 500)
      }
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
    if (path.endsWith('/contracts/12/audit-status')) {
      return fulfillJson(route, {
        contract_id: 12,
        status: 'done',
        job_id: 502,
        risk_count: 0,
        cross_checks: [],
        requires_review: false,
        ocr_confidence: 0.98,
        review_reason: null,
      })
    }
    if (path.endsWith('/contracts/12/risks')) return fulfillJson(route, [])
    return fulfillJson(route, [])
  })
}

async function submitAndCompleteBatch(page: Page) {
  await page.goto(`${baseUrl}/audit`)
  await expect(page.getByRole('heading', { name: '待审合同' })).toBeVisible()

  await page.locator('input[type="file"]').setInputFiles([
    { name: '采购合同.txt', mimeType: 'text/plain', buffer: Buffer.from('采购服务器设备') },
    { name: '开发协议.txt', mimeType: 'text/plain', buffer: Buffer.from('交付软件源代码') },
    { name: '扫描件.txt', mimeType: 'text/plain', buffer: Buffer.from('') },
  ])
  await expect(page.getByText('可以审查', { exact: true })).toBeVisible()
  await expect(
    page.getByRole('table', { name: '待审合同队列' }).getByText('待确认', { exact: true }),
  ).toBeVisible()
  await page.getByRole('combobox', { name: '开发协议.txt 的合同类型' }).click()
  await page.getByRole('option', { name: '软件开发外包合同' }).click()
  await page.getByRole('button', { name: '确认 开发协议.txt' }).click()
  await page.getByRole('checkbox', { name: '选择采购合同.txt' }).check()
  await page.getByRole('checkbox', { name: '选择开发协议.txt' }).check()
  await page.getByRole('button', { name: '审查就绪项' }).click()

  await expect(page.getByText('已提交 2 份合同')).toBeVisible()
  await expect(page.getByRole('region', { name: '审查批次 88' })).toContainText('部分失败')
  await expect(page.getByRole('region', { name: '审查批次 88' })).toContainText('模型服务暂不可用')

  await page.getByRole('button', { name: '重试失败项' }).click()
  await expect(page.getByRole('region', { name: '审查批次 88' })).toContainText('已完成')
}

test('uploads mixed contracts, confirms one exception and audits ready items', async ({ page }) => {
  await prepare(page)
  await submitAndCompleteBatch(page)

  await page.getByRole('button', { name: '查看 采购合同.txt 的审查结果' }).click()
  await expect(page).toHaveURL(/\/audit/)
  await expect(page.getByText('当前查看')).toBeVisible()
  await expect(page.getByRole('heading', { name: '采购合同.txt' })).toBeVisible()
  await expect(page.getByText('付款条款', { exact: true })).toBeVisible()
  await expect(page.getByText('进入复核', { exact: true })).toBeVisible()
})

test('switches completed contracts and shows a truthful empty result', async ({ page }) => {
  await prepare(page)
  await submitAndCompleteBatch(page)

  await page.getByRole('button', { name: '查看 采购合同.txt 的审查结果' }).click()
  await expect(page.getByText('付款条款', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '查看 开发协议.txt 的审查结果' }).click()

  await expect(page.getByRole('heading', { name: '开发协议.txt' })).toBeVisible()
  await expect(page.getByText('该合同未检出风险')).toBeVisible()
  await expect(page.getByText('付款条款', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '合同关键要素' })).toHaveCount(0)
})

test('keeps the batch summary when loading a completed result fails', async ({ page }) => {
  await prepare(page, { failContract11Result: true })
  await submitAndCompleteBatch(page)

  await page.getByRole('button', { name: '查看 采购合同.txt 的审查结果' }).click()

  await expect(page.locator('.el-message').last()).toContainText('审查结果加载失败')
  await expect(page.getByRole('region', { name: '审查批次 88' })).toBeVisible()
  await expect(page.getByText('当前查看')).toHaveCount(0)
})

test('restores import batch from the url after reload', async ({ page }) => {
  await prepare(page)
  await page.goto(`${baseUrl}/audit?import=42`)
  await expect(page.getByText('采购合同.txt')).toBeVisible()

  await page.reload()

  await expect(page.getByText('采购合同.txt')).toBeVisible()
})

test('keeps both contracts visible when adding files consecutively', async ({ page }) => {
  const keys: string[] = []
  const firstItem = importItem({
    id: 10,
    contract_id: 110,
    filename: '第一份合同.txt',
  })
  const secondItem = importItem({
    id: 11,
    contract_id: 111,
    filename: '第二份合同.txt',
  })
  const firstBatch = {
    ...mixedBatch,
    id: 55,
    status: 'ready',
    total: 1,
    ready: 1,
    failed: 0,
    items: [firstItem],
  }
  const appendedBatch = {
    ...firstBatch,
    total: 2,
    ready: 2,
    items: [firstItem, secondItem],
  }
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
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-12T10:00:00Z' })
    }
    if (path.includes('/admin/lookups/department')) return fulfillJson(route, [{ value: '法务部' }])
    if (path.includes('/admin/lookups/contract_type')) {
      return fulfillJson(route, [{ value: '采购合同' }])
    }
    if (path.endsWith('/imports') && method === 'POST') {
      keys.push(route.request().headers()['idempotency-key'])
      return fulfillJson(route, firstBatch, 202)
    }
    if (path.endsWith('/imports/55/items') && method === 'POST') {
      keys.push(route.request().headers()['idempotency-key'])
      return fulfillJson(route, appendedBatch, 202)
    }
    if (path.endsWith('/imports/55') && method === 'GET') return fulfillJson(route, appendedBatch)
    return fulfillJson(route, [])
  })
  await page.goto(`${baseUrl}/audit`)
  const fileInput = page.locator('input[type="file"]')

  await fileInput.setInputFiles({
    name: '第一份合同.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('first'),
  })
  await expect(page.getByText('第一份合同.txt')).toBeVisible()
  await fileInput.setInputFiles({
    name: '第二份合同.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('second'),
  })

  await expect(page.getByText('第一份合同.txt')).toBeVisible()
  await expect(page.getByText('第二份合同.txt')).toBeVisible()
  await expect(page.getByLabel('导入状态摘要').getByText('2', { exact: true }).first()).toBeVisible()
  await expect(page.locator('.el-message').last()).toContainText('已接收 1 份合同')
  expect(keys).toHaveLength(2)
  expect(keys[0]).not.toBe(keys[1])
})
