import { expect, test, type Page } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.E2E_PORT ?? '41739'}`

const pendingRisk = {
  id: 901, agent: 'legal', level: 'high', category: '付款期限待核对',
  original_text: '模型候选：验收后付款', risk_reason: '付款期限不明确，可能影响收付款安排',
  basis: '候选法规依据', suggestion: '补充验收和付款的明确期限', confidence: 86,
  tier: 'red', review_status: 'pending', rag_sources: [], evidence_status: 'unclear',
  original_text_verified: false, requires_manual_review: true, support_relation_status: 'unclear',
  applicability_status: 'unknown_as_of', applicability_reason_codes: ['AS_OF_DATE_UNKNOWN'],
  support_validation_reason: '来源适用性未确认或已失效',
  support_validator_version: 'support-v4', support_validation_mode: 'semantic',
  support_validation_failed_stage: 'applicability', support_validation_reason_code: 'SOURCE_NOT_APPLICABLE',
  retrieval_attempts: [{ attempt: 'initial', evidence_relations: [{
    source: { source: '法规检索候选'.repeat(10), evidence_id: 'KC-9', content: '候选法条内容' },
    status: 'unclear', reason: '需要核对适用时点',
  }] }],
}

async function prepare(page: Page, risks: unknown[] = [pendingRisk], batch?: Record<string, unknown>) {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('authorized_departments', JSON.stringify(['法务部']))
    localStorage.setItem('qijian-completed-audit', JSON.stringify({ owner: 'legal', contractId: 901, filename: '专业复核.pdf', jobId: 9901 }))
  })
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith('/runtime/status')) body = { status: 'online' }
    else if (path.endsWith('/contracts/901/audit-status')) body = {
      contract_id: 901, job_id: 9901, status: 'review_required', risk_count: risks.length,
      cross_checks: [], requires_review: true, review_reason: '请复核风险依据',
    }
    else if (path.endsWith('/contracts/901/risks')) body = risks
    else if (path.endsWith('/batches/88')) body = batch
    else if (path.endsWith('/handoffs')) body = { state: 'NO_DATA', items: [] }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto(`${baseUrl}/audit${batch ? '?batch=88' : ''}`)
}

async function openRisk(page: Page) {
  await page.getByRole('button', { name: '复核风险：付款期限待核对' }).click()
  return page.locator('.el-drawer').last()
}

for (const width of [375, 1280]) {
  test(`待核风险先解释业务和下一步，候选原文与诊断可展开 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await prepare(page)
    const drawer = await openRisk(page)
    const drawerBody = drawer.locator('.el-drawer__body')
    await expect.poll(() => drawerBody.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
    await expect(drawer.getByRole('heading', { name: '业务摘要', exact: true })).toBeVisible()
    await expect(drawer.getByText(pendingRisk.risk_reason, { exact: true })).toBeVisible()
    await expect(drawer.getByText('请核对合同已确认的签订日期，再核验法规在该日期是否适用。', { exact: true })).toBeVisible()
    await expect(drawer.getByText('适用时点未知，不能据此认定法规已失效。', { exact: true })).toBeVisible()
    await expect(drawer.getByText('原文定位尚未通过，模型候选不能作为已核验合同原文。', { exact: true })).toBeVisible()
    await expect(drawer.getByRole('heading', { name: '合同原文（已定位）', exact: true })).toHaveCount(0)
    await expect(drawer.getByRole('heading', { name: '命中原文', exact: true })).toHaveCount(0)
    await expect(drawer.getByText(pendingRisk.original_text, { exact: true })).not.toBeVisible()
    await expect(drawer.getByText(/support-v4/)).not.toBeVisible()
    await expect(drawer.getByText(/原因码：SOURCE_NOT_APPLICABLE/)).not.toBeVisible()
    await expect(drawer.getByText(/AS_OF_DATE_UNKNOWN/)).not.toBeVisible()
    await expect(drawer.getByText('无可靠依据', { exact: true })).toBeVisible()
    await drawer.getByText('查看模型候选文本', { exact: true }).click()
    await expect(drawer.getByText(pendingRisk.original_text, { exact: true })).toBeVisible()
    await drawer.getByText('技术核验与检索记录', { exact: true }).click()
    await expect(drawer.getByText(/原因码：SOURCE_NOT_APPLICABLE/)).toBeVisible()
    await expect(drawer.getByText(/support-v4/)).toBeVisible()
    await expect(drawer.getByText('候选法条内容', { exact: true })).toBeVisible()
    await expect.poll(() => drawerBody.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
    await expect(drawer.getByRole('button', { name: '确认并生成整改项', exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}

test('阅读视角切换只改变关注提示，共用风险和复核动作', async ({ page }) => {
  await prepare(page)
  const drawer = await openRisk(page)
  await expect(drawer.getByText('核对条款效力、法规适用时点与责任分配。', { exact: true })).toBeVisible()
  await drawer.getByText('财务视角', { exact: true }).click()
  await expect(drawer.getByRole('radio', { name: '财务视角', exact: true })).toBeChecked()
  await expect(drawer.getByText('核对付款条件、金额口径与履约凭据；金额和计算结果以合同及已核验记录为准。', { exact: true })).toBeVisible()
  await expect(drawer.getByText('阅读视角仅调整关注提示，共用同一复核记录。', { exact: true })).toBeVisible()
  await expect(drawer.getByText(pendingRisk.risk_reason, { exact: true })).toBeVisible()
  await expect(drawer.getByRole('button', { name: '确认并生成整改项', exact: true })).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('role'))).toBe('legal')
})

test('业务摘要完整保留币种和业务编号，详情不改写原始风险说明', async ({ page }) => {
  const businessReason = '合同A_2026_001：付款币种为美元（USD）或人民币（CNY），请核对结算口径。'
  await prepare(page, [{ ...pendingRisk, risk_reason: businessReason }])
  const riskCard = page.getByRole('button', { name: '复核风险：付款期限待核对' })
  await expect(riskCard.locator('.risk-line')).toHaveText(businessReason)
  const drawer = await openRisk(page)
  await expect(drawer.locator('.business-summary > .step-content > .rd-text')).toHaveText(businessReason)
})

test('批次复核摘要只解释已知原因码，保留未知编号及币种', async ({ page }) => {
  const reason = '合同A_2026_001以美元（USD）或人民币（CNY）结算；SOURCE_NOT_APPLICABLE；FUTURE_REVIEW_CODE'
  await prepare(page, [], {
    id: 88, status: 'review_required', total: 1, completed: 1, failed: 0, progress: 100,
    items: [{ id: 7, contract_id: 901, filename: '币种待核对合同.pdf', status: 'review_required', progress: 100,
      progress_stage: 'completed', requires_review: true, review_reason: reason, error: null }],
  })
  const region = page.getByRole('region', { name: '审查批次 88' })
  await expect(region.locator('.batch-result-item-review-reason')).toHaveText('合同A_2026_001以美元（USD）或人民币（CNY）结算；法规适用性待核对；FUTURE_REVIEW_CODE')
  await region.getByText('完整复核说明', { exact: true }).click()
  await expect(region.getByText(reason, { exact: true })).toBeVisible()
})

for (const scenario of [
  { name: '顶层失效但缺少已确认日期', status: 'expired', codes: ['AS_OF_DATE_UNKNOWN'], sources: [],
    explanation: '适用时点未知，不能据此认定法规已失效。' },
  { name: '顶层适用但来源状态混合', status: 'applicable', codes: ['SOURCE_APPLICABLE', 'SOURCE_EXPIRED'],
    sources: [
      { source: '法规甲', content: '适用来源', reliable: true, applicability_status: 'applicable' },
      { source: '法规乙', content: '失效来源', reliable: true, applicability_status: 'expired' },
    ],
    explanation: '依据来源存在多种适用状态，请逐条核对各法规的适用时点。' },
]) {
  test(`适用性标签与正文一致：${scenario.name}`, async ({ page }) => {
    await prepare(page, [{ ...pendingRisk, applicability_status: scenario.status,
      applicability_reason_codes: scenario.codes, rag_sources: scenario.sources }])
    const drawer = await openRisk(page)
    const applicability = drawer.locator('section').filter({ has: page.getByRole('heading', { name: '法规适用性', exact: true }) })
    await expect(applicability.getByText('待核验', { exact: true })).toBeVisible()
    await expect(applicability.getByText(scenario.explanation, { exact: true })).toBeVisible()
    await expect(applicability.getByText('适用性已核验', { exact: true })).toHaveCount(0)
    await expect(applicability.getByText('法规时点不适用', { exact: true })).toHaveCount(0)
  })
}

for (const [status, explanation] of [
  ['expired', '该法规在审查时点已失效，请核对替代规定及过渡条款。'],
  ['not_yet_effective', '该法规在审查时点尚未生效，请核对当时有效的规定。'],
  ['unresolved', '法规适用条件尚未确认，请核对法规版本、地域及合同事实。'],
]) {
  test(`法规状态 ${status} 单独解释且不虚构缺失签订日期`, async ({ page }) => {
    await prepare(page, [{ ...pendingRisk, applicability_status: status, applicability_reason_codes: [] }])
    const drawer = await openRisk(page)
    await expect(drawer.getByText(explanation, { exact: true })).toBeVisible()
    await expect(drawer.getByText('请核对合同已确认的签订日期，再核验法规在该日期是否适用。', { exact: true })).toHaveCount(0)
  })
}

for (const scenario of [
  { name: '顶层待核验但来源单一失效', status: 'unresolved', codes: ['SOURCE_EXPIRED'],
    explanation: '该法规在审查时点已失效，请核对替代规定及过渡条款。' },
  { name: '顶层待核验但来源单一未生效', status: 'unresolved', codes: ['SOURCE_NOT_YET_EFFECTIVE'],
    explanation: '该法规在审查时点尚未生效，请核对当时有效的规定。' },
  { name: '来源存在多种时间状态', status: 'unresolved', codes: ['SOURCE_EXPIRED', 'SOURCE_NOT_YET_EFFECTIVE'],
    explanation: '依据来源存在多种适用状态，请逐条核对各法规的适用时点。' },
  { name: '适用来源与失效来源混合', status: 'unresolved', codes: ['SOURCE_EXPIRED', 'SOURCE_APPLICABLE'],
    explanation: '依据来源存在多种适用状态，请逐条核对各法规的适用时点。' },
  { name: '未知日期优先于失效原因', status: 'unresolved', codes: ['SOURCE_EXPIRED', 'AS_OF_DATE_UNKNOWN'],
    explanation: '适用时点未知，不能据此认定法规已失效。' },
  { name: '顶层未知日期优先于失效原因', status: 'unknown_as_of', codes: ['SOURCE_EXPIRED'],
    explanation: '适用时点未知，不能据此认定法规已失效。' },
  { name: '明确未知日期优先于顶层失效状态', status: 'expired', codes: ['AS_OF_DATE_UNKNOWN'],
    explanation: '适用时点未知，不能据此认定法规已失效。' },
  { name: '来源记录显示混合但原因码不完整', status: 'unresolved', codes: ['SOURCE_EXPIRED'],
    sources: [
      { source: '法规甲', content: '适用来源', reliable: true, applicability_status: 'applicable' },
      { source: '法规乙', content: '失效来源', reliable: true, applicability_status: 'expired' },
    ],
    explanation: '依据来源存在多种适用状态，请逐条核对各法规的适用时点。' },
]) {
  test(`真实来源状态汇总：${scenario.name}`, async ({ page }) => {
    await prepare(page, [{ ...pendingRisk, applicability_status: scenario.status, applicability_reason_codes: scenario.codes,
      rag_sources: scenario.sources || [] }])
    const drawer = await openRisk(page)
    await expect(drawer.getByText(scenario.explanation, { exact: true })).toBeVisible()
    if (scenario.explanation.includes('未知')) {
      await expect(drawer.getByText('请核对合同已确认的签订日期，再核验法规在该日期是否适用。', { exact: true })).toBeVisible()
    } else {
      await expect(drawer.getByText('请核对合同已确认的签订日期，再核验法规在该日期是否适用。', { exact: true })).toHaveCount(0)
    }
  })
}

test('原文定位成功才展示合同原文，仍与依据核验分开', async ({ page }) => {
  await prepare(page, [{ ...pendingRisk, original_text_verified: true }])
  const drawer = await openRisk(page)
  await expect(drawer.getByRole('heading', { name: '合同原文（已定位）', exact: true })).toBeVisible()
  await expect(drawer.getByText(pendingRisk.original_text, { exact: true })).toBeVisible()
  await expect(drawer.getByText('依据与原文已核验', { exact: true })).toHaveCount(0)
})

test('批次压缩重复原因但保留完整说明，并明确机器100%不代表人工完成', async ({ page }) => {
  const reason = Array(8).fill('来源适用性未确认或已失效（SOURCE_NOT_APPLICABLE）；AS_OF_DATE_UNKNOWN').join('；')
  await prepare(page, [], {
    id: 88, status: 'review_required', total: 1, completed: 1, failed: 0, progress: 100,
    items: [{ id: 7, contract_id: 901, filename: '待复核合同.pdf', status: 'review_required', progress: 100,
      progress_stage: 'completed', requires_review: true, review_reason: reason, error: null }],
  })
  const region = page.getByRole('region', { name: '审查批次 88' })
  await expect(region.getByText('机器处理进度（100% 不代表人工复核完成）', { exact: true })).toBeVisible()
  await expect(region.getByText('人工复核以各风险的复核记录为准。', { exact: true })).toBeVisible()
  const summary = region.locator('.batch-result-item-review-reason')
  expect((await summary.innerText()).length).toBeLessThanOrEqual(100)
  await expect(summary).not.toContainText(/SOURCE_NOT_APPLICABLE|AS_OF_DATE_UNKNOWN/)
  await expect(region.getByText(reason, { exact: true })).not.toBeVisible()
  await region.getByText('完整复核说明', { exact: true }).click()
  await expect(region.getByText(reason, { exact: true })).toBeVisible()
})

test('空结果和失败批次在手机端保留边界与恢复入口', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 })
  await prepare(page, [], {
    id: 88, status: 'failed', total: 1, completed: 1, failed: 1, progress: 100,
    items: [{ id: 7, contract_id: 901, filename: '失败合同.pdf', status: 'failed', progress: 68,
      progress_stage: 'failed', error: '模型服务暂不可用', error_code: 'MODEL_UNAVAILABLE', retryable: true,
      error_action: '请检查服务后重试' }],
  })
  await expect(page.getByText('审查结果不完整，暂不能据此判断合同无风险', { exact: true })).toBeVisible()
  await expect(page.getByText('模型服务暂不可用', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '重试失败项', exact: true })).toBeVisible()
  await expect(page.getByText('机器处理进度（100% 不代表人工复核完成）', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('批次仅展示实际记录的耗时，未知耗时不伪造为零', async ({ page }) => {
  await prepare(page, [], {
    id: 88, status: 'done', total: 2, completed: 2, failed: 0, progress: 100,
    items: [
      { id: 7, contract_id: 901, filename: '计时合同.pdf', status: 'done', progress: 100,
        progress_stage: 'completed', queue_wait_ms: 1200, processing_ms: 31500, total_ms: 32700 },
      { id: 8, contract_id: 902, filename: '历史合同.pdf', status: 'done', progress: 100,
        progress_stage: 'completed', queue_wait_ms: null, processing_ms: null, total_ms: null },
    ],
  })
  const timed = page.locator('.batch-result-item').filter({ hasText: '计时合同.pdf' })
  await expect(timed.getByText('排队 1.2 秒 · 处理 31.5 秒 · 总耗时 32.7 秒', { exact: true })).toBeVisible()
  const historical = page.locator('.batch-result-item').filter({ hasText: '历史合同.pdf' })
  await expect(historical.locator('.batch-result-item-timing')).toHaveCount(0)
})
