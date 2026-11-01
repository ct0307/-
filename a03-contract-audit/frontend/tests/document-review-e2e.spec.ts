import { expect, test, type Page } from '@playwright/test'

const text = '合同完整正文\n第一条 双方合作背景与正常交付义务。\n第二条 验收后十日内付款。\n附件 明细交付清单。'
const risks = [
  { id: 31, agent: 'finance', level: 'high', category: '付款条件', original_text: '验收后十日内付款。',
    suggestion: '明确验收标准', review_status: 'pending', basis: '合同约定', risk_reason: '条件不清', confidence: 80, tier: 'red', rag_sources: [] },
  { id: 32, agent: 'legal', level: 'medium', category: '缺失引用', original_text: '这句话不在正文中',
    suggestion: '人工核对引用', review_status: 'pending', basis: '', risk_reason: '', confidence: 70, tier: 'yellow', rag_sources: [] },
]

async function setup(page: Page, documentStatus: 'available' | 'empty' | 'error' = 'available') {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'reader')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('authorized_departments', '["法务部"]')
    localStorage.setItem('qijian-completed-audit', JSON.stringify({owner:'reader', contractId:301, filename:'完整正文样本.txt', jobId:3301}))
  })
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith('/runtime/status')) body = {status:'online', checked_at:'2026-11-01T00:00:00Z'}
    else if (path.endsWith('/handoffs')) body = {items:[], state:'EMPTY'}
    else if (path.endsWith('/audit-status')) body = {contract_id:301, job_id:3301, status:'done', risk_count:2, cross_checks:[], requires_review:false}
    else if (path.endsWith('/risks')) body = risks
    else if (path.endsWith('/document')) {
      if (documentStatus === 'error') {
        await route.fulfill({status:503, contentType:'application/json', body:JSON.stringify({detail:'正文服务暂不可用'})})
        return
      }
      body = {contract_id:301, filename:'完整正文样本.txt', status:documentStatus,
        text:documentStatus === 'available' ? text : '', source:'native', requires_review:false,
        message:documentStatus === 'empty' ? '未提取到可阅读正文' : '', missing_pages:[]}
    }
    await route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(body)})
  })
  await page.goto('/audit')
  await expect(page.getByText('付款条件',{exact:true})).toBeVisible()
}

test('完整正文保留正常上下文，风险可定位，缺失引用不伪造匹配', async ({page}) => {
  await setup(page)
  await page.getByRole('button',{name:'查看合同原文与批注'}).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('region',{name:'完整解析正文'})).toContainText('第一条 双方合作背景与正常交付义务。')
  await expect(dialog.getByRole('region',{name:'完整解析正文'})).toContainText('附件 明细交付清单。')
  await dialog.getByRole('button',{name:'定位风险：付款条件',exact:true}).click()
  await expect(dialog.locator('mark')).toHaveText('验收后十日内付款。')
  await dialog.getByRole('button',{name:'定位风险：缺失引用',exact:true}).focus()
  await page.keyboard.press('Enter')
  await expect(dialog.getByText('未在解析正文中找到精确引用，请人工核对。',{exact:true})).toBeVisible()
  await expect(dialog.locator('mark')).toHaveCount(0)
  await page.setViewportSize({width:390,height:844})
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await expect(dialog.getByRole('region',{name:'完整解析正文'})).toBeVisible()
})

test('正文为空时说明原因，不以风险摘录冒充正文', async ({page}) => {
  await setup(page,'empty')
  await page.getByRole('button',{name:'查看合同原文与批注'}).click()
  const dialog=page.getByRole('dialog')
  await expect(dialog.getByText('未提取到可阅读正文',{exact:true})).toBeVisible()
  await expect(dialog.getByRole('button',{name:'重新加载正文'})).toBeVisible()
})

test('正文加载失败后可以重试并恢复', async ({page}) => {
  await setup(page,'error')
  await page.getByRole('button',{name:'查看合同原文与批注'}).click()
  const dialog=page.getByRole('dialog')
  await expect(dialog.getByText('正文加载失败，请重试。',{exact:true})).toBeVisible()
  await page.route('**/contracts/301/document',route=>route.fulfill({status:200,contentType:'application/json',
    body:JSON.stringify({contract_id:301,filename:'完整正文样本.txt',status:'available',text,source:'native',missing_pages:[]})}))
  await dialog.getByRole('button',{name:'重新加载正文'}).click()
  await expect(dialog.getByRole('region',{name:'完整解析正文'})).toContainText('附件 明细交付清单。')
})

test('历史链接打开指定合同与任务，不恢复成其他合同', async ({page}) => {
  await setup(page)
  await page.goto('/audit?contractId=301&jobId=3301&filename=完整正文样本.txt')
  await expect(page.locator('[data-audit-detail]').getByRole('heading',{name:'完整正文样本.txt'})).toBeVisible()
  await expect(page.getByRole('button',{name:'查看合同原文与批注'})).toBeVisible()
})

test('未审查历史合同可以直接阅读正文且不会自动发起审查', async ({page}) => {
  await setup(page)
  let started = false
  await page.route('**/contracts/301/audit-status',route=>route.fulfill({json:{contract_id:301,status:'audit_failed',job_id:null}}))
  await page.route('**/contracts/301/audit',async route=>{started=true;await route.fulfill({json:{}})})
  await page.goto('/audit?contractId=301&filename=完整正文样本.txt')
  await expect(page.getByRole('region',{name:'所选合同'})).toContainText('完整正文样本.txt')
  await page.getByRole('button',{name:'查看所选合同原文'}).click()
  await expect(page.getByRole('region',{name:'完整解析正文'})).toContainText('附件 明细交付清单。')
  expect(started).toBe(false)
})

test('覆盖不完整且没有风险候选时不展示未检出风险', async ({page}) => {
  await setup(page)
  await page.route('**/contracts/301/audit-status**',route=>route.fulfill({json:{contract_id:301,job_id:3301,status:'review_required',risk_count:0,
    requires_review:true,review_reason:'审查覆盖不完整',coverage:{planned:2,completed:1}}}))
  await page.route('**/contracts/301/risks**',route=>route.fulfill({json:[]}))
  await page.goto('/audit?contractId=301&jobId=3301&filename=完整正文样本.txt')
  await expect(page.getByText('审查结果不完整，暂不能据此判断合同无风险',{exact:true})).toBeVisible()
  await expect(page.getByText('该合同未检出风险',{exact:true})).toHaveCount(0)
})
