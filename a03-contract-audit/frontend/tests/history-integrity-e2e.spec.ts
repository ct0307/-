import { expect, test, type Page } from '@playwright/test'
import { historyRiskCountLabel, isHistoryAssessmentComplete, normalizeHistoryAssessment } from '../src/utils/history-assessment'
import type { HistoryRow } from '../src/mock/history'

test('覆盖率必须为正整数计划且完成数严格相等，异常和失败都不能得出完整结论',()=>{
  const base:HistoryRow={id:'C1',name:'边界合同',type:'采购合同',submitter:'测试员',time:'2026-11-01',level:'中风险',riskCount:2,status:'待整改',assessmentComplete:true,coverage:{planned:3,completed:3}}
  expect(isHistoryAssessmentComplete(base)).toBe(true)
  expect(normalizeHistoryAssessment(base).level).toBe('中风险')
  expect(historyRiskCountLabel(base)).toBe('2')
  for(const coverage of [null,{planned:0,completed:0},{planned:3,completed:2},{planned:3,completed:4},{planned:2.5,completed:2.5},{planned:3,completed:NaN}]) {
    expect(isHistoryAssessmentComplete({...base,coverage})).toBe(false)
  }
  for(const status of ['审查失败','解析失败','审查中','未审查'] as const) {
    expect(isHistoryAssessmentComplete({...base,status})).toBe(false)
  }
  expect(isHistoryAssessmentComplete({...base,assessmentComplete:undefined})).toBe(false)
  expect(normalizeHistoryAssessment({...base,status:'合规',coverage:null}).status).toBe('待人工复核')
  expect(historyRiskCountLabel({...base,coverage:null})).toBe('已检出 2')
  expect(historyRiskCountLabel({...base,riskCount:0,coverage:null})).toBe('未完成')
})

const history = [
  { id:'C0301',name:'失败合同.txt',type:'采购合同',submitter:'测试员',time:'2026-11-01T00:00:00Z',level:'低风险',riskCount:0,status:'审查失败',assessmentComplete:false,coverage:{planned:10,completed:2} },
  { id:'C0302',name:'完整合同.txt',type:'采购合同',submitter:'测试员',time:'2026-11-01T00:00:00Z',level:'未发现风险',riskCount:0,status:'未发现风险',assessmentComplete:true,coverage:{planned:10,completed:10} },
  { id:'C0303',name:'旧响应合同.txt',type:'采购合同',submitter:'测试员',time:'2026-11-01T00:00:00Z',level:'低风险',riskCount:0,status:'合规' },
  { id:'C0304',name:'低覆盖合同.txt',type:'采购合同',submitter:'测试员',time:'2026-11-01T00:00:00Z',level:'低风险',riskCount:1,status:'合规',assessmentComplete:true,coverage:{planned:10,completed:2} },
]
const risk = { id:71,agent:'legal',level:'high',category:'当前任务候选',original_text:'正文付款条款',suggestion:'核对条款',review_status:'pending',basis:'合同约定',confidence:80,tier:'red',rag_sources:[] }

async function setup(page:Page, role='legal') {
  await page.addInitScript(role => {
    localStorage.setItem('token','history-test-token')
    localStorage.setItem('role',role)
    localStorage.setItem('username','history-reader')
    localStorage.setItem('department','法务部')
    localStorage.setItem('authorized_departments','["法务部"]')
  },role)
  await page.route('**/api/v1/**', async route => {
    const url=new URL(route.request().url())
    let body:unknown=[]
    if (url.pathname.endsWith('/runtime/status')) body={status:'online'}
    else if (url.pathname.endsWith('/handoffs')) body={items:[],state:'EMPTY'}
    else if (url.pathname.endsWith('/contracts')) body=history
    else if (url.pathname.endsWith('/audit-status')) {
      const cid=Number(url.pathname.split('/').at(-2))
      body={contract_id:cid,job_id:cid+3000,batch_id:81,status:cid===301?'audit_failed':'done',risk_count:0,
        requires_review:cid===301,coverage:{planned:10,completed:cid===301?2:10},quality_reasons:[],issues:[]}
    } else if (url.pathname.endsWith('/risks')) body=url.searchParams.has('job_id')?[]:[risk]
    else if (url.pathname.endsWith('/document')) {
      const cid=Number(url.pathname.split('/').at(-2))
      body={contract_id:cid,filename:'合同.txt',status:'available',text:`合同 ${cid} 完整正文。正文付款条款`,source:'native'}
    }
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)})
  })
  await page.goto('/history')
  await expect(page.getByRole('row').filter({hasText:'失败合同.txt'})).toBeVisible()
}

