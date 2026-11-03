import { expect, test, type Page } from '@playwright/test'

const snapshot = {
  state: 'awaiting_review', can_finalize: true, version: 0, generation: 1,
  review_fingerprint: 'a'.repeat(64), pending_count: 0, requires_quality_ack: true,
  groups: [{ issue_id: 'I1', category: '付款期限', agents: ['legal', 'finance'] }],
  conflicts: [{ id: 'X2', trigger: '收款主体不一致', note: '请核对授权收款证明' }],
  directed_reviews: [{ check_id: 'X2', target_agent: 'legal', status: 'manual_required', verdict: 'unclear' }],
  budget: { calls: 4, max_calls: 120 },
}

async function setup(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'fixture-token')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('qijian-completed-audit', JSON.stringify({ owner: 'legal', contractId: 160, jobId: 55, filename: '终审测试合同.docx' }))
  })
  await page.route('**/api/v1/**', route => route.fulfill({ json: route.request().url().includes('/audit-status')
    ? { contract_id: 160, job_id: 55, status: 'review_required', cross_checks: [] } : [] }))
}

test('终审提交绑定快照、质量说明和逐项裁决，窄屏正常', async ({ page }) => {
  await setup(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/v1/workflows/160', route => route.fulfill({ json: snapshot }))
  let submitted: Record<string, unknown> | undefined
  await page.route('**/api/v1/workflows/160/finalize', route => {
    submitted = route.request().postDataJSON()
    return route.fulfill({ json: { ...snapshot, state: 'published', version: 1 } })
  })
  page.on('dialog', () => { throw new Error('终审不得依赖浏览器原生弹框') })
  await page.goto('/collaboration')
  await expect(page.getByText('X2 · 法务复查：需人工核验')).toBeVisible()
  await page.getByRole('button', { name: '填写终审并发布' }).click()
  const form = page.getByRole('dialog', { name: '人工终审' })
  await form.getByLabel('终审意见', { exact: true }).fill('已完成终审核验')
  await form.getByLabel('质量核验意见', { exact: true }).fill('已核对合同原件')
  await form.getByLabel('X2 裁决意见', { exact: true }).fill('已核对授权收款证明')
  await form.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(page.getByRole('button', { name: '已完成终审发布' })).toBeDisabled()
  await expect(page.getByText('已记录 1 项冲突的人工裁决；模型复查记录仍保留供追溯。')).toBeVisible()
  await expect(page.getByText('仍有 1 项冲突需要人工裁决；模型复查不能替代终审。')).toHaveCount(0)
  expect(submitted).toEqual({ expected_generation: 1, expected_version: 0,
    review_fingerprint: snapshot.review_fingerprint, comment: '已完成终审核验',
    quality_comment: '已核对合同原件', conflict_resolutions: { X2: '已核对授权收款证明' } })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('加载失败可重试，历史快照空状态不冒充待终审', async ({ page }) => {
  await setup(page)
  let failed = true
  await page.route('**/api/v1/workflows/160', route => failed
    ? route.fulfill({ status: 503, json: { detail: '工作流暂不可用' } })
    : route.fulfill({ json: { state: 'not_available', can_finalize: false, message: '历史合同请重新审查' } }))
  await page.goto('/collaboration')
  await expect(page.getByText('工作流暂不可用', { exact: true }).first()).toBeVisible()
  failed = false
  await page.getByRole('button', { name: '刷新工作流' }).click()
  await expect(page.getByText('历史合同请重新审查')).toBeVisible()
  await expect(page.getByRole('button', { name: '填写终审并发布' })).toHaveCount(0)
})

test('未处理风险禁止终审，必填校验与取消不发送发布请求', async ({ page }) => {
  await setup(page)
  let pending = 1
  await page.route('**/api/v1/workflows/160', route => route.fulfill({ json: { ...snapshot, pending_count: pending } }))
  const requests: string[] = []
  page.on('request', request => { if (request.url().endsWith('/finalize')) requests.push(request.url()) })
  await page.goto('/collaboration')
  await expect(page.getByRole('button', { name: '填写终审并发布' })).toBeDisabled()
  pending = 0
  await page.getByRole('button', { name: '刷新工作流' }).click()
  await page.getByRole('button', { name: '填写终审并发布' }).click()
  const form = page.getByRole('dialog', { name: '人工终审' })
  await form.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(form.getByText('请填写终审意见')).toBeVisible()
  await form.getByLabel('终审意见', { exact: true }).fill('终审意见')
  await form.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(form.getByText('请填写质量核验意见')).toBeVisible()
  await form.getByRole('button', { name: '取消', exact: true }).click()
  await expect(form).not.toBeVisible()
  expect(requests).toEqual([])
})

test('缺少整改任务提前展示缺项与补齐入口', async ({ page }) => {
  await setup(page)
  await page.route('**/api/v1/workflows/160', route => route.fulfill({ json: {
    ...snapshot, missing_rectifications: [{ risk_id: 42, category: '付款期限' }],
  } }))
  await page.goto('/collaboration')
  await expect(page.getByText('付款期限 · 风险 #42')).toBeVisible()
  await expect(page.getByRole('button', { name: '填写终审并发布' })).toBeDisabled()
  await page.getByRole('button', { name: '补齐整改计划' }).click()
  await expect(page).toHaveURL(/\/audit/)
})

test('发布失败保留表单意见，可重试', async ({ page }) => {
  await setup(page)
  let failed = true
  const current = () => ({ ...snapshot, requires_quality_ack: false, conflicts: [],
    version: failed ? 0 : 1, review_fingerprint: (failed ? 'a' : 'b').repeat(64) })
  await page.route('**/api/v1/workflows/160', route => route.fulfill({ json: current() }))
  let submitted: Record<string, unknown> | undefined
  await page.route('**/api/v1/workflows/160/finalize', route => {
    submitted = route.request().postDataJSON()
    if (failed) return route.fulfill({ status: 409, json: { detail: '审查或人工意见已变化，请刷新后重新确认' } })
    expect(submitted).toMatchObject({ expected_version: 1, review_fingerprint: 'b'.repeat(64) })
    return route.fulfill({ json: { ...current(), state: 'published', version: 2 } })
  })
  await page.goto('/collaboration')
  await page.getByRole('button', { name: '填写终审并发布' }).click()
  const form = page.getByRole('dialog', { name: '人工终审' })
  await form.getByLabel('终审意见', { exact: true }).fill('本次已独立核对')
  await form.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(form.getByText('审查或人工意见已变化，请刷新后重新确认')).toBeVisible()
  await expect(form.getByLabel('终审意见', { exact: true })).toHaveValue('本次已独立核对')
  failed = false
  await form.getByRole('button', { name: '刷新终审状态', exact: true }).click()
  await expect(form.getByText('已刷新，请重新核对当前审查、质量说明和冲突裁决后确认发布。')).toBeVisible()
  await expect(form.getByLabel('终审意见', { exact: true })).toHaveValue('本次已独立核对')
  await form.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(form).not.toBeVisible()
  await expect(page.getByRole('button', { name: '已完成终审发布' })).toBeDisabled()
})
