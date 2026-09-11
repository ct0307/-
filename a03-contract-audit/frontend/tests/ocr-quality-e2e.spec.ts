import { expect, test } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 frontend 后设置 E2E_BASE_URL')

const parseResult = {
  contract_id: 1,
  elements: {},
  text_length: 480,
  requires_review: true,
  ocr_confidence: 0.423,
  review_reason: 'OCR 平均置信度低于 75%',
}

const auditResult = {
  contract_id: 1,
  status: 'review_required',
  risk_count: 1,
  cross_checks: [],
  ...parseResult,
}

const risks = [{
  id: 1,
  agent: 'system',
  level: 'high',
  category: '扫描件识别质量不足',
  original_text: 'OCR 平均置信度：42.3%',
  risk_reason: 'OCR 质量未达到自动采信门槛。',
  basis: parseResult.review_reason,
  suggestion: '请人工复核',
  confidence: 42,
  tier: 'red',
  review_status: 'pending',
  rag_sources: [],
  evidence_status: 'unsupported',
  original_text_verified: false,
  requires_manual_review: true,
}]

test('renders low-confidence OCR review state without mobile overflow', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('authorized_departments', JSON.stringify(['法务部']))
    localStorage.setItem('qijian-active-audit', JSON.stringify({
      owner: 'legal',
      contractId: 1,
      filename: 'scan.pdf',
      idempotencyKey: 'audit:ocr-recovery',
      contractType: '软件开发外包合同',
      dimensions: ['legal'],
      jobId: 9,
      batchId: 8,
    }))
  })
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    let body: unknown

    if (path.endsWith('/auth/login')) {
      body = {
        access_token: 'test-token',
        token_type: 'bearer',
        role: 'legal',
        username: 'legal',
        department: '法务部',
      }
    } else if (path.endsWith('/runtime/status')) {
      body = {
        status: 'online',
        checked_at: '2026-07-26T10:00:00Z',
        provider: 'qwen',
        model: 'qwen2.5:14b',
        endpoint: null,
        detail: null,
      }
    } else if (path.includes('/admin/lookups/')) {
      body = []
    } else if (path.endsWith('/contracts/1/audit-status')) {
      body = { ...auditResult, job_id: 9, batch_id: 8 }
    } else if (path.endsWith('/contracts/1/risks')) {
      body = risks
    } else {
      body = []
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
  })

  await page.goto(`${baseUrl}/audit`)
  await page.waitForLoadState('networkidle')

  const reviewAlert = page.getByRole('alert').filter({ hasText: '扫描件需人工复核' })
  await expect(reviewAlert).toContainText('扫描件需人工复核')
  await expect(reviewAlert).toContainText('42.3%')
  await expect(page.getByText('待人工复核', { exact: true })).toBeVisible()
  await expect(page.getByText('扫描件识别质量不足')).toBeVisible()
  await expect(page.getByText('证据不足 · 待复核')).toBeVisible()

  await page.getByText('扫描件识别质量不足').click()
  await expect(page.getByRole('alert').filter({ hasText: '无可靠依据' })).toContainText(
    '不能直接作为正式审查依据',
  )

  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(350)
  const closedSidebarRight = await page.locator('#app-sidebar').evaluate(
    (element) => element.getBoundingClientRect().right,
  )
  expect(closedSidebarRight).toBeLessThanOrEqual(0)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  await page.screenshot({
    path: test.info().outputPath('ocr-review-mobile.png'),
    fullPage: true,
  })
})

