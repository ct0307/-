import { expect, test, type Page, type Route } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 frontend 后设置 E2E_BASE_URL')

const readyItem = {
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
}

function importBatch(items: unknown[]) {
  return {
    id: 42,
    status: items.some((item) => (item as { status: string }).status === 'failed')
      ? 'needs_attention'
      : 'ready',
    total: items.length,
    ready: items.filter((item) => (item as { status: string }).status === 'ready').length,
    failed: items.filter((item) => (item as { status: string }).status === 'failed').length,
    created_at: '2026-09-11T10:00:00Z',
    updated_at: '2026-09-11T10:00:00Z',
    items,
  }
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function prepare(page: Page, routeApi: (route: Route) => Promise<void>) {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('authorized_departments', JSON.stringify(['法务部']))
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T10:00:00Z' })
    }
    if (path.includes('/admin/lookups/department')) return fulfillJson(route, [{ value: '法务部' }])
    if (path.includes('/admin/lookups/contract_type')) return fulfillJson(route, [{ value: '采购合同' }])
    await routeApi(route)
  })
  await page.goto(`${baseUrl}/audit`)
  await page.waitForLoadState('networkidle')
}

test('uses one import endpoint for both single and multiple files', async ({ page }) => {
  let importCalls = 0
  let legacyUploadCalls = 0
  await prepare(page, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/imports') && route.request().method() === 'POST') {
      importCalls += 1
      return fulfillJson(route, importBatch([readyItem]), 202)
    }
    if (path.endsWith('/contracts/upload') || path.endsWith('/batches')) legacyUploadCalls += 1
    return fulfillJson(route, [])
  })

  await page.locator('input[type="file"]').setInputFiles({
    name: '采购合同.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('采购设备'),
  })

  await expect(page).toHaveURL(/\?import=42$/)
  expect(importCalls).toBe(1)
  expect(legacyUploadCalls).toBe(0)
})

test('removes an upload failure without deleting a contract draft', async ({ page }) => {
  let removeCalls = 0
  const failed = {
    ...readyItem,
    id: 2,
    contract_id: null,
    filename: '病毒.exe',
    status: 'failed',
    error_code: 'UNSUPPORTED_FILE_TYPE',
    error_message: '不支持的文件类型',
    suggested_type: '',
    confidence: null,
    confirmed_type: '',
    department: '',
  }
  await prepare(page, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/imports') && route.request().method() === 'POST') {
      return fulfillJson(route, importBatch([failed]), 202)
    }
    if (path.endsWith('/imports/42/items/2/record') && route.request().method() === 'DELETE') {
      removeCalls += 1
      return route.fulfill({ status: 204, body: '' })
    }
    return fulfillJson(route, [])
  })
  await page.locator('input[type="file"]').setInputFiles({
    name: '病毒.exe',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('bad'),
  })

  await page.getByRole('button', { name: '移出 病毒.exe' }).click()

  expect(removeCalls).toBe(1)
  await expect(page.getByText('病毒.exe')).toHaveCount(0)
})

test('disables file selection while the import request is pending', async ({ page }) => {
  let release: (() => void) | undefined
  const gate = new Promise<void>((resolve) => { release = resolve })
  await prepare(page, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/imports') && route.request().method() === 'POST') {
      await gate
      return fulfillJson(route, importBatch([readyItem]), 202)
    }
    return fulfillJson(route, [])
  })
  const input = page.locator('input[type="file"]')
  const request = page.waitForRequest((value) => value.url().endsWith('/api/v1/imports'))

  await input.setInputFiles({
    name: '采购合同.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('采购设备'),
  })
  await request
  await expect(input).toBeDisabled()

  release?.()
  await expect(input).toBeEnabled()
})
