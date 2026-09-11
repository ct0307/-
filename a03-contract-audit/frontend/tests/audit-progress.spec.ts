import { expect, test } from '@playwright/test'

import {
  AUDIT_POLLING_MAX_ATTEMPTS,
  auditProgressDisplay,
  waitForAuditTerminal,
} from '../src/utils/audit-progress'
import { PARSE_TIMEOUT_MS } from '../src/api/contract'


test('default polling budget covers the backend 30 minute task limit', () => {
  expect(AUDIT_POLLING_MAX_ATTEMPTS).toBeGreaterThanOrEqual(1860)
})

test('parse timeout leaves transport margin beyond the backend OCR budget', () => {
  expect(PARSE_TIMEOUT_MS).toBeGreaterThan(120_000)
})


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

test('single audit surfaces the persisted backend failure detail', async () => {
  await expect(waitForAuditTerminal(
    async () => ({
      contract_id: 1,
      status: 'audit_failed',
      error_code: 'MODEL_TIMEOUT',
      error_message: '模型响应超时，请稍后重试',
      retryable: true,
    }),
    { intervalMs: 0, maxAttempts: 1 },
  )).rejects.toMatchObject({
    message: '模型响应超时，请稍后重试',
    code: 'MODEL_TIMEOUT',
    retryable: true,
  })
})

test('single audit fails closed for an unknown persisted status', async () => {
  await expect(waitForAuditTerminal(
    async () => ({ contract_id: 1, status: 'mystery_state' }),
    { intervalMs: 0, maxAttempts: 1 },
  )).rejects.toThrow('审查任务返回未知状态：mystery_state')
})
