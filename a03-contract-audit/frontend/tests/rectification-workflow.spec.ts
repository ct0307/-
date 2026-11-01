import { expect, test, type Page } from '@playwright/test'

async function prepare(page: Page) {
  let item = {
    id: 'RC101',
    contract: '软件开发合同.pdf',
    risk: '违约责任约定不明',
    level: 'high',
    owner: 'business',
    status: '处理中',
    created: '2026-09-15',
    due: '2026-09-20',
    note: '补充违约情形和赔偿范围。',
    contract_id: 7,
    acceptance_criteria: '违约情形与赔偿范围明确，修订稿可核对。',
    contract_stage: 'unsigned', handling_method: 'revision', version: 1,
    risk_id: 42,
    resolution: '',
    review_comment: '',
    submitted_at: null as string | null,
    closed_at: null as string | null,
  }
  const updates: Array<Record<string, unknown>> = []

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/auth/login')) {
      await route.fulfill({ json: {
        access_token: 'rectify-test-token', token_type: 'bearer', role: 'business',
        username: 'business', department: '研发部', authorized_departments: ['研发部'],
      } })
    } else if (path.endsWith('/rectifications') && request.method() === 'GET') {
      await route.fulfill({ json: [item] })
    } else if (path.endsWith('/rectifications/RC101') && request.method() === 'PATCH') {
      const payload = request.postDataJSON() as Record<string, unknown>
      updates.push(payload)
      item = {
        ...item,
        ...payload,
        version: item.version + 1,
        submitted_at: payload.status === '待复核' ? '2026-09-17T02:00:00Z' : item.submitted_at,
        closed_at: payload.status === '已闭环' ? '2026-09-17T03:00:00Z' : item.closed_at,
      }
      await route.fulfill({ json: item })
    } else if (path.endsWith('/rectifications/materials')) {
      await route.fulfill({ json: [{ id: 8, filename: '整改修订版.docx', content_sha256: 'evidence-sha' }] })
    } else if (path.endsWith('/dashboard/summary')) {
      await route.fulfill({ json: {
        total_contracts: 0, total_risks: 0, level_distribution: {}, category_distribution: [],
        contract_status: {}, review_status: {}, agent_distribution: {},
      } })
    } else if (path.endsWith('/runtime/status')) {
      await route.fulfill({ json: { status: 'online', model: 'test-model' } })
    } else {
      await route.fulfill({ json: [] })
    }
  })

  await page.goto('/login')
  await page.getByPlaceholder('用户名').fill('legal')
  await page.getByPlaceholder('密码').fill('legal123')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  return updates
}

test('整改结果必须经复核才能闭环，且移动端无横向溢出', async ({ page }) => {
  const updates = await prepare(page)
  await page.goto('/rectify')
  await expect(page.getByRole('button', { name: /RC101/ })).toBeVisible()
  await page.getByRole('button', { name: /RC101/ }).click()

  await page.getByRole('button', { name: '提交复核' }).click()
  await expect(page.getByText('请填写具体整改结果')).toBeVisible()
  await page.getByLabel('整改结果 必填').fill('已补充违约责任、违约金计算方式及赔偿范围。')
  await page.getByLabel('修改后条款', { exact: true }).fill('违约方按合同金额百分之十支付违约金。')
  await page.getByRole('combobox', { name: '关联整改材料' }).click()
  await page.getByRole('option', { name: /整改修订版.docx/ }).click()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '提交复核' }).click()
  await expect(page.getByText('RC101 · 待复核')).toBeVisible()
  await expect(page.getByRole('button', { name: '通过并闭环' })).toHaveCount(0)

  // 切换为另一位法务，避免把责任人提交并自验作为合法流程。
  await page.evaluate(() => { localStorage.setItem('username', 'legal-reviewer'); localStorage.setItem('role', 'legal') })
  await page.reload()
  await page.getByRole('button', { name: /RC101/ }).click()

  await page.getByLabel('复核意见').fill('修订条款与原风险一致，验收通过。')
  await page.getByRole('button', { name: '通过并闭环' }).click()
  await expect(page.getByText('RC101 · 已闭环')).toBeVisible()
  expect(updates.map((update) => update.status)).toEqual(['待复核', '已闭环'])

  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