test('失败、旧响应与低覆盖不能显示低风险，完整零候选保留未发现风险',async({page})=>{
  await setup(page)
  for(const name of ['失败合同.txt','旧响应合同.txt','低覆盖合同.txt']) {
    const row=page.getByRole('row').filter({hasText:name})
    await expect(row).toContainText('尚无法判断')
    await expect(row).not.toContainText('低风险')
  }
  await expect(page.getByRole('row').filter({hasText:'失败合同.txt'})).toContainText('未完成')
  await expect(page.getByRole('row').filter({hasText:'低覆盖合同.txt'})).toContainText('已检出 1')
  await expect(page.getByRole('row').filter({hasText:'完整合同.txt'})).toContainText('未发现风险')
  await page.locator('.filters .el-select').first().click()
  await page.getByRole('option',{name:'尚无法判断',exact:true}).click()
  await expect(page.getByRole('row').filter({hasText:'完整合同.txt'})).toHaveCount(0)
})

test('1280桌面直接可见合规状态，移动端不产生页面横向溢出',async({page})=>{
  await page.setViewportSize({width:1280,height:800})
  await setup(page)
  const cell=page.getByRole('row').filter({hasText:'失败合同.txt'}).getByText('审查失败',{exact:true})
  await expect(cell).toBeInViewport({ratio:1})
  await page.setViewportSize({width:390,height:844})
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
})

test('失败合同详情明确不完整，可读原文并恢复对应批次',async({page})=>{
  await setup(page)
  const requests:string[]=[]
  page.on('request',request=>{if(request.url().includes('/301/risks'))requests.push(request.url())})
  await page.getByRole('row').filter({hasText:'失败合同.txt'}).click()
  const drawer=page.getByRole('dialog').filter({hasText:'风险详情'})
  await expect(drawer).toContainText('结果不完整')
  await expect(drawer).not.toContainText('暂无风险记录')
  await drawer.getByRole('button',{name:'查看合同原文与批注'}).click()
  await expect(page.getByRole('region',{name:'完整解析正文'})).toContainText('合同 301 完整正文')
  await page.keyboard.press('Escape')
  await drawer.getByRole('button',{name:'前往审查页复核'}).click()
  await expect(page).toHaveURL(/\/audit\?batch=81$/)
  expect(requests.every(url=>new URL(url).searchParams.get('job_id')==='3301')).toBe(true)
})

test('键盘打开完整合同零候选详情，可以读原文并携带合同与任务跳转',async({page})=>{
  await setup(page,'finance')
  await page.getByRole('button',{name:'完整合同.txt',exact:true}).focus()
  await page.keyboard.press('Enter')
  const drawer=page.getByRole('dialog')
  await expect(drawer).toContainText('本次完整审查未发现风险候选')
  await expect(drawer.getByRole('button',{name:'查看合同原文与批注'})).toBeEnabled()
  await drawer.getByRole('button',{name:'前往审查页复核'}).click()
  await expect(page).toHaveURL(/contractId=302/)
  await expect(page).toHaveURL(/jobId=3302/)
  expect(new URL(page.url()).searchParams.get('filename')).toBe('完整合同.txt')
})

