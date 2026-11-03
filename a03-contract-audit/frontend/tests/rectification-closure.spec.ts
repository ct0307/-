import { expect, test, type Page } from '@playwright/test'

const baseItem = {
  id: 'RC201', contract: '技术服务合同.pdf', contract_id: 8, risk_id: 42,
  risk: '违约责任约定不明', level: 'high', owner: 'business', status: '处理中',
  created: '2026-11-01', due: '2026-11-10', note: '补充赔偿范围',
  acceptance_criteria: '明确违约金和赔偿范围', contract_stage: 'unsigned', handling_method: 'revision',
  collaborators: [], resolution: '', review_comment: '', submitted_at: null, closed_at: null,
  before_text: '违约责任另行协商。', original_text_verified: false, after_text: '',
  evidence: [], events: [], version: 1,
}

async function prepare(page: Page, options: { role?: string; username?: string; item?: Record<string, unknown>; fail?: boolean; empty?: boolean; listError?: boolean } = {}) {
  const role = options.role ?? 'business'
  const username = options.username ?? 'business'
  let item = { ...baseItem, ...options.item }
  const updates: Array<Record<string, unknown>> = []
  await page.addInitScript(({ role, username }) => {
    localStorage.setItem('token', 'closure-test')
    localStorage.setItem('role', role)
    localStorage.setItem('username', username)
    localStorage.setItem('department', '研发部')
  }, { role, username })
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/rectifications') && route.request().method() === 'GET') {
      if (options.listError) await route.fulfill({ status: 503, json: { detail: '整改列表暂时不可用' } })
      else await route.fulfill({ json: options.empty ? [] : [item] })
    } else if (path.endsWith('/rectifications/participants')) {
      await route.fulfill({ json: [{ id: 1, username: 'business', role: 'business', department: '研发部' }, { id: 2, username: 'legal', role: 'legal', department: '法务部' }] })
    } else if (path.endsWith('/rectifications/materials')) {
      await route.fulfill({ json: [{ id: 9, filename: '修订稿.docx', content_sha256: 'hash-evidence' }] })
    } else if (path.includes('/rectifications/RC201') && ['PATCH', 'POST'].includes(route.request().method())) {
      const payload = route.request().postDataJSON() as Record<string, unknown>
      updates.push(payload)
      if (path.endsWith('/plan') && Object.keys(payload).some(key => !['owner', 'collaborators', 'due', 'note', 'acceptance_criteria', 'contract_stage', 'handling_method', 'version'].includes(key))) return void await route.fulfill({ status: 422, json: { detail: '计划更新包含不允许的字段' } })
      if (options.fail) await route.fulfill({ status: 409, json: { detail: '任务已被其他人员更新，请刷新后重试' } })
      else {
        item = { ...item, ...payload, version: item.version + 1 }
        await route.fulfill({ json: item })
      }
    } else if (path.endsWith('/runtime/status')) await route.fulfill({ json: { status: 'online' } })
    else await route.fulfill({ json: [] })
  })
  await page.goto('/rectify')
  if (!options.empty && !options.listError) await page.getByRole('button', { name: /RC201/ }).click()
  return updates
}

test('提交复核必须关联实际材料并填写修改后条款', async ({ page }) => {
  const updates = await prepare(page)
  await page.getByLabel('整改结果 必填').fill('补充违约金计算与赔偿上限。')
  await page.getByRole('button', { name: '提交复核', exact: true }).click()
  await expect(page.getByText('请至少关联一份修订版或凭证')).toBeVisible()
  expect(updates).toHaveLength(0)
  await page.getByRole('combobox', { name: '关联整改材料' }).click()
  await page.getByRole('option', { name: /修订稿.docx/ }).click()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '提交复核', exact: true }).click()
  await expect(page.getByText('请填写修改后条款')).toBeVisible()
  await page.getByLabel('修改后条款').fill('违约方按合同金额的百分之十支付违约金。')
  await page.getByRole('button', { name: '提交复核', exact: true }).click()
  await expect(page.getByText('RC201 · 待复核')).toBeVisible()
  expect(updates[0]).toMatchObject({ status: '待复核', evidence_contract_ids: [9], version: 1 })
})

