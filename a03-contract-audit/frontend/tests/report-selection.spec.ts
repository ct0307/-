import { expect, test, type Page } from '@playwright/test'

const contracts = Array.from({ length: 12 }, (_, i) => ({
  id: i + 1, filename: `测试采购合同${i + 1}.docx`, contract_type: '采购合同', department: i === 11 ? '财务部' : '采购中心',
  party_a: '真实测试甲方', subject: '设备采购', payment_terms: '验收后支付', amount: '100万元', risk_high: 1, risk_medium: 0, risk_low: 0, risk_total: 1,
  status: 'done', job_status: 'done', job_id: i + 50, created_at: '2026-09-17T00:00:00', coverage: { planned: 4, completed: 4 },
  payment_analysis: { status: 'balanced', calculation: '30% + 70% = 100%', events: [{ quote: '验收后支付合同总价的70%', clause_id: '第二条', condition: '验收', percentage: '70', base: '合同总价' }], issues: [] },
}))

function snapshot(ids: number[]) {
  const rows = contracts.filter(c => ids.includes(c.id))
  return {
    report_id: `snapshot-${ids.join('-')}`, generated_at: '2026-09-17T09:00:00Z', contract_ids: ids, contracts: rows,
    summary: { total: ids.length, completed: ids.length, review_required: 0, failed: 0, unreviewed: 0, running: 0, risks: ids.length, high: ids.length, medium: 0, low: 0, supported: 0 },
    risks: rows.map(c => ({ id: c.id, contract_id: c.id, filename: c.filename, category: '付款风险', level: 'high', original_text: '验收前支付全部尾款', risk_reason: '付款先于验收', basis: '依据待复核', suggestion: '增加验收条件', evidence_status: 'unclear', original_text_verified: false, contract_evidence: [], rag_sources: [], agent: 'finance', review_status: 'pending', applicability_status: 'unknown_as_of', rule_executions: [{ rule_id: 'PAY-001', status: 'hit' }], decision_trace: { status: 'manual_review', reason_codes: ['RULE_RESULT_UNRESOLVED'] } })),
    matrix: { categories: ['付款风险'], rows: rows.map(c => ({ contract_id: c.id, filename: c.filename, counts: [1] })) }, rectifications: [], notes: ['无高风险不等于合规'],
  }
}