for (const scenario of [
  {name:'待复核且只覆盖1项',snapshot:{status:'review_required',requires_review:true,coverage:{planned:10,completed:1}},coverageText:'已完成 1 / 10 项计划检查。'},
  {name:'done但覆盖不足',snapshot:{status:'done',requires_review:false,coverage:{planned:10,completed:1}},coverageText:'已完成 1 / 10 项计划检查。'},
  {name:'done但要求复核',snapshot:{status:'done',requires_review:true}},
  {name:'质量原因非空',snapshot:{quality_reasons:['MODEL_INCOMPLETE']}},
  {name:'问题列表非空',snapshot:{issues:[{reason:'覆盖不足'}]}},
  {name:'质量原因类型无效',snapshot:{quality_reasons:''}},
  {name:'问题列表类型无效',snapshot:{issues:{}}},
  {name:'旧任务响应缺元数据',snapshot:{requires_review:undefined,coverage:undefined,quality_reasons:undefined,issues:undefined},coverageText:'缺少完整覆盖率证据。'},
]) {
  test(`最新重审${scenario.name}不能沿用列表完整结论`,async({page})=>{
    await setup(page)
    const snapshot={contract_id:302,job_id:9902,status:'done',risk_count:0,requires_review:false,
      coverage:{planned:10,completed:10},quality_reasons:[],issues:[],...scenario.snapshot}
    await page.route('**/302/audit-status',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(snapshot)}))
    const requests:string[]=[]
    page.on('request',request=>{if(request.url().includes('/302/risks'))requests.push(request.url())})
    await page.getByRole('row').filter({hasText:'完整合同.txt'}).click()
    const drawer=page.getByRole('dialog')
    await expect(drawer).toContainText('结果不完整')
    await expect(drawer).not.toContainText('本次完整审查未发现风险候选')
    if (scenario.coverageText) await expect(drawer).toContainText(scenario.coverageText)
    expect(requests.length).toBeGreaterThan(0)
    expect(requests.every(url=>new URL(url).searchParams.get('job_id')==='9902')).toBe(true)
  })
}

test('状态加载失败保留原文和重试，不把空数据当成功',async({page})=>{
  await setup(page)
  await page.route('**/301/audit-status',route=>route.fulfill({status:503,contentType:'application/json',body:'{"detail":"暂不可用"}'}))
  await page.getByRole('row').filter({hasText:'失败合同.txt'}).click()
  const drawer=page.getByRole('dialog')
  await expect(drawer).toContainText('详情加载失败')
  await expect(drawer.getByRole('button',{name:'重试加载详情'})).toBeVisible()
  await expect(drawer.getByRole('button',{name:'查看合同原文与批注'})).toBeEnabled()
  await expect(drawer).not.toContainText('本次完整审查未发现风险候选')
  await page.unroute('**/301/audit-status')
  await drawer.getByRole('button',{name:'重试加载详情'}).click()
  await expect(drawer).not.toContainText('详情加载失败')
})

test('业务角色不显示全文入口',async({page})=>{
  await setup(page,'business')
  await page.getByRole('row').filter({hasText:'失败合同.txt'}).click()
  await expect(page.getByRole('button',{name:'查看合同原文与批注'})).toHaveCount(0)
})

test('无任务的合同不读取旧候选，仍可查看原文',async({page})=>{
  await setup(page,'admin')
  await page.route('**/303/audit-status',route=>route.fulfill({status:200,contentType:'application/json',body:'{"contract_id":303,"status":"queued"}'}))
  const riskRequests:string[]=[]
  page.on('request',request=>{if(request.url().includes('/303/risks'))riskRequests.push(request.url())})
  await page.getByRole('row').filter({hasText:'旧响应合同.txt'}).click()
  const drawer=page.getByRole('dialog')
  await expect(drawer).toContainText('结果不完整')
  await expect(drawer).not.toContainText('当前任务候选')
  await drawer.getByRole('button',{name:'查看合同原文与批注'}).click()
  await expect(page.getByRole('region',{name:'完整解析正文'})).toContainText('合同 303 完整正文')
  expect(riskRequests).toEqual([])
})

test('关闭旧详情后选择新合同，延迟响应不覆盖当前上下文',async({page})=>{
  await setup(page)
  let releaseOld:()=>void=()=>{}
  const oldGate=new Promise<void>(resolve=>{releaseOld=resolve})
  let oldStarted=false
  await page.route('**/301/audit-status',async route=>{
    oldStarted=true
    await oldGate
    await route.fulfill({status:200,contentType:'application/json',body:'{"contract_id":301,"job_id":3301,"batch_id":81,"status":"audit_failed"}'})
  })
  await page.getByRole('row').filter({hasText:'失败合同.txt'}).click()
  await expect.poll(()=>oldStarted).toBe(true)
  await page.keyboard.press('Escape')
  await page.getByRole('row').filter({hasText:'完整合同.txt'}).click()
  releaseOld()
  const drawer=page.getByRole('dialog')
  await expect(drawer).toContainText('风险详情 · 完整合同.txt')
  await expect(drawer).toContainText('本次完整审查未发现风险候选')
  await drawer.getByRole('button',{name:'前往审查页复核'}).click()
  await expect(page).toHaveURL(/contractId=302/)
  await expect(page).toHaveURL(/jobId=3302/)
})
