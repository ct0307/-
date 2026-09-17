import { expect, test } from '@playwright/test'

for (const riskCount of [0, 1]) {
  test(`完成后刷新恢复真实结果：${riskCount} 条风险`, async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('token', 'test-token')
      localStorage.setItem('username', 'legal')
      localStorage.setItem('role', 'legal')
      localStorage.setItem('department', '法务部')
      localStorage.setItem('qijian-completed-audit', JSON.stringify({ owner: 'legal', contractId: 160, jobId: 55, filename: '真实采购合同.docx' }))
    })
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      const body = path.endsWith('/audit-status')
        ? { contract_id: 160, job_id: 55, status: 'done', cross_checks: [] }
        : path.endsWith('/risks')
          ? Array.from({ length: riskCount }, () => ({ id: 1, contract_id: 160, agent: 'legal', category: '付款', level: 'high', review_status: 'pending', original_text: '真实条款', basis: '待复核依据', suggestion: '明确付款期限', confidence: 80, tier: 'red' }))
          : []
      await route.fulfill({ json: body })
    })
    await page.goto('/collaboration')
    await expect(page.getByText('真实审查会话', { exact: true })).toBeVisible()
    await expect(page.getByText('真实采购合同.docx', { exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByText('真实采购合同.docx', { exact: true })).toBeVisible()
    await expect(page.getByText('演示数据 · 未开始审查')).toHaveCount(0)
    await expect(page.getByText('暂无跨智能体冲突记录')).toBeVisible()
  })
}

test('无会话显示空状态，跨账号不恢复', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('username', 'finance')
    localStorage.setItem('role', 'finance')
    localStorage.setItem('qijian-completed-audit', JSON.stringify({ owner: 'legal', contractId: 160, jobId: 55, filename: '其他账号.docx' }))
  })
  await page.route('**/api/v1/**', route => route.fulfill({ json: [] }))
  await page.goto('/collaboration')
  await expect(page.getByText('尚未选择审查结果', { exact: true })).toBeVisible()
  await expect(page.getByText('其他账号.docx', { exact: true })).toHaveCount(0)
  await expect(page.getByText('演示数据 · 未开始审查')).toHaveCount(0)
})

test('规则校验来源独立展示，不冒充法务或财务模型', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('qijian-completed-audit', JSON.stringify({ owner: 'legal', contractId: 160, jobId: 55, filename: '逻辑合同.docx' }))
  })
  await page.route('**/api/v1/**', route => route.fulfill({ json: route.request().url().includes('/audit-status') ? {
    contract_id: 160, job_id: 55, status: 'done', cross_checks: [{ id: 'FC-1', from_agent: 'system', to_agent: 'finance', trigger: '付款比例超过100%', action: '人工核对付款基数', verdict: 'conflict', note: '30% + 80% = 110%' }],
  } : [] }))
  await page.goto('/collaboration')
  await expect(page.getByText('规则校验', { exact: true })).toBeVisible()
  await expect(page.getByText('30% + 80% = 110%', { exact: true })).toBeVisible()
})

test('恢复请求失败保留标识，可重试恢复；已删除合同清除标识', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('qijian-completed-audit', JSON.stringify({ owner: 'legal', contractId: 160, jobId: 55, filename: '恢复测试.docx' }))
  })
  let status = 503
  await page.route('**/api/v1/**', route => {
    if (route.request().url().includes('/audit-status')) return route.fulfill({ status, json: status === 200 ? { contract_id: 160, job_id: 55, status: 'done', cross_checks: [] } : { detail: '恢复失败，请重试' } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/collaboration')
  await expect(page.getByText('恢复失败，请重试', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => !!localStorage.getItem('qijian-completed-audit'))).toBe(true)
  status = 200
  await page.getByRole('button', { name: '重新加载' }).click()
  await expect(page.getByText('恢复测试.docx', { exact: true })).toBeVisible()
  status = 404
  await page.reload()
  await expect(page.getByText('恢复失败，请重试', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('qijian-completed-audit'))).toBeNull()
})
