import { expect, test, type Page, type Route } from '@playwright/test'

interface MockOptions {
  profileListFails?: boolean
  updateConflicts?: boolean
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function mockAdminApi(page: Page, options: MockOptions = {}) {
  let listFails = options.profileListFails ?? false
  let profileVersion = 3
  let updateConflicts = options.updateConflicts ?? false
  let updateBody: Record<string, unknown> | null = null

  await page.addInitScript(() => {
    localStorage.setItem('token', 'admin-token')
    localStorage.setItem('role', 'admin')
    localStorage.setItem('username', 'admin')
    localStorage.setItem('department', '管理部')
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-16T10:00:00Z' })
    }
    if (path.endsWith('/admin/access-matrix')) {
      return fulfillJson(route, { modules: [], roles: [] })
    }
    if (
      path.endsWith('/admin/audit-logs')
      || path.endsWith('/admin/llm-calls')
      || path.endsWith('/admin/users/department-scopes')
      || path.endsWith('/admin/contract-trash')
    ) {
      return fulfillJson(route, [])
    }
    if (path.endsWith('/admin/lookups/contract_type/profiles') && method === 'GET') {
      if (listFails) {
        return fulfillJson(route, { detail: '规则服务暂不可用' }, 500)
      }
      return fulfillJson(route, [
        {
          lookup_item_id: 10,
          value: '采购合同',
          aliases: ['采购'],
          positive_signals: ['采购', '供货'],
          negative_signals: [],
          enabled: true,
          version: profileVersion,
        },
        {
          lookup_item_id: 11,
          value: '居间合同',
          aliases: [],
          positive_signals: [],
          negative_signals: [],
          enabled: false,
          version: 1,
        },
      ])
    }
    if (path.endsWith('/admin/lookups/department')) return fulfillJson(route, [])
    if (path.endsWith('/admin/lookups/contract_type')) {
      return fulfillJson(route, [
        { id: 10, category: 'contract_type', value: '采购合同', sort_order: 0 },
        { id: 11, category: 'contract_type', value: '居间合同', sort_order: 1 },
      ])
    }
    if (path.endsWith('/admin/lookups/10/profile') && method === 'PUT') {
      updateBody = route.request().postDataJSON() as Record<string, unknown>
      if (updateConflicts) {
        updateConflicts = false
        profileVersion = 4
        return fulfillJson(route, { detail: '规则已被更新，请刷新后重试' }, 409)
      }
      profileVersion += 1
      return fulfillJson(route, {
        lookup_item_id: 10,
        value: '采购合同',
        ...updateBody,
        version: profileVersion,
      })
    }
    return fulfillJson(route, [])
  })

  return {
    getUpdateBody: () => updateBody,
    recoverProfileList: () => { listFails = false },
  }
}

async function openConfig(page: Page) {
  await page.goto('/admin')
  await page.getByRole('tab', { name: '基础配置' }).click()
}

test('admin edits and normalizes a contract type profile', async ({ page }) => {
  const mock = await mockAdminApi(page)
  await openConfig(page)

  await page.getByRole('button', { name: '编辑采购合同规则' }).click()
  await expect(page.getByRole('dialog', { name: '采购合同分类规则' })).toBeVisible()
  await page.getByLabel('正向信号').fill('采购\n供货\n设备\n采购')
  await page.getByRole('button', { name: '保存规则' }).click()

  expect(mock.getUpdateBody()).toEqual({
    aliases: ['采购'],
    positive_signals: ['采购', '供货', '设备'],
    negative_signals: [],
    enabled: true,
    version: 3,
  })
  await expect(page.getByText('分类规则已保存')).toBeVisible()
})

test('empty profile opens as an editable empty state', async ({ page }) => {
  await mockAdminApi(page)
  await openConfig(page)

  await page.getByRole('button', { name: '编辑居间合同规则' }).click()

  await expect(page.getByRole('dialog', { name: '居间合同分类规则' })).toBeVisible()
  await expect(page.getByLabel('别名')).toHaveValue('')
  await expect(page.getByLabel('正向信号')).toHaveValue('')
  await expect(page.getByLabel('负向信号')).toHaveValue('')
})

test('profile list failure is recoverable without hiding contract types', async ({ page }) => {
  const mock = await mockAdminApi(page, { profileListFails: true })
  await openConfig(page)

  await expect(page.getByText('规则加载失败')).toBeVisible()
  await expect(page.getByText('采购合同', { exact: true })).toBeVisible()
  mock.recoverProfileList()
  await page.getByRole('button', { name: '重新加载分类规则' }).click()

  await expect(page.getByRole('button', { name: '编辑采购合同规则' })).toBeVisible()
})

test('409 keeps the drawer open and refreshes the version for retry', async ({ page }) => {
  const mock = await mockAdminApi(page, { updateConflicts: true })
  await openConfig(page)
  await page.getByRole('button', { name: '编辑采购合同规则' }).click()
  await page.getByLabel('正向信号').fill('采购\n设备')
  await page.getByRole('button', { name: '保存规则' }).click()

  await expect(page.getByText('规则已被更新，请刷新后重试')).toBeVisible()
  await expect(page.getByRole('dialog', { name: '采购合同分类规则' })).toBeVisible()
  await page.getByRole('button', { name: '保存规则' }).click()
  expect(mock.getUpdateBody()?.version).toBe(4)
})

test('profile editor has no horizontal overflow at 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockAdminApi(page)
  await openConfig(page)
  await page.getByRole('button', { name: '编辑采购合同规则' }).click()

  await expect(page.getByRole('dialog', { name: '采购合同分类规则' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
