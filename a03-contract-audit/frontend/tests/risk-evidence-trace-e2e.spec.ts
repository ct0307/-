import { expect, test } from '@playwright/test'

import { applicabilityMeta, ruleStatusMeta } from '../src/utils/audit-trace'

const baseUrl = process.env.E2E_BASE_URL
  ?? `http://127.0.0.1:${process.env.E2E_PORT ?? '41739'}`

const legacyRisk = {
  id: 901,
  agent: 'legal',
  level: 'high',
  category: 'legacy-risk-without-trace',
  original_text: '旧接口只返回基础风险字段',
  risk_reason: '用于验证向后兼容',
  basis: '历史依据',
  suggestion: '人工复核后再采纳',
  confidence: 86,
  tier: 'red',
  review_status: 'pending',
  rag_sources: [],
  evidence_status: 'supported',
  original_text_verified: true,
}

const abnormalRuleRisk = {
  id: 902,
  agent: 'finance',
  level: 'medium',
  category: 'risk-with-abnormal-rule-status',
  original_text: '规则执行状态来自未知版本',
  risk_reason: '用于验证规则异常状态降级',
  basis: '规则证据',
  suggestion: '补充规则核验',
  confidence: 74,
  tier: 'yellow',
  review_status: 'pending',
  rag_sources: [],
  evidence_status: 'partially_supported',
  original_text_verified: false,
  applicability_status: 'unknown_as_of',
  applicability_reason_codes: ['missing_effective_date'],
  rule_executions: [{ rule_id: 'RULE-UNKNOWN', rule_version: 'test-v1', status: 'unexpected_status' }],
  decision_trace: { status: 'manual_review', reason_codes: ['RULE_RESULT_UNRESOLVED'] },
}

test('兼容旧风险字段并展示未知适用性与异常规则状态', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('role', 'legal')
    localStorage.setItem('username', 'legal')
    localStorage.setItem('department', '法务部')
    localStorage.setItem('authorized_departments', JSON.stringify(['法务部']))
    localStorage.setItem('qijian-completed-audit', JSON.stringify({
      owner: 'legal', contractId: 901, filename: 'trace-compatibility.pdf', jobId: 9901,
    }))
  })

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith('/runtime/status')) {
      body = { status: 'online', checked_at: '2026-09-18T10:00:00Z' }
    } else if (path.includes('/admin/lookups/')) {
      body = []
    } else if (path.endsWith('/contracts/901/audit-status')) {
      body = {
        contract_id: 901,
        job_id: 9901,
        status: 'done',
        risk_count: 2,
        cross_checks: [],
        requires_review: false,
      }
    } else if (path.endsWith('/contracts/901/risks')) {
      body = [legacyRisk, abnormalRuleRisk]
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto(`${baseUrl}/audit`)
  await expect(page.getByText('legacy-risk-without-trace', { exact: true })).toBeVisible()

  await page.getByText('legacy-risk-without-trace', { exact: true }).click()
  const drawer = page.locator('.el-drawer').last()
  await expect(drawer.locator('section').filter({ hasText: '法规适用性' }).getByText(applicabilityMeta(undefined).label, { exact: true })).toBeVisible()
  await expect(drawer.locator('section').filter({ hasText: '规则核验' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Close this dialog' }).click()

  await page.getByText('risk-with-abnormal-rule-status', { exact: true }).click()
  await expect(drawer.locator('section').filter({ hasText: '法规适用性' }).getByText(applicabilityMeta('unknown_as_of').label, { exact: true })).toBeVisible()
  await expect(drawer.locator('section').filter({ hasText: '规则核验' }).getByText(ruleStatusMeta('unexpected_status').label, { exact: true })).toBeVisible()

  await page.goto(`${baseUrl}/collaboration`)
  await expect(page.getByText('决策：人工复核', { exact: true })).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
