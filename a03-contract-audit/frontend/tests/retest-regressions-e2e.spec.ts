import { expect, test, type Page } from '@playwright/test'

async function prepare(page: Page, failed = false) {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'admin')
    localStorage.setItem('username', 'admin')
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith('/dashboard/summary')) {
      if (failed) return route.fulfill({status:500, body:'{}', contentType:'application/json'})
      body = {total_contracts:5,total_risks:0,review_status:{},contract_status:{parsed:5},level_distribution:{},category_distribution:[],agent_distribution:{}}
    }
    if (path.endsWith('/contracts')) body = [{id:'C0001',name:'待审测试.txt',type:'采购合同',submitter:'admin',time:new Date().toISOString(),level:'低风险',riskCount:0,status:'未审查'}]
    if (path.endsWith('/runtime/status')) body = {status:'online'}
    await route.fulfill({body:JSON.stringify(body),contentType:'application/json'})
  })
}

test('工作台不把导入和未审查标为完成或合规', async ({page}) => {
  await prepare(page)
  await page.goto('/dashboard')
  await expect(page.getByText('累计导入合同', {exact:true})).toBeVisible()
  await expect(page.getByText('风险复核完成率', {exact:true})).toBeVisible()
  await expect(page.getByText('「待审测试.txt」已导入，待审查', {exact:true})).toBeVisible()
  await expect(page.locator('.dash').getByText('刚刚', {exact:true})).toBeVisible()
})

test('390宽度侧栏默认完全隐藏，开关后主区保持可见', async ({page}) => {
  await page.setViewportSize({width:390,height:844})
  await prepare(page)
  await page.goto('/audit')
  await expect(page.getByText('收件箱为空', {exact:true})).toBeVisible()
  await expect.poll(async () => (await page.locator('#app-sidebar').boundingBox())!.x + (await page.locator('#app-sidebar').boundingBox())!.width).toBeLessThanOrEqual(1)
  await page.getByRole('button', {name:'打开导航菜单'}).click()
  await expect(page.getByRole('menuitem', {name:'工作台',exact:true})).toBeVisible()
  await page.keyboard.press('Escape')
  await expect.poll(async () => (await page.locator('#app-sidebar').boundingBox())!.x + (await page.locator('#app-sidebar').boundingBox())!.width).toBeLessThanOrEqual(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('工作台请求失败显示重试且不展示假统计', async ({page}) => {
  await prepare(page,true)
  await page.goto('/dashboard')
  await expect(page.getByText('看板加载失败',{exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'重新加载'})).toBeVisible()
  await expect(page.locator('.kpi-card')).toHaveCount(0)
})

test('桌面切到手机并等待动画后侧栏隐藏', async ({page}) => {
  await prepare(page)
  await page.setViewportSize({width:1440,height:900})
  await page.goto('/audit')
  await expect(page.getByText('收件箱为空',{exact:true})).toBeVisible()
  await page.setViewportSize({width:390,height:844})
  await expect.poll(async () => (await page.locator('#app-sidebar').boundingBox())!.x + (await page.locator('#app-sidebar').boundingBox())!.width).toBeLessThanOrEqual(1)
  await expect(page.getByRole('button',{name:'打开导航菜单'})).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
