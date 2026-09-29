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
  const answers = ['已完成终审核验', '已核对合同原件', '已核对授权收款证明']
  page.on('dialog', dialog => dialog.accept(answers.shift()))
  await page.goto('/collaboration')
  await expect(page.getByText('X2 · 法务复查：需人工核验')).toBeVisible()
  await page.getByRole('button', { name: '填写终审并发布' }).click()
  await expect(page.getByRole('button', { name: '已完成终审发布' })).toBeDisabled()
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

test('未处理风险禁止终审，取消质量说明不发送发布请求', async ({ page }) => {
  await setup(page)
  let pending = 1
  await page.route('**/api/v1/workflows/160', route => route.fulfill({ json: { ...snapshot, pending_count: pending } }))
  const requests: string[] = []
  page.on('request', request => { if (request.url().endsWith('/finalize')) requests.push(request.url()) })
  await page.goto('/collaboration')
  await expect(page.getByRole('button', { name: '填写终审并发布' })).toBeDisabled()
  pending = 0
  await page.getByRole('button', { name: '刷新工作流' }).click()
  let dialogs = 0
  page.on('dialog', dialog => ++dialogs === 1 ? dialog.accept('终审意见') : dialog.dismiss())
  await page.getByRole('button', { name: '填写终审并发布' }).click()
  expect(dialogs).toBe(2)
  expect(requests).toEqual([])
})
