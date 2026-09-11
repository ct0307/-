import { expect, test, type Page, type Route } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 frontend 后设置 E2E_BASE_URL')

const item = (overrides: Record<string, unknown>) => ({
  id: 1,
  contract_id: 11,
  filename: '采购合同.pdf',
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

const batch = (items: unknown[]) => ({
  id: 42,
  status: 'needs_attention',
  total: items.length,
  ready: 1,
  failed: 0,
  created_at: '2026-09-11T10:00:00Z',
  updated_at: '2026-09-11T10:00:00Z',
  items,
})

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
}

async function openAudit(page: Page, fixture: unknown) {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('authorized_departments', JSON.stringify(['法务部', '采购中心']))
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T10:00:00Z' })
    }
    if (path.includes('/admin/lookups/department')) {
      return fulfillJson(route, [{ value: '法务部' }, { value: '采购中心' }])
    }
    if (path.includes('/admin/lookups/contract_type')) {
      return fulfillJson(route, [{ value: '采购合同' }, { value: '软件开发外包合同' }])
    }
    if (path.endsWith('/imports/42')) return fulfillJson(route, fixture)
    return fulfillJson(route, [])
  })
  await page.goto(`${baseUrl}/audit?import=42`)
  await page.waitForLoadState('networkidle')
}

test('shows one upload entry and file-level mixed contract types', async ({ page }) => {
  const fixture = batch([
    item({}),
    item({
      id: 2,
      contract_id: 12,
      filename: '软件开发协议.docx',
      suggested_type: '软件开发外包合同',
      confirmed_type: '软件开发外包合同',
      confidence: 0.89,
    }),
  ])

  await page.setViewportSize({ width: 1440, height: 900 })
  await openAudit(page, fixture)

  await expect(page.getByRole('heading', { name: '待审合同' })).toBeVisible()
  await expect(page.getByText('批量上传（支持50份以上）')).toHaveCount(0)
  await expect(page.getByText('采购合同.pdf')).toBeVisible()
  await expect(page.getByText('软件开发协议.docx')).toBeVisible()
  const rows = page.getByRole('table', { name: '待审合同队列' }).getByRole('row')
  await expect(rows.filter({ hasText: '采购合同.pdf' }).getByRole('cell').nth(3)).toContainText('采购合同')
  await expect(rows.filter({ hasText: '软件开发协议.docx' }).getByRole('cell').nth(3)).toContainText('软件开发外包合同')
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
  await page.screenshot({ path: test.info().outputPath('inbox-desktop-1440.png'), fullPage: true })
})

test('uses different actions for upload and parse failures', async ({ page }) => {
  const fixture = batch([
    item({
      id: 3,
      contract_id: null,
      filename: '病毒.exe',
      status: 'failed',
      error_code: 'UNSUPPORTED_FILE_TYPE',
      error_message: '不支持的文件类型',
      suggested_type: '',
      confirmed_type: '',
      confidence: null,
      department: '',
    }),
    item({
      id: 4,
      filename: '扫描件.pdf',
      status: 'failed',
      error_code: 'PARSE_FAILED',
      error_message: '合同解析失败，请重新解析或删除草稿',
    }),
  ])

  await openAudit(page, fixture)

  await expect(page.getByRole('button', { name: '移出 病毒.exe' })).toBeVisible()
  await expect(page.getByRole('button', { name: '重新解析 扫描件.pdf' })).toBeVisible()
  await expect(page.getByRole('button', { name: '删除合同草稿 扫描件.pdf' })).toBeVisible()

  await page.setViewportSize({ width: 768, height: 1024 })
  await page.waitForTimeout(350)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
  await page.screenshot({ path: test.info().outputPath('inbox-tablet-768.png'), fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(350)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
  await page.screenshot({ path: test.info().outputPath('inbox-mobile-390.png'), fullPage: true })
})
