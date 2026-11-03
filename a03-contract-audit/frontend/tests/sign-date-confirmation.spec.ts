import { expect, test, type Page } from '@playwright/test'

async function setup(page: Page, options: { empty?: boolean; fail?: boolean; restored?: boolean } = {}) {
  await page.addInitScript((restored) => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('department', '法务部')
    if (restored) localStorage.setItem('qijian-completed-audit', JSON.stringify({ owner: 'legal', contractId: 91, jobId: 12, filename: '日期测试.txt' }))
  }, options.restored ?? false)
  let value = { contract_id: 91, contract_type: '采购合同', sign_date: options.empty ? '' : '2026年10月01日', confirmed: false, confirmed_by: null as number | null, confirmed_by_name: null as string | null, confirmed_at: null as string | null, audit_invalidated: false }
  const submissions: unknown[] = []
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/audit') && route.request().method() === 'POST') {
      expect(route.request().postDataJSON().contract_type).toBe('采购合同')
      value.audit_invalidated = false
      return route.fulfill({ json: { contract_id: 91, job_id: 13, status: 'done', cross_checks: [] } })
    }
    if (path.endsWith('/sign-date')) {
      if (route.request().method() === 'PATCH') {
        submissions.push(route.request().postDataJSON())
        if (options.fail) return route.fulfill({ status: 409, json: { detail: '合同正在处理，请完成当前任务后确认签订日期' } })
        value = { ...value, sign_date: route.request().postDataJSON().sign_date, confirmed: true, confirmed_by: 1, confirmed_by_name: 'legal', confirmed_at: '2026-11-02T10:00:00Z', audit_invalidated: options.restored ?? false }
      }
      return route.fulfill({ json: value })
    }
    if (path.endsWith('/audit-status')) return route.fulfill({ json: { contract_id: 91, job_id: 12, status: 'done', cross_checks: [] } })
    if (path.endsWith('/imports/42')) return route.fulfill({ json: { id: 42, status: 'needs_attention', total: 1, ready: 0, failed: 0, items: [{ id: 7, contract_id: 91, filename: '日期测试.txt', status: 'awaiting_confirmation', suggested_type: '采购合同', confirmed_type: '', confidence: 0.9, department: '法务部', requires_review: false }] } })
    return route.fulfill({ json: [] })
  })
  await page.goto(options.restored ? '/audit' : '/audit?import=42')
  return submissions
}

test('自动日期需主动确认，校正后刷新保留确认人和日期', async ({ page }) => {
  const submissions = await setup(page)
  await expect(page.getByText('未确认 · 法规适用时点未知', { exact: true })).toBeVisible()
  expect(submissions).toHaveLength(0)
  await page.getByLabel('签订日期', { exact: true }).fill('2026-10-02')
  await page.getByRole('button', { name: '确认签订日期', exact: true }).click()
  await expect(page.getByText('已确认 · legal', { exact: false })).toBeVisible()
  expect(submissions).toEqual([{ sign_date: '2026-10-02' }])
  await page.reload()
  await expect(page.getByLabel('签订日期', { exact: true })).toHaveValue('2026-10-02')
  await expect(page.getByText('已确认 · legal', { exact: false })).toBeVisible()
})

test('日期缺失显示空状态；移动端无溢出；失败保留校正值且不确认', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await setup(page, { empty: true, fail: true })
  await expect(page.getByText('未检出签订日期，请核对原文后填写', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认签订日期', exact: true })).toBeDisabled()
  await page.getByLabel('签订日期', { exact: true }).fill('2026-10-02')
  await page.getByRole('button', { name: '确认签订日期', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '合同正在处理' })).toBeVisible()
  await expect(page.getByLabel('签订日期', { exact: true })).toHaveValue('2026-10-02')
  await expect(page.getByText('未确认 · 法规适用时点未知', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
  await page.screenshot({ path: test.info().outputPath('sign-date-mobile-error.png'), fullPage: true })
})

test('恢复完成结果也提供日期入口，确认后旧结果提示失效', async ({ page }) => {
  await setup(page, { restored: true })
  await expect(page.getByRole('heading', { name: '日期测试.txt', exact: true })).toBeVisible()
  await page.getByLabel('签订日期', { exact: true }).fill('2026-10-02')
  await page.getByRole('button', { name: '确认签订日期', exact: true }).click()
  await expect(page.getByText('签订日期已确认或变更，请重新审查；历史结果不能用于当前终审。', { exact: true })).toBeVisible()
  await expect(page.getByText('机器处理完成', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '按确认日期重新审查', exact: true }).click()
  await expect(page.getByText('机器处理完成', { exact: true })).toBeVisible()
  await expect(page.getByText('签订日期已确认或变更，请重新审查；历史结果不能用于当前终审。', { exact: true })).toHaveCount(0)
})
