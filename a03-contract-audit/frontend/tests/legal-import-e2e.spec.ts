import { expect, test, type Page } from '@playwright/test'


const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 frontend 后设置 E2E_BASE_URL')

const preview = {
  candidate: true,
  allowed: true,
  source_id: 'civil-code-2020',
  title: '中华人民共和国民法典',
  file_sha256: '90ec77751e4192d640db49dd671fbf00a9528dadcc13dd5294737143d2c1c629',
  hash_matches: true,
  article_count: 1260,
  chunk_count: 1261,
  replace_article_count: 802,
  replace_chunk_count: 803,
  errors: [],
  token: 'preview-token',
}

async function mockKnowledgeApi(page: Page, previewResult: unknown = preview) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith('/auth/login')) {
      body = {
        access_token: 'test-token', token_type: 'bearer', role: 'admin',
        username: 'admin', department: '法务部',
      }
    } else if (path.endsWith('/runtime/status')) {
      body = { status: 'offline', checked_at: '2026-09-09T03:00:00Z' }
    } else if (path.endsWith('/knowledge/cards')) {
      body = { total: 0, page: 1, size: 24, items: [] }
    } else if (path.endsWith('/knowledge/stats')) {
      body = []
    } else if (path.endsWith('/knowledge/legal-import/preview')) {
      body = previewResult
    } else if (path.endsWith('/knowledge/legal-import/apply')) {
      body = {
        source_id: 'civil-code-2020', article_count: 1260, chunk_count: 1261,
        reused_embeddings: 803, rebuilt_embeddings: 458,
        embedding_model: 'test-embedding', embedding_dimension: 512,
        embedding_signature: 'test-signature', first_article_ok: true,
        article_585_ok: true, last_article_ok: true,
      }
    } else if (path.endsWith('/knowledge/import-file')) {
      body = {
        source: 'rules.txt', category: 'rule', detected_category: 'rule',
        auto_detected: true, imported_chunks: 2, skipped_duplicates: 0,
        filtered_placeholders: 0, split_mode: 'paragraph', article_count: 0,
        overlap_warning: null,
      }
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

async function openImportDialog(page: Page) {
  await page.goto(`${baseUrl}/login`)
  await page.locator('input[name="username"]').fill('admin')
  await page.locator('input[name="password"]').fill('admin123')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await page.goto(`${baseUrl}/knowledge`)
  await page.getByRole('button', { name: '导入文件' }).click()
  return page.getByRole('dialog', { name: '批量导入文件' })
}

test('previews and applies the verified civil code without mobile clipping', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  await mockKnowledgeApi(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  const dialog = await openImportDialog(page)
  await dialog.locator('input[type="file"]').setInputFiles({
    name: 'civil-code.txt', mimeType: 'text/plain', buffer: Buffer.from('official fixture'),
  })

  await expect(dialog.getByText('校验通过', { exact: true })).toBeVisible()
  await expect(dialog).toContainText('1260 条父法条')
  await expect(dialog).toContainText('与官方基准一致')
  await expect(dialog.getByRole('button', { name: '应用权威法源' })).toBeEnabled()

  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(async () => dialog.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    return Math.max(0, rect.right - window.innerWidth)
  })).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0)

  await dialog.getByRole('button', { name: '应用权威法源' }).click()
  await page.getByRole('dialog', { name: '确认替换权威法源' })
    .getByRole('button', { name: '确认替换' }).click()
  await expect(dialog).toContainText('第 1、585、1260 条均已核验')
  await expect(dialog).toContainText('复用 803 个向量')
  expect(consoleErrors).toEqual([])
})

test('blocks a civil code candidate whose hash does not match', async ({ page }) => {
  await mockKnowledgeApi(page, {
    ...preview, allowed: false, hash_matches: false, token: null,
    errors: ['文件哈希与官方基准不一致'],
  })
  const dialog = await openImportDialog(page)
  await dialog.locator('input[type="file"]').setInputFiles({
    name: 'civil-code.txt', mimeType: 'text/plain', buffer: Buffer.from('modified fixture'),
  })

  await expect(dialog).toContainText('禁止导入')
  await expect(dialog).toContainText('文件哈希与官方基准不一致')
  await expect(dialog.getByRole('button', { name: '应用权威法源' })).toBeDisabled()
})

test('keeps ordinary files on the existing generic import endpoint', async ({ page }) => {
  let genericImportCalls = 0
  await mockKnowledgeApi(page, {
    candidate: false, allowed: false, source_id: null, title: null,
    file_sha256: 'generic', hash_matches: false, article_count: 0, chunk_count: 0,
    replace_article_count: 0, replace_chunk_count: 0, errors: [], token: null,
  })
  page.on('request', (request) => {
    if (request.url().endsWith('/knowledge/import-file')) genericImportCalls += 1
  })
  const dialog = await openImportDialog(page)
  await dialog.locator('input[type="file"]').setInputFiles({
    name: 'rules.txt', mimeType: 'text/plain', buffer: Buffer.from('ordinary rules'),
  })
  await dialog.getByRole('button', { name: '开始导入' }).click()

  await expect(dialog).toContainText('入库 2 个切片')
  expect(genericImportCalls).toBe(1)
})
