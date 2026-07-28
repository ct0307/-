import { expect, test } from '@playwright/test'

import { auditProgressDisplay, waitForAuditTerminal } from '../src/utils/audit-progress'


test('single audit never invents a percentage while backend request is running', () => {
  expect(auditProgressDisplay('running')).toEqual({
    label: '正在执行合同审查…',
    percentage: null,
    indeterminate: true,
  })
})

test('single audit only reports completion after the request finishes', () => {
  expect(auditProgressDisplay('done')).toEqual({
    label: '审查完成',
    percentage: 100,
    indeterminate: false,
  })
})

test('single audit waits for persisted terminal status', async () => {
  const responses = [
    { contract_id: 1, status: 'auditing' },
    { contract_id: 1, status: 'review_required', requires_review: true },
  ]
  let calls = 0

  const result = await waitForAuditTerminal(
    async () => responses[calls++]!,
    { intervalMs: 0, maxAttempts: 3 },
  )

  expect(calls).toBe(2)
  expect(result.status).toBe('review_required')
  expect(result.requires_review).toBe(true)
})

test('single audit surfaces persisted failure status', async () => {
  await expect(waitForAuditTerminal(
    async () => ({ contract_id: 1, status: 'audit_failed' }),
    { intervalMs: 0, maxAttempts: 1 },
  )).rejects.toThrow('审查任务执行失败')
})
