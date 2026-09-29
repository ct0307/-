import { expect, test, type Page } from '@playwright/test'

const handoff = { contract_id: 41, filename: '交接采购合同.docx', contract_type: '采购合同', audit_job_id: null,
  department: '采购中心', contract_status: 'parsed', state: 'accepted', version: 2, assigned_to: 2,
  reason: '', can_submit: false, can_accept: false, can_return: true, can_review: true }

async function setup(page: Page, role = 'legal') {
  await page.addInitScript((role) => {
    localStorage.setItem('token', 'fixture-token')
    localStorage.setItem('role', role)
    localStorage.setItem('username', `${role}-real-user`)
    localStorage.setItem('department', '采购中心')
    localStorage.setItem('authorized_departments', '["采购中心"]')
  }, role)
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith('/runtime/status')) body = { status: 'degraded', processing_mode: 'rules_fallback', checked_at: '2026-09-29T10:00:00Z' }
    if (path.endsWith('/handoffs')) body = { state: 'READY', items: [{ ...handoff, can_review: role === 'legal', can_return: role === 'legal', can_submit: role === 'business', state: role === 'business' ? 'draft' : 'accepted' }] }
    if (path.endsWith('/contracts/41/audit')) body = { contract_id: 41, job_id: 71, status: 'review_required', risk_count: 0, requires_review: true }
    await route.fulfill({ json: body })
  })
}

test('法务从接收合同直接发起审查，使用服务端合同类型', async ({ page }) => {
  await setup(page)
  await page.goto('/audit')
  await expect(page.getByText('交接采购合同.docx', { exact: true })).toBeVisible()
  const request = page.waitForRequest(r => r.url().endsWith('/contracts/41/audit') && r.method() === 'POST')
  await page.getByRole('button', { name: '发起审查', exact: true }).click()
  expect((await request).postDataJSON().contract_type).toBe('采购合同')
  await expect(page.getByText('已打开交接合同的审查结果', { exact: true })).toBeVisible()
})

test('业务仅显示交接入口，真实身份及窄屏布局正常', async ({ page }) => {
  await setup(page, 'business')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/audit')
  await expect(page.getByRole('button', { name: '提交法务审查', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '请通过合同交接提交法务审查', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '发起审查', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('交接列表区分空数据、无授权和加载失败并可重试', async ({ page }) => {
  await setup(page)
  let state = 'NO_DATA'
  let fail = false
  let malformed = false
  await page.route('**/api/v1/handoffs', route => fail
    ? route.fulfill({ status: 500, json: { detail: '测试故障' } })
    : route.fulfill({ json: malformed ? {} : { state, items: [] } }))
  await page.goto('/audit')
  await expect(page.getByText('暂无可交接合同，请先上传并确认类型')).toBeVisible()
  state = 'NO_AUTH_SCOPE'
  await page.getByRole('button', { name: '刷新交接列表' }).click()
  await expect(page.getByText('暂无授权部门，请联系管理员配置')).toBeVisible()
  fail = true
  await page.getByRole('button', { name: '刷新交接列表' }).click()
  await expect(page.getByText('交接列表加载失败，请重试')).toBeVisible()
  fail = false
  malformed = true
  await page.getByRole('button', { name: '刷新交接列表' }).click()
  await expect(page.getByText('交接列表加载失败，请重试')).toBeVisible()
  malformed = false
  await page.getByRole('button', { name: '刷新交接列表' }).click()
  await expect(page.getByText('暂无授权部门，请联系管理员配置')).toBeVisible()
})