async function setup(page: Page, empty = false) {
  const requests: Array<number[] | null> = []
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('department', '采购中心')
  })
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/contracts-metadata')) return route.fulfill({ json: empty ? [] : contracts })
    if (url.pathname.endsWith('/preview')) {
      const ids = route.request().postDataJSON().contract_ids
      requests.push(ids)
      return route.fulfill({ json: snapshot(ids ?? contracts.map(c => c.id)) })
    }
    if (url.pathname.endsWith('/export')) return route.fulfill({ body: '测试导出', contentType: 'application/octet-stream' })
    if (url.pathname.endsWith('/audit-status')) return route.fulfill({ json: { contract_id: 1, job_id: 50, status: 'done', cross_checks: [] } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/reports')
  return requests
}

test('默认显示全量看板，勾选单合同自动联动且导出一致，协作可恢复', async ({ page }) => {
  const requests = await setup(page)
  await expect(page.getByTestId('preview-total')).toHaveText('12')
  await expect(page.locator('.chart canvas')).toHaveCount(4)
  await page.screenshot({ path: '../outputs/live-dashboard/initial-mock.png' })
  await expect(page.locator('.chart-grid')).toBeInViewport()
  await page.getByRole('button', { name: '选择合同', exact: true }).click()
  await page.getByRole('checkbox', { name: '选择 测试采购合同1.docx', exact: true }).check()
  await expect(page.getByTestId('preview-total')).toHaveText('1')
  expect(requests).toEqual([null, [1]])
  await expect(page.locator('.risk-matrix tbody tr')).toHaveCount(1)
  const request = page.waitForRequest('**/reports/export?**')
  await page.getByRole('button', { name: '导出 Excel' }).click()
  const url = new URL((await request).url())
  expect(url.searchParams.getAll('contract_ids')).toEqual(['1'])
  expect(url.searchParams.get('report_id')).toBe('snapshot-1')
  await page.getByRole('button', { name: '查看证据' }).first().click()
  await expect(page.getByText('验收前支付全部尾款', { exact: true })).toBeVisible()
  await expect(page.getByText('法规适用性', { exact: true })).toBeVisible()
  await expect(page.getByText('待核验', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('规则核验', { exact: true })).toBeVisible()
  await expect(page.getByText('决策结果', { exact: true })).toBeVisible()
  await expect(page.getByText('人工复核', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Close this dialog' }).click()
  await page.getByRole('button', { name: '查看协作' }).first().click()
  await expect(page.getByText('真实审查会话', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('测试采购合同1.docx', { exact: true })).toBeVisible()
})

test('跨页勾选、筛选和全量均自动联动，清空勾选恢复全部合同', async ({ page }) => {
  const requests = await setup(page)
  await expect(page.getByTestId('preview-total')).toHaveText('12')
  await page.getByRole('button', { name: '选择合同', exact: true }).click()
  await page.getByRole('checkbox', { name: '选择 测试采购合同1.docx', exact: true }).check()
  await page.getByRole('button', { name: '下一页' }).click()
  await page.getByRole('checkbox', { name: '选择 测试采购合同12.docx', exact: true }).check()
  await expect(page.getByTestId('preview-total')).toHaveText('2')
  expect(requests.at(-1)).toEqual([1, 12])
  await page.getByLabel('搜索合同').fill('合同12')
  await page.getByRole('radio', { name: '当前筛选结果' }).check()
  await expect(page.getByRole('button', { name: '导出 Word' })).toBeDisabled()
  await expect(page.getByTestId('preview-total')).toHaveText('1')
  expect(requests.at(-1)).toEqual([12])
  await page.getByRole('radio', { name: '全部可见合同' }).check()
  await expect(page.getByTestId('preview-total')).toHaveText('12')
  expect(requests.at(-1)).toBeNull()
  await page.getByRole('radio', { name: '跟随勾选' }).check()
  await expect(page.getByTestId('preview-total')).toHaveText('2')
  await page.getByRole('button', { name: '清空勾选' }).click()
  await expect(page.getByTestId('preview-total')).toHaveText('12')
  expect(requests.at(-1)).toBeNull()
  const request = page.waitForRequest('**/reports/export?**')
  await page.getByRole('button', { name: '导出 Excel' }).click()
  expect(new URL((await request).url()).searchParams.getAll('contract_ids')).toEqual([])
})

test('空状态和移动端无横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await setup(page, true)
  await expect(page.getByText('暂无合同，请先导入真实测试合同')).toBeVisible()
  await expect(page.getByRole('button', { name: '刷新看板', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '导出 Excel' })).toBeDisabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('加载失败可重试；预览错误不保留可导出的旧结果', async ({ page }) => {
  await setup(page)
  await expect(page.getByTestId('preview-total')).toHaveText('12')
  await page.route('**/reports/preview', route => route.fulfill({ status: 500, json: { detail: '预览生成失败' } }))
  await page.getByRole('button', { name: '选择合同', exact: true }).click()
  await page.getByRole('checkbox', { name: '选择 测试采购合同1.docx', exact: true }).check()
  await expect(page.getByText('预览生成失败', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '导出 Excel' })).toBeDisabled()
  await expect(page.getByTestId('preview-total')).toHaveCount(0)
  await page.unroute('**/reports/preview')
  await page.getByRole('button', { name: '刷新看板', exact: true }).click()
  await expect(page.getByTestId('preview-total')).toHaveText('1')
})

test('旧预览迟到不能覆盖新范围，列表加载失败可重试', async ({ page }) => {
  await setup(page)
  await expect(page.getByTestId('preview-total')).toHaveText('12')
  await page.getByRole('button', { name: '选择合同', exact: true }).click()
  let release: () => void = () => {}
  const pending = new Promise<void>(resolve => { release = resolve })
  await page.route('**/reports/preview', async route => {
    const ids = route.request().postDataJSON().contract_ids
    if (ids?.length === 1) await pending
    await route.fulfill({ json: snapshot(ids ?? contracts.map(c => c.id)) })
  })
  const request = page.waitForRequest('**/reports/preview')
  await page.getByRole('checkbox', { name: '选择 测试采购合同1.docx', exact: true }).check()
  await request
  await expect(page.getByRole('button', { name: '导出 Excel' })).toBeDisabled()
  await page.getByRole('checkbox', { name: '选择 测试采购合同2.docx', exact: true }).check()
  await expect(page.getByTestId('preview-total')).toHaveText('2')
  const response = page.waitForResponse(response => response.url().endsWith('/preview') && response.request().postDataJSON().contract_ids?.length === 1)
  release()
  await response
  await expect(page.getByTestId('preview-total')).toHaveText('2')
  const exported = page.waitForRequest('**/reports/export?**')
  await page.getByRole('button', { name: '导出 Excel' }).click()
  expect(new URL((await exported).url()).searchParams.getAll('contract_ids')).toEqual(['1', '2'])
  let fail = true
  await page.route('**/reports/contracts-metadata', route => route.fulfill(fail ? { status: 503, json: { detail: '合同读取暂不可用' } } : { json: contracts }))
  await page.getByRole('button', { name: '刷新合同列表' }).click()
  await expect(page.getByText('合同读取暂不可用', { exact: true })).toBeVisible()
  fail = false
  await page.getByRole('button', { name: '刷新合同列表' }).click()
  await expect(page.getByRole('checkbox', { name: '选择 测试采购合同1.docx', exact: true })).toBeVisible()
  await expect(page.getByTestId('preview-total')).toHaveText('2')
})

test('筛选无匹配时显示空状态，重新勾选自动回到跟随模式', async ({ page }) => {
  await setup(page)
  await expect(page.getByTestId('preview-total')).toHaveText('12')
  await page.getByRole('button', { name: '选择合同', exact: true }).click()
  await page.getByRole('radio', { name: '当前筛选结果' }).check()
  await page.getByLabel('搜索合同').fill('没有这个合同')
  await expect(page.getByTestId('preview-total')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '导出 Excel' })).toBeDisabled()
  await page.getByLabel('搜索合同').clear()
  await page.getByRole('checkbox', { name: '选择 测试采购合同1.docx', exact: true }).check()
  await expect(page.getByRole('radio', { name: '跟随勾选' })).toBeChecked()
  await expect(page.getByTestId('preview-total')).toHaveText('1')
  await page.getByRole('checkbox', { name: '选择 测试采购合同1.docx', exact: true }).uncheck()
  await expect(page.getByTestId('preview-total')).toHaveText('12')
})

test('离开报表页面后，迟到的合同列表不会再请求看板', async ({ page }) => {
  const requests = await setup(page)
  await expect(page.getByTestId('preview-total')).toHaveText('12')
  let release: () => void = () => {}
  const pending = new Promise<void>(resolve => { release = resolve })
  await page.route('**/reports/contracts-metadata', async route => {
    await pending
    await route.fulfill({ json: contracts })
  })
  const request = page.waitForRequest('**/reports/contracts-metadata')
  await page.getByRole('button', { name: '刷新合同列表' }).click()
  await request
  await page.getByRole('menuitem', { name: '工作台', exact: true }).click()
  await expect(page).not.toHaveURL(/reports/)
  await page.clock.install()
  const response = page.waitForResponse('**/reports/contracts-metadata')
  release()
  await response
  await page.waitForLoadState('networkidle')
  await page.clock.fastForward(1000)
  await page.waitForLoadState('networkidle')
  expect(requests).toEqual([null])
})