test('独立法务验收必须填写本次意见，不能借用旧意见或修改提交结果', async ({ page }) => {
  const updates = await prepare(page, { role: 'legal', username: 'reviewer', item: { status: '待复核', submitted_by: 7, review_comment: '上轮退回：缺少凭证', resolution: '新一轮修订已完成', after_text: '新条款', can_review: true } })
  await expect(page.getByLabel('复核意见', { exact: true })).toHaveValue('')
  await expect(page.getByLabel('整改结果', { exact: true })).toHaveAttribute('readonly', '')
  await page.getByRole('button', { name: '通过并闭环' }).click()
  await expect(page.getByText('请填写复核结论')).toBeVisible()
  expect(updates).toHaveLength(0)
  await page.getByLabel('复核意见', { exact: true }).fill('本轮条款与材料完整，独立验收通过。')
  await page.getByRole('button', { name: '通过并闭环' }).click()
  await expect(page.getByText('RC201 · 已闭环')).toBeVisible()
  expect(updates[0]).toEqual({ status: '已闭环', version: 1, review_comment: '本轮条款与材料完整，独立验收通过。' })
})

test('服务端禁止能力优先，非责任人及自验管理员不显示执行验收', async ({ page }) => {
  await prepare(page, { role: 'admin', username: 'admin', item: { status: '待复核', submitted_by: 1, can_review: false, can_manage: false } })
  await expect(page.getByRole('button', { name: '通过并闭环' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '退回整改' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '提交复核', exact: true })).toHaveCount(0)
})

test('风险接受独立申请与管理员批准，保持独立状态及剩余风险', async ({ page }) => {
  const updates = await prepare(page)
  await page.getByText('申请风险接受', { exact: true }).click()
  await page.getByRole('button', { name: '提交风险接受申请' }).click()
  await expect(page.getByText('请填写控制措施、接受理由和剩余风险')).toBeVisible()
  await page.getByLabel('整改结果 必填').fill('限定预付款比例并每周核对履约情况。')
  await page.getByLabel('接受理由', { exact: true }).fill('对方暂不接受修改，项目按授权范围继续履行。')
  await page.getByLabel('剩余风险', { exact: true }).fill('对方迟延履行时仍可能出现回款争议。')
  await page.getByRole('button', { name: '提交风险接受申请' }).click()
  await expect(page.getByText('RC201 · 待风险接受')).toBeVisible()
  await expect(page.getByRole('button', { name: '批准风险接受' })).toHaveCount(0)
  expect(updates[0]).toMatchObject({ status: '待风险接受', version: 1, residual_risk: '对方迟延履行时仍可能出现回款争议。' })
})

test('另一管理员批准风险接受，重启保留时间线历史', async ({ page }) => {
  const events = [{ id: 1, action: 'request_acceptance', actor: 'business', occurred_at: '2026-11-01T10:00:00Z', from_status: '处理中', to_status: '待风险接受', snapshot: { acceptance_reason: '历史申请原因', residual_risk: '仍有回款争议', resolution: '每日跟进履约' } }]
  const updates = await prepare(page, { role: 'admin', username: 'review-admin', item: { status: '待风险接受', submitted_by: 'business', acceptance_reason: '历史申请原因', residual_risk: '仍有回款争议', resolution: '每日跟进履约', events, can_accept: true, can_reopen: true } })
  await page.getByLabel('复核意见', { exact: true }).fill('批准本次风险接受，持续跟进剩余风险。')
  await page.getByRole('button', { name: '批准风险接受' }).click()
  await expect(page.getByText('RC201 · 已接受风险')).toBeVisible()
  await expect(page.getByText('已接受风险不代表风险已消除，保留剩余风险。')).toBeVisible()
  await expect(page.getByRole('button', { name: '通过并闭环' })).toHaveCount(0)
  await page.getByRole('button', { name: '重新开启', exact: true }).click()
  await page.getByRole('button', { name: '确认重新开启' }).click()
  await expect(page.getByText('RC201 · 待处理')).toBeVisible()
  await expect(page.getByText('申请风险接受', { exact: true })).toBeVisible()
  await page.getByText('查看本次记录').click()
  await expect(page.getByText('历史申请原因', { exact: true })).toBeVisible()
  expect(updates.map(update => update.status)).toEqual(['已接受风险', '待处理'])
  expect(updates.map(update => update.version)).toEqual([1, 2])
})

