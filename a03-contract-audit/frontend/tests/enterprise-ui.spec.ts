import { expect, test } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 backend 和 frontend 后设置 E2E_BASE_URL')

test('enterprise delivery desktop, empty, error and mobile states', async ({ page }) => {
  const consoleErrors: string[] = []
  const unresolvedIconWarnings: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
    if (
      ['warning', 'error'].includes(message.type())
      && /Failed to resolve component: (Menu|Expand|Fold|ChatDotRound)/.test(message.text())
    ) {
      unresolvedIconWarnings.push(message.text())
    }
  })

  await page.goto(`${baseUrl}/login`)
  await page.waitForLoadState('networkidle')
  await page.locator('input[name="username"]').fill('admin')
  await page.locator('input[name="password"]').fill('admin123')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByRole('status')).toContainText(/检测中|正在重试|模型服务离线|状态待确认|DEEPSEEK|QWEN|.+ · .+/)
  await expect(page.getByText('契鉴', { exact: true }).first()).toBeVisible()

  await page.getByRole('menuitem', { name: '合同审查' }).click()
  await expect(page).toHaveURL(/\/audit$/)
  await expect(page.getByRole('heading', { name: '待审合同' })).toBeVisible()
  await expect(page.getByText('批量上传（支持50份以上）')).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('audit-desktop.png'), fullPage: true })
  expect(unresolvedIconWarnings).toEqual([])
  expect(consoleErrors).toEqual([])
  consoleErrors.length = 0

  await page.route('**/api/v1/runtime/status', (route) => route.abort())
  await page.reload()
  await page.waitForLoadState('networkidle')
  await expect(page.getByRole('status')).toContainText('正在重试')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await page.waitForLoadState('networkidle')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  const menuButton = page.getByRole('button', { name: '打开导航菜单' })
  await expect(menuButton).toBeVisible()
  await menuButton.click()
  await expect(page.getByRole('button', { name: '关闭导航菜单' })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: '合同审查' })).toBeVisible()
  await expect(page.locator('#app-sidebar')).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, 0)')
  await page.screenshot({ path: test.info().outputPath('audit-mobile.png'), fullPage: true })

  expect(consoleErrors.length).toBeGreaterThan(0)
  expect(consoleErrors.every((message) => message.includes('net::ERR_FAILED'))).toBe(true)
})
