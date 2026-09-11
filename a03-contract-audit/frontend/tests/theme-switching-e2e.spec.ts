import { expect, test, type Page } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 backend 和 frontend 后设置 E2E_BASE_URL')

async function login(page: Page) {
  await page.goto(`${baseUrl}/login`)
  await page.locator('input[name="username"]').fill('admin')
  await page.locator('input[name="password"]').fill('admin123')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
}

async function chooseTheme(page: Page, label: string) {
  await page.getByRole('button', { name: '切换外观' }).click()
  await page.getByRole('menuitem', { name: new RegExp(label) }).click()
}

test('defaults to dossier and persists a manual theme', async ({ page }) => {
  await page.goto(`${baseUrl}/login`)
  await page.evaluate(() => localStorage.removeItem('qijian-theme-mode'))
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dossier')

  await page.locator('input[name="username"]').fill('admin')
  await page.locator('input[name="password"]').fill('admin123')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)

  await chooseTheme(page, '深灰审阅')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect.poll(() => page.evaluate(() => localStorage.getItem('qijian-theme-mode'))).toBe('dark')

  await page.goto(`${baseUrl}/audit`)
  const primaryButtonUsesThemeForeground = await page
    .getByRole('button', { name: '审查就绪项' })
    .evaluate((button) => {
    const probe = document.createElement('span')
    probe.style.color = 'var(--on-brass)'
    document.body.appendChild(probe)
    const expected = getComputedStyle(probe).color
    probe.remove()
    return getComputedStyle(button).color === expected
    })
  expect(primaryButtonUsesThemeForeground).toBe(true)

  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
})

test('system mode follows color scheme without horizontal overflow', async ({ page }) => {
  const consoleIssues: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') consoleIssues.push(message.text())
  })

  await page.emulateMedia({ colorScheme: 'dark' })
  await login(page)
  await chooseTheme(page, '跟随系统')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')

  await page.emulateMedia({ colorScheme: 'light' })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '切换外观' }).click()
  await expect(page.getByRole('menuitem', { name: /卷宗主题/ })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
  expect(consoleIssues).toEqual([])
})
