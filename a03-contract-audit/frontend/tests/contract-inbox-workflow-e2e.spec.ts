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

async function prepare(page: Page) {
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
        status: 'done',
        total: 2,
        completed: 2,
        failed: 0,
        created_at: '2026-09-11T10:00:00Z',
        updated_at: '2026-09-11T10:00:00Z',
        items: [],
      }, 202)
    }
    return fulfillJson(route, [])
  })
}

test('uploads mixed contracts, confirms one exception and audits ready items', async ({ page }) => {
  await prepare(page)
  await page.goto(`${baseUrl}/audit`)
  await page.waitForLoadState('networkidle')

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
})

test('restores import batch from the url after reload', async ({ page }) => {
  await prepare(page)
  await page.goto(`${baseUrl}/audit?import=42`)
  await expect(page.getByText('采购合同.txt')).toBeVisible()

  await page.reload()

  await expect(page.getByText('采购合同.txt')).toBeVisible()
})
