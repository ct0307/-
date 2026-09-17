import { expect, test, type Route } from '@playwright/test'
import type { UserConfig } from 'vite'

import viteConfig from '../vite.config'

const echartsEntries = [
  'echarts/core',
  'echarts/charts',
  'echarts/components',
  'echarts/renderers',
]

const reportSummary = {
  kpi: { total: 2, pass: 50, risk: 1, time: '1.2min' },
  kpiTrend: { total: '+1', pass: '+1%', risk: '0', time: '-0.1min' },
  trend: {
    labels: ['第一周', '第二周'],
    total: [1, 2],
    pass: [1, 1],
    risk: [0, 1],
  },
  donut: [
    { name: '高风险', value: 1 },
    { name: '中风险', value: 1 },
    { name: '低风险', value: 0 },
  ],
  depts: [{ name: '法务部', risk: 1, money: '10万元' }],
  tops: [{ name: '付款条件不明确', value: 1 }],
}

const contractMetadata = [{
  id: 1,
  filename: '图表稳定性测试合同.pdf',
  contract_type: '采购合同',
  department: '法务部',
  party_a: '甲方公司',
  subject: '软件服务',
  payment_terms: '验收后付款',
  amount: '10万元',
  risk_high: 1,
  risk_medium: 1,
  risk_low: 0,
  risk_total: 2,
  status: 'completed',
}]

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

test('prebundles every ECharts entry used by BaseChart', () => {
  const config = viteConfig as UserConfig

  expect(config.optimizeDeps?.include).toEqual(expect.arrayContaining(echartsEntries))
})

test('renders all report charts without leaving a loading mask', async ({ page }) => {
  const runtimeIssues: string[] = []
  page.on('console', (message) => {
    if (
      ['error', 'warning'].includes(message.type())
      && /ECharts|xAxis|mounted hook/i.test(message.text())
    ) {
      runtimeIssues.push(message.text())
    }
  })
  page.on('pageerror', (error) => runtimeIssues.push(error.message))

  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('authorized_departments', JSON.stringify(['法务部']))
  })

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/reports/summary')) return fulfillJson(route, reportSummary)
    if (path.endsWith('/reports/contracts-metadata')) return fulfillJson(route, contractMetadata)
    if (path.endsWith('/reports/preview')) return fulfillJson(route, {
      report_id: 'chart-stability', generated_at: '2026-09-17T00:00:00Z', contract_ids: [1],
      contracts: contractMetadata.map(c => ({ ...c, created_at: '2026-09-17T00:00:00Z', job_status: 'done' })),
      summary: { total: 1, completed: 1, review_required: 0, failed: 0, unreviewed: 0, running: 0, risks: 2, high: 1, medium: 1, low: 0, supported: 0 },
      risks: [{ contract_id: 1, level: 'high', category: '付款条件不明确' }, { contract_id: 1, level: 'medium', category: '验收条件' }],
      matrix: { categories: [], rows: [] }, rectifications: [], notes: [],
    })
    if (path.endsWith('/runtime/status')) {
      return fulfillJson(route, {
        status: 'online',
        checked_at: '2026-09-16T00:00:00Z',
        provider: 'deepseek',
        model: 'test-model',
      })
    }
    return fulfillJson(route, [])
  })

  await page.goto('/reports')
  await expect(page.getByRole('heading', { name: '多维数据报表' })).toBeVisible()
  await expect(page.locator('.chart canvas')).toHaveCount(4)
  await expect(page.locator('.report-body .el-loading-mask')).toHaveCount(0)
  expect(runtimeIssues).toEqual([])
})
