import { expect, test, type Page } from '@playwright/test'

// 仅隔离 HTTP 边界，运行真实 Vue 页面、Axios 拦截器、Pinia 和路由。
async function prepare(page: Page) {
  let loginSequence = 0
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/login')) {
      const username = new URLSearchParams(route.request().postData() || '').get('username')
      await route.fulfill({ json: {
        access_token: `test-${username}-${++loginSequence}`, token_type: 'bearer', role: 'legal',
        username, department: '法务部', authorized_departments: ['法务部'],
      } })
    } else if (path.endsWith('/rectifications')) {
      const authorization = route.request().headers().authorization
      await route.fulfill({ json: authorization === 'Bearer test-legal-2' ? [{
        id: 'RC-NEW', contract: '用户乙合同', risk: '新会话风险', level: 'low',
        owner: '用户乙', status: '待处理', created: '2026-09-15', due: '2026-09-22', note: '',
      }] : [] })
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
  await expect(page.getByText('累计导入合同', { exact: true })).toBeVisible()
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
      const paths = ['/src/stores/audit-session.ts', '/src/stores/import-inbox.ts', '/src/stores/batch.ts', '/src/stores/rectify.ts', '/src/stores/notify.ts']
      const [auditModule, inboxModule, batchModule, rectifyModule, notifyModule] = await Promise.all(paths.map((path) => import(/* @vite-ignore */ path)))
      const audit = auditModule.useAuditSessionStore()
      audit.contractId = 42
      audit.filename = '测试合同.pdf'
      audit.elements = { party_a: '测试甲方' }
      const inbox = inboxModule.useImportInboxStore()
      inbox.selectedIds = [42]
      inbox.polling = true
      batchModule.useBatchStore().polling = true
      rectifyModule.useRectifyStore().items = [{
        id: 'RC-PRIVATE', contract: '用户甲合同', risk: '敏感风险', level: 'high', owner: '用户甲',
        status: '待处理', created: '2026-09-15', due: '2026-09-20', note: '内部说明',
      }]
      notifyModule.useNotifyStore().push('rectify', '用户甲通知', '敏感风险内容')
      localStorage.setItem('qijian-active-audit', '{}')
      localStorage.setItem('session-test-preference', '保留')
      document.documentElement.dataset.sessionMarker = '保持页面实例'
    })
    await page.route('**/api/v1/session-expired', (route) => route.fulfill({ status: 401, json: {} }))
    expect(await requestError(page, '/session-expired')).toBe('登录已过期，请重新登录')
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByPlaceholder('用户名')).toBeVisible()

    const state = await page.evaluate(async () => {
      const paths = ['/src/stores/auth.ts', '/src/stores/audit-session.ts', '/src/stores/import-inbox.ts', '/src/stores/batch.ts', '/src/stores/rectify.ts', '/src/stores/notify.ts', '/src/utils/session.ts', '/src/router/index.ts']
      const [authModule, auditModule, inboxModule, batchModule, rectifyModule, notifyModule, sessionModule, routerModule] = await Promise.all(paths.map((path) => import(/* @vite-ignore */ path)))
      const auth = authModule.useAuthStore()
      const audit = auditModule.useAuditSessionStore()
      const inbox = inboxModule.useImportInboxStore()
      await routerModule.default.push('/audit')
      return {
        authenticated: auth.isAuthenticated(), username: auth.username, departments: auth.authorizedDepartments,
        contractId: audit.contractId, elements: audit.elements, selectedIds: inbox.selectedIds,
        inboxPolling: inbox.polling, batchPolling: batchModule.useBatchStore().polling,
        rectifications: rectifyModule.useRectifyStore().items,
        notifications: notifyModule.useNotifyStore().items,
        keysCleared: Object.values(sessionModule.SESSION_KEYS).every((key) => localStorage.getItem(key as string) === null),
        preference: localStorage.getItem('session-test-preference'),
        marker: document.documentElement.dataset.sessionMarker,
        overflow: document.documentElement.scrollWidth > window.innerWidth,
      }
    })
    expect(state).toEqual({
      authenticated: false, username: '', departments: [], contractId: null, elements: null,
      selectedIds: [], inboxPolling: false, batchPolling: false, keysCleared: true,
      rectifications: [], notifications: [],
      preference: '保留', marker: '保持页面实例', overflow: false,
    })
    await expect(page).toHaveURL(/\/login$/)
    await page.screenshot({ path: testInfo.outputPath('expired-login.png'), fullPage: true })
    await login(page)
    await expect.poll(() => page.evaluate(async () => {
      const modulePath = '/src/stores/rectify.ts'
      const { useRectifyStore } = await import(/* @vite-ignore */ modulePath)
      return useRectifyStore().items[0]?.contract
    })).toBe('用户乙合同')
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
  expect(oldRequest.headers().authorization).toBe('Bearer test-legal-1')
  await page.evaluate(async () => {
    const modulePath = '/src/stores/auth.ts'
    const { useAuthStore } = await import(/* @vite-ignore */ modulePath)
    await useAuthStore().login('legal', 'test-password')
  })
  releaseResponse()
  await pending
  expect(await page.evaluate(() => localStorage.getItem('token'))).toBe('test-legal-2')
  await expect(page).toHaveURL(/\/dashboard$/)
})

