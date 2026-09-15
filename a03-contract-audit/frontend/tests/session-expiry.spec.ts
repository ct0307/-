import { expect, test, type Page } from '@playwright/test'

// 仅隔离 HTTP 边界，运行真实 Vue 页面、Axios 拦截器、Pinia 和路由。
async function prepare(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/login')) {
      const username = new URLSearchParams(route.request().postData() || '').get('username')
      await route.fulfill({ json: {
        access_token: `test-${username}`, token_type: 'bearer', role: 'legal',
        username, department: '法务部', authorized_departments: ['法务部'],
      } })
    } else if (path.endsWith('/dashboard/summary')) {
      await route.fulfill({ json: {
        total_contracts: 0, total_risks: 0, level_distribution: {},
        category_distribution: [], contract_status: {}, review_status: {}, agent_distribution: {},
      } })
    } else {
      await route.fulfill({ json: [] })
    }
  })
  await page.goto('/login')
  await expect(page.getByPlaceholder('用户名')).toBeVisible()
}

async function login(page: Page) {
  await page.getByPlaceholder('用户名').fill('legal')
  await page.getByPlaceholder('密码').fill('test-password')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByText('累计审查合同', { exact: true })).toBeVisible()
}

async function requestError(page: Page, path: string) {
  return page.evaluate(async (url) => {
    const modulePath = '/src/api/client.ts'
    const { default: client } = await import(/* @vite-ignore */ modulePath)
    try { await client.get(url); return '' }
    catch (error) { return (error as Error).message }
  }, path)
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`401 清空持久化与内存会话并允许重新登录 ${viewport.width}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await prepare(page)
    await page.getByRole('button', { name: '登 录' }).click()
    await expect(page.getByText('请输入用户名', { exact: true })).toBeVisible()
    await expect(page.getByText('请输入密码', { exact: true })).toBeVisible()
    await login(page)

    await page.route('**/api/v1/session-forbidden', (route) => route.fulfill({ status: 403, json: {} }))
    expect(await requestError(page, '/session-forbidden')).toBe('权限不足，无法执行此操作')
    await expect(page).toHaveURL(/\/dashboard$/)

    await page.evaluate(async () => {
      const paths = ['/src/stores/audit-session.ts', '/src/stores/import-inbox.ts', '/src/stores/batch.ts']
      const [auditModule, inboxModule, batchModule] = await Promise.all(paths.map((path) => import(/* @vite-ignore */ path)))
      const audit = auditModule.useAuditSessionStore()
      audit.contractId = 42
      audit.filename = '测试合同.pdf'
      audit.elements = { party_a: '测试甲方' }
      const inbox = inboxModule.useImportInboxStore()
      inbox.selectedIds = [42]
      inbox.polling = true
      batchModule.useBatchStore().polling = true
      localStorage.setItem('qijian-active-audit', '{}')
      localStorage.setItem('session-test-preference', '保留')
      document.documentElement.dataset.sessionMarker = '保持页面实例'
    })
    await page.route('**/api/v1/session-expired', (route) => route.fulfill({ status: 401, json: {} }))
    expect(await requestError(page, '/session-expired')).toBe('登录已过期，请重新登录')
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByPlaceholder('用户名')).toBeVisible()

    const state = await page.evaluate(async () => {
      const paths = ['/src/stores/auth.ts', '/src/stores/audit-session.ts', '/src/stores/import-inbox.ts', '/src/stores/batch.ts', '/src/utils/session.ts', '/src/router/index.ts']
      const [authModule, auditModule, inboxModule, batchModule, sessionModule, routerModule] = await Promise.all(paths.map((path) => import(/* @vite-ignore */ path)))
      const auth = authModule.useAuthStore()
      const audit = auditModule.useAuditSessionStore()
      const inbox = inboxModule.useImportInboxStore()
      await routerModule.default.push('/audit')
      return {
        authenticated: auth.isAuthenticated(), username: auth.username, departments: auth.authorizedDepartments,
        contractId: audit.contractId, elements: audit.elements, selectedIds: inbox.selectedIds,
        inboxPolling: inbox.polling, batchPolling: batchModule.useBatchStore().polling,
        keysCleared: Object.values(sessionModule.SESSION_KEYS).every((key) => localStorage.getItem(key as string) === null),
        preference: localStorage.getItem('session-test-preference'),
        marker: document.documentElement.dataset.sessionMarker,
        overflow: document.documentElement.scrollWidth > window.innerWidth,
      }
    })
    expect(state).toEqual({
      authenticated: false, username: '', departments: [], contractId: null, elements: null,
      selectedIds: [], inboxPolling: false, batchPolling: false, keysCleared: true,
      preference: '保留', marker: '保持页面实例', overflow: false,
    })
    await expect(page).toHaveURL(/\/login$/)
    await page.screenshot({ path: testInfo.outputPath('expired-login.png'), fullPage: true })
    await login(page)
    expect(pageErrors).toEqual([])
  })
}

test('旧请求迟到的 401 不清理新登录会话', async ({ page }) => {
  await prepare(page)
  await login(page)
  let releaseResponse!: () => void
  const responseReady = new Promise<void>((resolve) => { releaseResponse = resolve })
  await page.route('**/api/v1/session-old', async (route) => {
    await responseReady
    await route.fulfill({ status: 401, json: {} })
  })
  const requested = page.waitForRequest('**/api/v1/session-old')
  const pending = requestError(page, '/session-old')
  const oldRequest = await requested
  expect(oldRequest.headers().authorization).toBe('Bearer test-legal')
  await page.evaluate(async () => {
    const modulePath = '/src/stores/auth.ts'
    const { useAuthStore } = await import(/* @vite-ignore */ modulePath)
    await useAuthStore().login('new-user', 'test-password')
  })
  releaseResponse()
  await pending
  expect(await page.evaluate(() => localStorage.getItem('token'))).toBe('test-new-user')
  await expect(page).toHaveURL(/\/dashboard$/)
})