test('requires confirmation when selected type conflicts with the material', async ({ page }) => {
  let confirmRequestBody: Record<string, unknown> | null = null
  let batchCalls = 0
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    let body: unknown = []
    if (path.endsWith('/auth/login')) {
      body = {
        access_token: 'test-token', token_type: 'bearer', role: 'legal',
        username: 'legal', department: '法务部',
      }
    } else if (path.endsWith('/runtime/status')) {
      body = { status: 'online', checked_at: '2026-07-31T10:00:00Z' }
    } else if (path.includes('/admin/lookups/contract_type')) {
      body = [{ value: '采购合同' }, { value: '软件开发外包合同' }]
    } else if (path.includes('/admin/lookups/department')) {
      body = [{ value: '法务部' }]
    } else if (path.endsWith('/imports') && method === 'POST') {
      body = {
        id: 12,
        status: 'needs_attention',
        total: 1,
        ready: 0,
        failed: 0,
        created_at: '2026-07-31T10:00:00Z',
        updated_at: '2026-07-31T10:00:00Z',
        items: [{
          id: 1,
          contract_id: 1,
          filename: '设备采购合同.pdf',
          status: 'awaiting_confirmation',
          error_code: null,
          error_message: null,
          suggested_type: '采购合同',
          confidence: 0.68,
          confirmed_type: '采购合同',
          department: '法务部',
          requires_review: false,
        }],
      }
    } else if (path.endsWith('/imports/12/items/1') && method === 'PATCH') {
      confirmRequestBody = route.request().postDataJSON()
      body = {
        id: 1,
        contract_id: 1,
        filename: '设备采购合同.pdf',
        status: 'ready',
        error_code: null,
        error_message: null,
        suggested_type: '采购合同',
        confidence: 0.68,
        confirmed_type: '软件开发外包合同',
        department: '法务部',
        requires_review: false,
      }
    } else if (path.endsWith('/batches/from-import')) {
      batchCalls += 1
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto(`${baseUrl}/login`)
  await page.locator('input[name="username"]').fill('legal')
  await page.locator('input[name="password"]').fill('legal123')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await page.goto(`${baseUrl}/audit`)
  await page.locator('input[type="file"]').first().setInputFiles({
    name: '设备采购合同.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 mocked purchase contract'),
  })
  const contractTypeSelect = page.getByRole('combobox', { name: '设备采购合同.pdf 的合同类型' })
  await contractTypeSelect.click()
  await page.getByRole('option', { name: '软件开发外包合同' }).click()
  await expect(page.getByRole('checkbox', { name: '选择设备采购合同.pdf' })).toBeDisabled()
  expect(batchCalls).toBe(0)

  await page.getByRole('button', { name: '确认 设备采购合同.pdf' }).click()

  expect(confirmRequestBody).toEqual({
    contract_type: '软件开发外包合同',
    department: '法务部',
  })
  await expect(page.getByRole('checkbox', { name: '选择设备采购合同.pdf' })).toBeEnabled()
})

test('filters review-required contracts in history without mobile overflow', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []

    if (path.endsWith('/auth/login')) {
      body = {
        access_token: 'test-token',
        token_type: 'bearer',
        role: 'legal',
        username: 'legal',
        department: '法务部',
      }
    } else if (path.endsWith('/runtime/status')) {
      body = {
        status: 'online',
        checked_at: '2026-07-26T10:00:00Z',
        provider: 'qwen',
        model: 'qwen2.5:14b',
        endpoint: null,
        detail: null,
      }
    } else if (path.endsWith('/contracts')) {
      body = [
        {
          id: 'C0001', name: '低置信度扫描合同', type: '采购合同',
          submitter: '测试用户', time: '2026-07-26 10:00', level: '高风险',
          riskCount: 1, status: '待人工复核',
        },
        {
          id: 'C0002', name: '正常文本合同', type: '采购合同',
          submitter: '测试用户', time: '2026-07-26 09:00', level: '低风险',
          riskCount: 0, status: '合规',
        },
      ]
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
  })

  await page.goto(`${baseUrl}/login`)
  await page.locator('input[name="username"]').fill('legal')
  await page.locator('input[name="password"]').fill('legal123')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await page.goto(`${baseUrl}/history`)
  await expect(page.getByText('低置信度扫描合同')).toBeVisible()
  await expect(page.getByText('正常文本合同')).toBeVisible()

  await page.locator('.filters .el-select').nth(1).click()
  await page.getByRole('option', { name: '待人工复核' }).click()

  await expect(page.getByText('低置信度扫描合同')).toBeVisible()
  await expect(page.getByText('正常文本合同')).toBeHidden()

  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(350)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  await page.screenshot({
    path: test.info().outputPath('history-review-mobile.png'),
    fullPage: true,
  })
})
