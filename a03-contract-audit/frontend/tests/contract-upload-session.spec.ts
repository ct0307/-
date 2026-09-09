import { expect, test, type Page, type Route } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 frontend 后设置 E2E_BASE_URL')

const parseResult = (contractId: number, party: string) => ({
  contract_id: contractId,
  elements: { party_a: party },
  text_length: 320,
  requires_review: false,
  ocr_confidence: null,
  review_reason: null,
})

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function openAudit(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
  })
  await page.goto(`${baseUrl}/audit`)
  await page.waitForLoadState('networkidle')
}

test('keeps upload records, retries the same contract and rolls back failed switching', async ({ page }) => {
  let uploadCalls = 0
  const parseCalls = new Map<number, number>()

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-09T08:00:00Z' })
    }
    if (path.includes('/admin/lookups/')) return fulfillJson(route, [])
    if (path.endsWith('/contracts/upload')) {
      uploadCalls += 1
      return fulfillJson(route, {
        id: uploadCalls,
        filename: uploadCalls === 1 ? '离职保密协议.pdf' : '小时工附加协议.pdf',
        contract_type: '',
        status: 'uploaded',
        created_at: '2026-09-09T08:00:00Z',
      })
    }
    const parseMatch = path.match(/\/contracts\/(\d+)\/parse$/)
    if (parseMatch) {
      const id = Number(parseMatch[1])
      const count = (parseCalls.get(id) ?? 0) + 1
      parseCalls.set(id, count)
      if (id === 1 && (count === 1 || count === 3)) {
        return fulfillJson(route, {
          detail: {
            code: 'PDF_TEXT_ENCODING_ERROR',
            detail: 'PDF 文本编码异常，请重新导出 PDF 后重试',
          },
        }, 422)
      }
      return fulfillJson(route, parseResult(id, id === 1 ? '甲公司' : '乙公司'))
    }
    return fulfillJson(route, [])
  })

  await openAudit(page)
  await expect(page.getByText('尚无上传记录')).toBeVisible()

  const fileInput = page.locator('input[type="file"]').first()
  await fileInput.setInputFiles({
    name: '离职保密协议.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 first'),
  })

  await expect(page.getByText('上传成功，解析失败')).toBeVisible()
  await expect(
    page.getByLabel('本次上传记录').getByText('PDF 文本编码异常，请重新导出 PDF 后重试'),
  ).toBeVisible()
  expect(uploadCalls).toBe(1)

  await page.getByRole('button', { name: '重新解析 离职保密协议.pdf' }).click()
  await expect(
    page.getByLabel('本次上传记录').getByText('解析完成', { exact: true }),
  ).toBeVisible()
  await expect(page.locator('.filename-text')).toContainText('离职保密协议.pdf（合同 #1）')
  expect(uploadCalls).toBe(1)

  await fileInput.setInputFiles({
    name: '小时工附加协议.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 second'),
  })
  await expect(page.getByText('离职保密协议.pdf', { exact: true })).toBeVisible()
  await expect(page.getByText('小时工附加协议.pdf', { exact: true })).toBeVisible()
  await expect(page.locator('.filename-text')).toContainText('小时工附加协议.pdf（合同 #2）')

  await page.getByRole('button', { name: '切换到 离职保密协议.pdf' }).click()
  await expect(
    page.getByLabel('本次上传记录').getByText('PDF 文本编码异常，请重新导出 PDF 后重试'),
  ).toBeVisible()
  await expect(page.locator('.filename-text')).toContainText('小时工附加协议.pdf（合同 #2）')

  await page.getByRole('button', { name: '重新解析 离职保密协议.pdf' }).click()
  await expect(page.locator('.filename-text')).toContainText('离职保密协议.pdf（合同 #1）')
  expect(uploadCalls).toBe(2)

  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(200)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
})

test('persists upload failure and clears records on logout', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-09T08:00:00Z' })
    }
    if (path.includes('/admin/lookups/')) return fulfillJson(route, [])
    if (path.endsWith('/contracts/upload')) {
      return fulfillJson(route, { detail: '文件超过大小限制' }, 413)
    }
    return fulfillJson(route, [])
  })

  await openAudit(page)
  await page.locator('input[type="file"]').first().setInputFiles({
    name: '劳务合同.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 failed'),
  })
  await expect(page.getByText('上传失败', { exact: true })).toBeVisible()
  await expect(page.getByLabel('本次上传记录').getByText('文件超过大小限制')).toBeVisible()

  await page.getByRole('button', { name: /切换演示视角或退出登录|用户菜单/ }).click()
  await page.getByRole('menuitem', { name: '退出登录' }).click()
  await expect(page).toHaveURL(/\/login$/)

  await page.evaluate(() => {
    localStorage.setItem('token', 'new-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal-2')
    localStorage.setItem('department', '法务部')
  })
  await page.goto(`${baseUrl}/audit`)
  await expect(page.getByText('尚无上传记录')).toBeVisible()
  await expect(page.getByText('劳务合同.pdf', { exact: true })).toHaveCount(0)
})

test('shows uploading and parsing states while disabling the upload input', async ({ page }) => {
  let releaseUpload: (() => void) | undefined
  let releaseParse: (() => void) | undefined
  const uploadGate = new Promise<void>((resolve) => { releaseUpload = resolve })
  const parseGate = new Promise<void>((resolve) => { releaseParse = resolve })

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-09T08:00:00Z' })
    }
    if (path.includes('/admin/lookups/')) return fulfillJson(route, [])
    if (path.endsWith('/contracts/upload')) {
      await uploadGate
      return fulfillJson(route, {
        id: 7,
        filename: '处理中合同.pdf',
        contract_type: '',
        status: 'uploaded',
        created_at: '2026-09-09T08:00:00Z',
      })
    }
    if (path.endsWith('/contracts/7/parse')) {
      await parseGate
      return fulfillJson(route, parseResult(7, '测试公司'))
    }
    return fulfillJson(route, [])
  })

  await openAudit(page)
  const input = page.locator('input[type="file"]').first()
  const uploadRequest = page.waitForRequest((request) => request.url().endsWith('/contracts/upload'))
  await input.setInputFiles({
    name: '处理中合同.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 pending'),
  })
  await uploadRequest
  await expect(page.getByText('上传中', { exact: true })).toBeVisible()
  await expect(input).toBeDisabled()

  const parseRequest = page.waitForRequest((request) => request.url().endsWith('/contracts/7/parse'))
  releaseUpload?.()
  await parseRequest
  await expect(page.getByText('解析中', { exact: true })).toBeVisible()
  await expect(input).toBeDisabled()

  releaseParse?.()
  await expect(page.getByLabel('本次上传记录').getByText('解析完成', { exact: true })).toBeVisible()
  await expect(input).toBeEnabled()
})
