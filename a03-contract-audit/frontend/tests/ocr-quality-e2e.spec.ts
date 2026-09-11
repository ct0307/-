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
  basis: parseResult.review_reason,
  suggestion: '请人工复核',
  confidence: 42,
  tier: 'red',
  review_status: 'pending',
  rag_sources: [],
}]

test('renders low-confidence OCR review state without mobile overflow', async ({ page }) => {
  let auditRequestBody: Record<string, unknown> | null = null
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
    } else if (path.endsWith('/contracts/upload')) {
      body = {
        id: 1,
        filename: 'scan.pdf',
        contract_type: '',
        status: 'uploaded',
        created_at: '2026-07-26T10:00:00Z',
        requires_review: false,
        ocr_confidence: null,
        review_reason: null,
      }
    } else if (path.endsWith('/contracts/1/parse')) {
      body = parseResult
    } else if (path.endsWith('/contracts/1/audit')) {
      auditRequestBody = route.request().postDataJSON()
      body = auditResult
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

  await page.goto(`${baseUrl}/login`)
  await page.locator('input[name="username"]').fill('legal')
  await page.locator('input[name="password"]').fill('legal123')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await page.goto(`${baseUrl}/audit`)
  await page.waitForLoadState('networkidle')

  const contractTypeSelect = page.locator('.config-panel .el-select').first()
  await expect(contractTypeSelect.locator('input')).toHaveValue('')

  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'scan.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 mocked scan'),
  })
  await contractTypeSelect.click()
  await page.getByRole('option', { name: '软件开发外包合同' }).click()
  await page.getByRole('button', { name: '启动合规审查' }).click()

  expect(auditRequestBody).toMatchObject({ contract_type: '软件开发外包合同' })

  const reviewAlert = page.getByRole('alert').filter({ hasText: '扫描件需人工复核' })
  await expect(reviewAlert).toContainText('扫描件需人工复核')
  await expect(reviewAlert).toContainText('42.3%')
  await expect(page.getByText('待人工复核', { exact: true })).toBeVisible()
  await expect(page.getByText('扫描件识别质量不足')).toBeVisible()
  await expect(page.getByText('无可靠依据 · 待人工复核')).toBeVisible()

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
  let auditCalls = 0
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith('/auth/login')) {
      body = {
        access_token: 'test-token', token_type: 'bearer', role: 'legal',
        username: 'legal', department: '法务部',
      }
    } else if (path.endsWith('/runtime/status')) {
      body = { status: 'online', checked_at: '2026-07-31T10:00:00Z' }
    } else if (path.endsWith('/contracts/upload')) {
      body = {
        id: 1, filename: '设备采购合同.pdf', contract_type: '', status: 'uploaded',
        created_at: '2026-07-31T10:00:00Z', requires_review: false,
        ocr_confidence: null, review_reason: null,
      }
    } else if (path.endsWith('/contracts/1/parse')) {
      body = { ...parseResult, elements: { contract_name: '设备采购合同' } }
    } else if (path.endsWith('/contracts/1/audit')) {
      auditCalls += 1
      body = { ...auditResult, risk_count: 0 }
    } else if (path.endsWith('/contracts/1/risks')) {
      body = []
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
  const contractTypeSelect = page.locator('.config-panel .el-select').first()
  await contractTypeSelect.click()
  await page.getByRole('option', { name: '软件开发外包合同' }).click()
  await page.getByRole('button', { name: '启动合规审查' }).click()

  await expect(page.getByRole('dialog', { name: '合同类型待确认' })).toBeVisible()
  expect(auditCalls).toBe(0)
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