test('版本冲突保留本次结果与材料选择，可刷新后重试', async ({ page }) => {
  const updates = await prepare(page, { fail: true })
  await page.getByLabel('整改结果 必填').fill('已经完成具体修改。')
  await page.getByLabel('修改后条款', { exact: true }).fill('修订后的责任条款。')
  await page.getByRole('combobox', { name: '关联整改材料' }).click()
  await page.getByRole('option', { name: /修订稿.docx/ }).click()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '提交复核', exact: true }).click()
  await expect(page.getByText('任务已被其他人员更新，请刷新后重试')).toBeVisible()
  await expect(page.getByLabel('整改结果 必填')).toHaveValue('已经完成具体修改。')
  await expect(page.getByLabel('修改后条款', { exact: true })).toHaveValue('修订后的责任条款。')
  expect(updates[0]).toMatchObject({ version: 1, evidence_contract_ids: [9] })
})

test('上传证据沿用来源部门且不会自动触发模型审查', async ({ page }) => {
  await prepare(page, { item: { department: '研发部' } })
  const modelRequests: string[] = []
  page.on('request', request => { if (/\/audit$/.test(new URL(request.url()).pathname)) modelRequests.push(request.url()) })
  let parsed = false
  await page.route('**/api/v1/contracts/9/parse', route => {
    parsed = true
    return route.fulfill({ json: { contract_id: 9, text_length: 20, status: 'parsed', elements: {} } })
  })
  await page.route('**/api/v1/contracts/upload?**', async route => {
    expect(new URL(route.request().url()).searchParams.get('department')).toBe('研发部')
    await route.fulfill({ json: { id: 9, filename: '修订稿.docx', status: 'uploaded' } })
  })
  await page.getByLabel('上传修订版或凭证').setInputFiles({ name: '修订稿.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: Buffer.from('测试材料') })
  await expect(page.getByText('材料已上传并关联，可核对原文；如需模型审查请主动进入审查页。')).toBeVisible()
  await expect(page.getByRole('button', { name: '查看材料原文', exact: true })).toBeVisible()
  expect(parsed).toBe(true)
  expect(modelRequests).toHaveLength(0)
})

test('材料解析失败保留关联，通过原文入口重试后可读', async ({ page }) => {
  await prepare(page, { item: { department: '研发部' } })
  await page.route('**/api/v1/contracts/upload?**', route => route.fulfill({ json: { id: 9, filename: '修订稿.docx', status: 'uploaded' } }))
  let parsed = false
  let fail = true
  await page.route('**/api/v1/contracts/9/parse', route => {
    if (fail) return route.fulfill({ status: 503, json: { detail: '解析暂不可用' } })
    parsed = true
    return route.fulfill({ json: { contract_id: 9, text_length: 8, status: 'parsed', elements: {} } })
  })
  await page.route('**/api/v1/contracts/9/document', route => route.fulfill({ json: {
    contract_id: 9, text: parsed ? '修订后的真实条款正文。' : '', message: '暂无有效解析正文，请完成合同解析后再查看。',
  } }))
  await page.getByLabel('上传修订版或凭证').setInputFiles({ name: '修订稿.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: Buffer.from('测试材料') })
  await expect(page.getByText(/材料已上传并关联，但正文解析失败/)).toBeVisible()
  await page.getByRole('button', { name: '查看材料原文', exact: true }).click()
  const reader = page.getByRole('dialog', { name: /合同原文与风险批注/ })
  await reader.getByRole('button', { name: '解析材料正文', exact: true }).click()
  await expect(reader.getByText('解析暂不可用', { exact: true })).toBeVisible()
  fail = false
  await reader.getByRole('button', { name: '解析材料正文', exact: true }).click()
  await expect(reader.getByRole('region', { name: '完整解析正文' })).toContainText('修订后的真实条款正文。')
})

test('高风险升级登记携带本次理由和版本', async ({ page }) => {
  const updates = await prepare(page)
  await page.getByRole('button', { name: '登记升级处理', exact: true }).click()
  const prompt = page.getByRole('dialog', { name: '登记升级处理' })
  await prompt.locator('textarea').fill('即将到期，需要跨部门协调补充协议。')
  await prompt.getByRole('button', { name: '登记升级', exact: true }).click()
  await expect(page.getByText('已登记升级处理', { exact: true })).toBeVisible()
  expect(updates[0]).toEqual({ reason: '即将到期，需要跨部门协调补充协议。', version: 1 })
})

for (const width of [375, 1280]) {
  test(`整改列表与详情抽屉无横向溢出 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await prepare(page, { item: { evidence: [{ contract_id: 9, filename: '长文件名'.repeat(20) + '.pdf', content_sha256: 'abc'.repeat(22) }] } })
    const drawer = page.locator('.rectify-drawer .el-drawer__body')
    await expect.poll(() => drawer.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.getByRole('button', { name: '关闭', exact: true }).click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}

test('空任务和加载失败提供明确提示', async ({ page }) => {
  await prepare(page, { empty: true })
  await expect(page.getByText('当前范围暂无整改任务')).toBeVisible()
  await page.route('**/api/v1/rectifications', route => route.fulfill({ status: 503, json: { detail: '整改列表暂时不可用' } }))
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(page.getByText('整改任务加载失败')).toBeVisible()
  await expect(page.getByRole('button', { name: '重新加载', exact: true })).toBeVisible()
})

test('业务责任人不能验收自己的整改，原文定位状态明确显示', async ({ page }) => {
  await prepare(page, { item: { status: '待复核', submitted_by: 'business' } })
  await expect(page.getByRole('button', { name: '通过并闭环' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '退回整改' })).toHaveCount(0)
  await expect(page.getByText('原文尚未定位核实')).toBeVisible()
  await expect(page.getByText('由其他法务、财务或管理员独立验收')).toBeVisible()
})

test('历史计划缺项必须补齐，表单保留并显示必填校验', async ({ page }) => {
  await prepare(page, { role: 'legal', username: 'legal', item: { owner: '', acceptance_criteria: '', contract_stage: 'unknown' } })
  await page.getByRole('button', { name: '补齐或调整计划' }).click()
  await page.getByRole('button', { name: '保存整改计划' }).click()
  await expect(page.getByText('请选择已注册的责任人')).toBeVisible()
  await expect(page.getByText('请填写验收条件')).toBeVisible()
})

test('保存现有任务计划只传计划白名单字段，保留版本控制', async ({ page }) => {
  const updates = await prepare(page, { role: 'legal', username: 'legal' })
  await page.getByRole('button', { name: '补齐或调整计划' }).click()
  const dialog = page.getByRole('dialog', { name: '整改计划', exact: true })
  await dialog.getByLabel('整改措施', { exact: true }).fill('请业务补齐具体赔偿范围并上传修订版。')
  await dialog.getByRole('button', { name: '保存整改计划' }).click()
  await expect(dialog).not.toBeVisible()
  expect(Object.keys(updates[0] ?? {}).sort()).toEqual(['owner', 'collaborators', 'due', 'note', 'acceptance_criteria', 'contract_stage', 'handling_method', 'version'].sort())
  expect(updates[0]).toMatchObject({ version: 1, owner: 'business' })
})

for (const [stage, expected] of [['unknown', 'revision'], ['signed', 'supplement']] as const) {
  test(`历史空处理方式补齐为有效默认值 ${stage}`, async ({ page }) => {
    const updates = await prepare(page, { role: 'legal', username: 'legal', item: { handling_method: '', contract_stage: stage } })
    await page.getByRole('button', { name: '补齐或调整计划' }).click()
    const dialog = page.getByRole('dialog', { name: '整改计划', exact: true })
    await dialog.getByRole('button', { name: '保存整改计划' }).click()
    await expect(dialog).not.toBeVisible()
    expect(updates[0]).toMatchObject({ handling_method: expected, contract_stage: stage, due: baseItem.due })
  })
}

test('确认风险后明确计划，创建失败保留表单并重试且不重复确认', async ({ page }) => {
  let confirmations = 0
  let creations = 0
  const risk = { id: 42, agent: 'legal', level: 'high', category: '违约责任约定不明', original_text: '违约另行协商', risk_reason: '赔偿范围不明', basis: '合同约定', suggestion: '补充赔偿范围', confidence: 85, tier: 'red', review_status: 'pending', rag_sources: [] }
  await page.addInitScript(() => {
    localStorage.setItem('token', 'audit-closure-test')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '研发部')
    localStorage.setItem('qijian-completed-audit', JSON.stringify({ owner: 'legal', contractId: 8, filename: '技术服务合同.pdf', jobId: 88 }))
  })
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith('/contracts/8/audit-status')) body = { contract_id: 8, job_id: 88, status: 'done', risk_count: 1, cross_checks: [] }
    else if (path.endsWith('/contracts/8/risks')) body = [risk]
    else if (path.endsWith('/risks/42/status')) { confirmations++; body = { risk_id: 42, review_status: 'confirmed' } }
    else if (path.endsWith('/rectifications/participants')) body = [{ id: 1, username: 'business', role: 'business', department: '研发部' }]
    else if (path.endsWith('/rectifications') && route.request().method() === 'POST') {
      creations++
      if (creations === 1) return void await route.fulfill({ status: 500, json: { detail: '创建服务暂时不可用' } })
      body = { ...baseItem, ...route.request().postDataJSON(), id: 'RC202', status: '待处理' }
    } else if (path.endsWith('/runtime/status')) body = { status: 'online' }
    else if (path.endsWith('/handoffs')) body = { state: 'NO_DATA', items: [] }
    await route.fulfill({ json: body })
  })
  await page.goto('/audit')
  await page.getByRole('button', { name: '复核风险：违约责任约定不明' }).click()
  await page.getByRole('button', { name: '确认并生成整改项', exact: true }).click()
  await page.getByPlaceholder('至少说明你核对了什么以及为何确认').fill('已核对违约条款，赔偿范围确实缺失。')
  await page.getByRole('button', { name: '提交确认', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '整改计划', exact: true })
  await expect(dialog).toBeVisible()
  expect(creations).toBe(0)
  await dialog.getByRole('combobox', { name: '责任人', exact: true }).click()
  await page.getByRole('option', { name: /business/ }).click()
  await dialog.getByRole('combobox', { name: '截止日期' }).fill('2026-11-20')
  await dialog.getByRole('combobox', { name: '截止日期' }).press('Tab')
  await dialog.getByLabel('验收条件', { exact: true }).fill('违约情形、违约金和赔偿范围均已明确。')
  await dialog.getByRole('button', { name: '保存整改计划' }).click()
  await expect(dialog.getByText(/风险已确认，但整改任务未生成/)).toBeVisible()
  await expect(dialog.getByLabel('验收条件', { exact: true })).toHaveValue('违约情形、违约金和赔偿范围均已明确。')
  await dialog.getByRole('button', { name: '保存整改计划' }).click()
  await expect(dialog).not.toBeVisible()
  expect(confirmations).toBe(1)
  expect(creations).toBe(2)
})