test('旧会话迟到的成功响应不回写新会话状态', async ({ page }) => {
  await prepare(page)
  await login(page)
  let releaseResponses!: () => void
  const responsesReady = new Promise<void>((resolve) => { releaseResponses = resolve })
  await page.route('**/api/v1/rectifications', async (route) => {
    const authorization = route.request().headers().authorization
    if (authorization === 'Bearer test-legal-1') await responsesReady
    await route.fulfill({ json: [{
      id: authorization === 'Bearer test-legal-1' ? 'RC-OLD' : 'RC-NEW',
      contract: authorization === 'Bearer test-legal-1' ? '旧用户私有合同' : '新用户合同',
      risk: '会话隔离', level: 'low', owner: '法务', status: '待处理',
      created: '2026-09-15', due: '2026-09-22', note: '',
    }] })
  })
  await page.route('**/api/v1/contracts/upload**', (route) => route.fulfill({ json: {
    id: 7, filename: '旧会话合同.txt', contract_type: '采购合同', status: 'uploaded',
    created_at: '2026-09-15T00:00:00Z',
  } }))
  await page.route('**/api/v1/contracts/7/parse', async (route) => {
    await responsesReady
    await route.fulfill({ json: {
      contract_id: 7, elements: { party_a: '旧用户私有甲方' }, text_length: 20,
    } })
  })

  const oldRectifyRequest = page.waitForRequest('**/api/v1/rectifications')
  const oldParseRequest = page.waitForRequest('**/api/v1/contracts/7/parse')
  await page.evaluate(async () => {
    const rectifyModule = await import(/* @vite-ignore */ '/src/stores/rectify.ts')
    const auditModule = await import(/* @vite-ignore */ '/src/stores/audit-session.ts')
    const pendingWindow = window as typeof window & {
      oldRectifyLoad?: Promise<void>
      oldUpload?: Promise<unknown>
    }
    pendingWindow.oldRectifyLoad = rectifyModule.useRectifyStore().load(true)
    pendingWindow.oldUpload = auditModule.useAuditSessionStore().uploadAndParse(
      new File(['旧会话内容'], '旧会话合同.txt', { type: 'text/plain' }),
      '采购合同',
    )
  })
  await oldRectifyRequest
  await oldParseRequest
  await page.evaluate(async () => {
    const { useAuthStore } = await import(/* @vite-ignore */ '/src/stores/auth.ts')
    await useAuthStore().login('legal', 'test-password')
  })
  releaseResponses()
  await page.evaluate(async () => {
    const pendingWindow = window as typeof window & {
      oldRectifyLoad?: Promise<void>
      oldUpload?: Promise<unknown>
    }
    await Promise.all([pendingWindow.oldRectifyLoad, pendingWindow.oldUpload])
  })

  const staleState = await page.evaluate(async () => {
    const rectifyModule = await import(/* @vite-ignore */ '/src/stores/rectify.ts')
    const auditModule = await import(/* @vite-ignore */ '/src/stores/audit-session.ts')
    const audit = auditModule.useAuditSessionStore()
    return {
      rectifications: rectifyModule.useRectifyStore().items,
      contractId: audit.contractId,
      elements: audit.elements,
      uploadRecords: audit.uploadRecords,
    }
  })
  expect(staleState).toEqual({
    rectifications: [], contractId: null, elements: null, uploadRecords: [],
  })

  await page.evaluate(async () => {
    const { useRectifyStore } = await import(/* @vite-ignore */ '/src/stores/rectify.ts')
    await useRectifyStore().load(true)
  })
  expect(await page.evaluate(async () => {
    const { useRectifyStore } = await import(/* @vite-ignore */ '/src/stores/rectify.ts')
    return useRectifyStore().items[0]?.contract
  })).toBe('新用户合同')
})
