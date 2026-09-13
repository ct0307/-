import { expect, test, type Route } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 frontend 后设置 E2E_BASE_URL')

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
}

test('admin can update the departments available to a legal user', async ({ page }) => {
  let savedDepartments: string[] = []
  await page.addInitScript(() => {
    localStorage.setItem('token', 'admin-token')
    localStorage.setItem('role', 'admin')
    localStorage.setItem('username', 'admin')
    localStorage.setItem('department', '管理部')
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T10:00:00Z' })
    }
    if (path.endsWith('/admin/access-matrix')) return fulfillJson(route, { modules: [], roles: [] })
    if (path.endsWith('/admin/audit-logs') || path.endsWith('/admin/llm-calls')) return fulfillJson(route, [])
    if (path.endsWith('/admin/lookups/department')) {
      return fulfillJson(route, [
        { id: 1, category: 'department', value: '法务部', sort_order: 0 },
        { id: 2, category: 'department', value: '采购中心', sort_order: 1 },
      ])
    }
    if (path.endsWith('/admin/lookups/contract_type')) return fulfillJson(route, [])
    if (path.endsWith('/admin/users/department-scopes')) {
      return fulfillJson(route, [{
        id: 7,
        username: 'legal',
        role: 'legal',
        department: '法务部',
        authorized_departments: ['法务部'],
      }])
    }
    if (path.endsWith('/admin/users/7/departments') && route.request().method() === 'PUT') {
      savedDepartments = (route.request().postDataJSON() as { departments: string[] }).departments
      return fulfillJson(route, {
        id: 7,
        username: 'legal',
        role: 'legal',
        department: '法务部',
        authorized_departments: savedDepartments,
      })
    }
    return fulfillJson(route, [])
  })

  await page.goto(`${baseUrl}/admin`)
  await page.getByRole('tab', { name: '基础配置' }).click()
  const legalRow = page.locator('.scope-row').filter({ hasText: 'legal' })
  await expect(legalRow.getByRole('combobox', { name: 'legal 的授权部门' })).toBeVisible()
  await legalRow.locator('.el-select__wrapper').click()
  await page.getByRole('option', { name: '采购中心' }).click()
  await page.getByRole('button', { name: '保存 legal 的部门授权' }).click()

  expect(savedDepartments.sort()).toEqual(['法务部', '采购中心'])
  await expect(page.getByText('授权部门已更新')).toBeVisible()
})

test('admin can restore a deleted contract draft from trash', async ({ page }) => {
  let restored = false
  await page.addInitScript(() => {
    localStorage.setItem('token', 'admin-token')
    localStorage.setItem('role', 'admin')
    localStorage.setItem('username', 'admin')
    localStorage.setItem('department', '管理部')
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, { status: 'online', checked_at: '2026-09-11T10:00:00Z' })
    }
    if (path.endsWith('/admin/access-matrix')) return fulfillJson(route, { modules: [], roles: [] })
    if (path.endsWith('/admin/audit-logs') || path.endsWith('/admin/llm-calls')) return fulfillJson(route, [])
    if (path.includes('/admin/lookups/') || path.endsWith('/admin/users/department-scopes')) return fulfillJson(route, [])
    if (path.endsWith('/admin/contract-trash')) {
      return fulfillJson(route, restored ? [] : [{
        batch_id: 42,
        item_id: 9,
        contract_id: 11,
        filename: '待恢复合同.txt',
        contract_type: '采购合同',
        department: '采购中心',
        deleted_at: '2026-09-10T10:00:00Z',
        expires_at: '2026-10-10T10:00:00Z',
        recoverable: true,
      }])
    }
    if (path.endsWith('/imports/42/items/9/restore') && route.request().method() === 'POST') {
      restored = true
      return fulfillJson(route, {})
    }
    return fulfillJson(route, [])
  })

  await page.goto(`${baseUrl}/admin`)
  await page.getByRole('tab', { name: '合同回收站' }).click()
  await expect(page.getByText('待恢复合同.txt')).toBeVisible()
  await page.getByRole('button', { name: '恢复 待恢复合同.txt' }).click()

  await expect(page.getByText('合同草稿已恢复')).toBeVisible()
  await expect(page.getByText('待恢复合同.txt')).toBeHidden()
})
