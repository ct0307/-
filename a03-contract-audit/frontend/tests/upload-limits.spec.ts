import { expect, test, type Page } from '@playwright/test'
import * as uploadLimits from '../src/config/upload-limits'

test('解析服务端配置，不以默认值替代自定义容量', () => {
  expect(typeof uploadLimits.parseUploadLimits).toBe('function')
  expect(uploadLimits.parseUploadLimits({ max_file_mb: 7, max_batch_files: 9, max_batch_mb: 13 })).toEqual({
    maxFileMb: 7, maxBatchFiles: 9, maxBatchMb: 13,
  })
})

for (const value of [null, [], {}, { max_file_mb: -1, max_batch_files: 200, max_batch_mb: 500 },
  { max_file_mb: 50, max_batch_files: 1.1, max_batch_mb: 500 },
  { max_file_mb: 50, max_batch_files: 200, max_batch_mb: '500' },
  { max_file_mb: Infinity, max_batch_files: 200, max_batch_mb: 500 },
  { max_file_mb: 50, max_batch_files: 200, max_batch_mb: 0 }]) {
  test(`拒绝无效的限制响应 ${JSON.stringify(value)}`, () => {
    expect(() => uploadLimits.parseUploadLimits(value)).toThrow('上传限制响应无效')
  })
}

async function prepare(page: Page, limits: unknown, status = 200, delay = false) {
  let release: (() => void) | undefined
  const pending = new Promise<void>((resolve) => { release = resolve })
  let uploaded = false
  await page.addInitScript(() => {
    localStorage.setItem('token', 'capacity-test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    let responseStatus = 200
    if (path.endsWith('/runtime/status')) body = { status: 'online', checked_at: '2026-10-08T00:00:00Z' }
    if (path.includes('/admin/lookups/department')) body = [{ value: '法务部' }]
    if (path.includes('/admin/lookups/contract_type')) body = [{ value: '采购合同' }]
    if (path.endsWith('/imports/limits')) {
      expect(route.request().headers().authorization).toBe('Bearer capacity-test-token')
      if (delay) await pending
      body = limits
      responseStatus = status
    }
    if (path.endsWith('/imports') && route.request().method() === 'POST') {
      uploaded = true
      body = { id: 42, status: 'ready', total: 0, ready: 0, failed: 0, created_at: '2026-10-08T00:00:00Z', updated_at: '2026-10-08T00:00:00Z', items: [] }
      responseStatus = 202
    }
    await route.fulfill({ status: responseStatus, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/audit')
  return { release: () => release?.(), wasUploaded: () => uploaded }
}

test('空收件箱显示后端自定义限制且手机宽度不溢出', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await prepare(page, { max_file_mb: 7, max_batch_files: 9, max_batch_mb: 13 })
  await expect(page.getByText('收件箱为空')).toBeVisible()
  await expect(page.locator('.upload-secondary')).toContainText('单批最多 9 份、总大小 13 MB，单文件 7 MB')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('读取限制期间显示加载状态', async ({ page }) => {
  const state = await prepare(page, { max_file_mb: 7, max_batch_files: 9, max_batch_mb: 13 }, 200, true)
  await expect(page.locator('.upload-secondary')).toContainText('正在读取上传限制')
  state.release()
  await expect(page.locator('.upload-secondary')).toContainText('单文件 7 MB')
})

for (const [name, value, status] of [
  ['网络失败', { detail: '服务暂不可用' }, 503],
  ['无效数据', { max_file_mb: 0, max_batch_files: 200, max_batch_mb: 500 }, 200],
] as const) {
  test(`${name}后提示无法读取并仍交给服务器校验上传`, async ({ page }) => {
    const state = await prepare(page, value, status)
    await expect(page.locator('.upload-secondary')).toContainText('无法读取上传限制，上传时由服务器校验')
    await expect(page.locator('.upload-secondary')).not.toContainText('50 MB')
    await page.locator('.file-input').setInputFiles({ name: '正常合同.txt', mimeType: 'text/plain', buffer: Buffer.from('正常合同内容') })
    await expect.poll(state.wasUploaded).toBe(true)
  })
}
