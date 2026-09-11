import { expect, test, type Page, type Route } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 frontend 后设置 E2E_BASE_URL')

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

async function uploadAndSelectType(page: Page) {
  await page.locator('input[type="file"]').first().setInputFiles({
    name: '可靠性测试合同.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 reliability'),
  })
  const contractTypeSelect = page.locator('.config-panel .el-select').first()
  await contractTypeSelect.click()
  await page.getByRole('option', { name: '软件开发外包合同' }).click()
}

test('uses idempotency keys and restores a running audit after reload', async ({ page }) => {
  let uploadKey = ''
  let auditKey = ''
  let allowCompletion = false

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T08:00:00Z' })
    }
    if (path.includes('/admin/lookups/')) return fulfillJson(route, [])
    if (path.endsWith('/contracts/upload')) {
      uploadKey = route.request().headers()['idempotency-key'] ?? ''
      return fulfillJson(route, {
        id: 41,
        filename: '可靠性测试合同.pdf',
        contract_type: '',
        status: 'uploaded',
        created_at: '2026-09-11T08:00:00Z',
      })
    }
    if (path.endsWith('/contracts/41/parse')) {
      return fulfillJson(route, {
        contract_id: 41,
        elements: { contract_name: '软件开发外包合同' },
        text_length: 500,
      })
    }
    if (path.endsWith('/contracts/41/audit')) {
      auditKey = route.request().headers()['idempotency-key'] ?? ''
      return fulfillJson(route, {
        contract_id: 41,
        status: 'auditing',
        job_id: 91,
        batch_id: 81,
      })
    }
    if (path.endsWith('/contracts/41/audit-status')) {
      expect(new URL(route.request().url()).searchParams.get('job_id')).toBe('91')
      return fulfillJson(route, allowCompletion
        ? { contract_id: 41, status: 'done', job_id: 91, batch_id: 81, risk_count: 0 }
        : { contract_id: 41, status: 'auditing', job_id: 91, batch_id: 81 })
    }
    if (path.endsWith('/contracts/41/risks')) return fulfillJson(route, [])
    return fulfillJson(route, [])
  })

  await openAudit(page)
  await uploadAndSelectType(page)
  await page.getByRole('button', { name: '启动合规审查' }).click()

  await expect.poll(() => page.evaluate(() => localStorage.getItem('qijian-active-audit'))).not.toBeNull()
  expect(uploadKey).toMatch(/^upload:[a-f0-9]{64}$/)
  expect(auditKey).toMatch(/^audit:[a-f0-9]{64}$/)

  allowCompletion = true
  await page.goto(`${baseUrl}/audit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('审查完成', { exact: true })).toBeVisible()
  await expect(page.getByText('已恢复审查结果，检出 0 条风险')).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('qijian-active-audit'))).toBeNull()
})

test('reuses the same audit operation after an uncertain network response', async ({ page }) => {
  const auditKeys: string[] = []
  let auditAttempts = 0

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T08:00:00Z' })
    }
    if (path.includes('/admin/lookups/')) return fulfillJson(route, [])
    if (path.endsWith('/contracts/upload')) {
      return fulfillJson(route, {
        id: 43,
        filename: '网络重试合同.pdf',
        contract_type: '',
        status: 'uploaded',
        created_at: '2026-09-11T08:00:00Z',
      })
    }
    if (path.endsWith('/contracts/43/parse')) {
      return fulfillJson(route, { contract_id: 43, elements: {}, text_length: 500 })
    }
    if (path.endsWith('/contracts/43/audit')) {
      auditKeys.push(route.request().headers()['idempotency-key'] ?? '')
      auditAttempts += 1
      if (auditAttempts === 1) return route.abort('connectionreset')
      return fulfillJson(route, {
        contract_id: 43,
        status: 'done',
        job_id: 93,
        batch_id: 83,
        risk_count: 0,
      })
    }
    if (path.endsWith('/contracts/43/risks')) return fulfillJson(route, [])
    return fulfillJson(route, [])
  })

  await openAudit(page)
  await uploadAndSelectType(page)
  await page.getByRole('button', { name: '启动合规审查' }).click()
  await expect(page.getByText('网络异常，无法连接到服务器')).toBeVisible()
  await page.getByRole('button', { name: '启动合规审查' }).click()
  await expect(page.getByText('审查完成', { exact: true })).toBeVisible()

  expect(auditKeys).toHaveLength(2)
  expect(auditKeys[1]).toBe(auditKeys[0])
})

test('shows the persisted model error instead of a fixed permission message', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T08:00:00Z' })
    }
    if (path.includes('/admin/lookups/')) return fulfillJson(route, [])
    if (path.endsWith('/contracts/upload')) {
      return fulfillJson(route, {
        id: 42,
        filename: '模型超时合同.pdf',
        contract_type: '',
        status: 'uploaded',
        created_at: '2026-09-11T08:00:00Z',
      })
    }
    if (path.endsWith('/contracts/42/parse')) {
      return fulfillJson(route, { contract_id: 42, elements: {}, text_length: 500 })
    }
    if (path.endsWith('/contracts/42/audit')) {
      return fulfillJson(route, { contract_id: 42, status: 'auditing', job_id: 92, batch_id: 82 })
    }
    if (path.endsWith('/contracts/42/audit-status')) {
      return fulfillJson(route, {
        contract_id: 42,
        status: 'audit_failed',
        error_code: 'MODEL_TIMEOUT',
        error_message: '模型响应超时，请稍后重试',
        retryable: true,
      })
    }
    return fulfillJson(route, [])
  })

  await openAudit(page)
  await uploadAndSelectType(page)
  await page.getByRole('button', { name: '启动合规审查' }).click()

  await expect(page.getByText('模型响应超时，请稍后重试')).toBeVisible()
  await expect(page.getByText('审查失败（需 legal / finance 角色）')).toHaveCount(0)
})

test('stopping browser polling does not claim the backend audit was cancelled', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T08:00:00Z' })
    }
    if (path.includes('/admin/lookups/')) return fulfillJson(route, [])
    if (path.endsWith('/contracts/upload')) {
      return fulfillJson(route, {
        id: 44,
        filename: '停止等待合同.pdf',
        contract_type: '',
        status: 'uploaded',
        created_at: '2026-09-11T08:00:00Z',
      })
    }
    if (path.endsWith('/contracts/44/parse')) {
      return fulfillJson(route, { contract_id: 44, elements: {}, text_length: 500 })
    }
    if (path.endsWith('/contracts/44/audit')) {
      return fulfillJson(route, {
        contract_id: 44,
        status: 'auditing',
        job_id: 94,
        batch_id: 84,
      })
    }
    if (path.endsWith('/contracts/44/audit-status')) {
      return fulfillJson(route, {
        contract_id: 44,
        status: 'auditing',
        job_id: 94,
        batch_id: 84,
      })
    }
    return fulfillJson(route, [])
  })

  await openAudit(page)
  await uploadAndSelectType(page)
  await page.getByRole('button', { name: '启动合规审查' }).click()
  await page.getByRole('button', { name: '停止等待' }).click()

  await expect(page.getByText('已停止页面等待，后台审查仍在执行，可刷新页面恢复')).toBeVisible()
  await page.waitForTimeout(200)
  await expect(page.getByText('审查失败，请重试')).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => localStorage.getItem('qijian-active-audit'))).not.toBeNull()
})

test('clears an expired recovery record when the persisted job no longer exists', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('qijian-active-audit', JSON.stringify({
      owner: 'legal',
      contractId: 45,
      filename: '已删除任务合同.pdf',
      idempotencyKey: 'audit:expired-recovery',
      contractType: '采购合同',
      dimensions: ['legal'],
      jobId: 95,
      batchId: 85,
    }))
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T08:00:00Z' })
    }
    if (path.includes('/admin/lookups/')) return fulfillJson(route, [])
    if (path.endsWith('/contracts/45/audit-status')) {
      return fulfillJson(route, { detail: '审查任务不存在' }, 404)
    }
    return fulfillJson(route, [])
  })

  await page.goto(`${baseUrl}/audit`)
  await page.waitForLoadState('networkidle')

  await expect(page.getByText('审查任务不存在')).toBeVisible()
  await expect.poll(
    () => page.evaluate(() => localStorage.getItem('qijian-active-audit')),
  ).toBeNull()
})
