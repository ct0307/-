import { expect, test } from '@playwright/test'

import {
  AUDIT_POLLING_MAX_ATTEMPTS,
  auditProgressDisplay,
  batchItemProgressDisplay,
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

test('batch item displays each persisted progress stage with the backend percentage', () => {
  expect(batchItemProgressDisplay(0, 'queued')).toEqual({
    label: '等待审查',
    percentage: 0,
    indeterminate: false,
  })
  expect(batchItemProgressDisplay(12, 'claimed')).toEqual({
    label: '已领取任务',
    percentage: 12,
    indeterminate: false,
  })
  expect(batchItemProgressDisplay(25, 'parsing')).toEqual({
    label: '正在解析',
    percentage: 25,
    indeterminate: false,
  })
  expect(batchItemProgressDisplay(48, 'reviewing')).toEqual({
    label: '正在审查',
    percentage: 48,
    indeterminate: false,
  })
  expect(batchItemProgressDisplay(72, 'verifying')).toEqual({
    label: '正在校验',
    percentage: 72,
    indeterminate: false,
  })
  expect(batchItemProgressDisplay(91, 'persisting')).toEqual({
    label: '正在保存',
    percentage: 91,
    indeterminate: false,
  })
  expect(batchItemProgressDisplay(100, 'completed')).toEqual({
    label: '审查完成',
    percentage: 100,
    indeterminate: false,
  })
})

test('discovery and enrichment change the real stage without inventing completed work', () => {
  expect(batchItemProgressDisplay(15, 'discovering')).toEqual({
    label: '正在发现风险', percentage: 15, indeterminate: false,
  })
  expect(batchItemProgressDisplay(15, 'enriching')).toEqual({
    label: '正在补充理由与建议', percentage: 15, indeterminate: false,
  })
})

test('review-required completion describes processing state without claiming audit completion', () => {
  expect(batchItemProgressDisplay(100, 'completed', 'review_required')).toEqual({
    label: '处理完成，待人工复核',
    percentage: 100,
    indeterminate: false,
  })
  expect(batchItemProgressDisplay(undefined, undefined, 'review_required')).toEqual({
    label: '处理完成，待人工复核',
    percentage: 100,
    indeterminate: false,
  })
})

test('batch item preserves persisted failure progress and clamps backend percentages', () => {
  expect(batchItemProgressDisplay(68, 'failed')).toEqual({
    label: '审查失败',
    percentage: 68,
    indeterminate: false,
  })
  expect(batchItemProgressDisplay(-5, 'parsing').percentage).toBe(0)
  expect(batchItemProgressDisplay(128, 'persisting').percentage).toBe(100)
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

test('single audit follows reviewing and validating before done', async () => {
  const responses = [
    { contract_id: 1, status: 'reviewing' },
    { contract_id: 1, status: 'validating' },
    { contract_id: 1, status: 'done' },
  ]
  let calls = 0

  const result = await waitForAuditTerminal(
    async () => responses[calls++]!,
    { intervalMs: 0, maxAttempts: 3 },
  )

  expect(calls).toBe(3)
  expect(result.status).toBe('done')
})

test('single audit accepts review_required as a usable terminal result', async () => {
  const result = await waitForAuditTerminal(
    async () => ({ contract_id: 1, status: 'review_required', requires_review: true }),
    { intervalMs: 0, maxAttempts: 1 },
  )

  expect(result.status).toBe('review_required')
  expect(result.requires_review).toBe(true)
})

test('single audit surfaces persisted failure status', async () => {
  await expect(waitForAuditTerminal(
    async () => ({ contract_id: 1, status: 'audit_failed' }),
    { intervalMs: 0, maxAttempts: 1 },
  )).rejects.toThrow('审查任务执行失败')
})

test('single audit accepts the batch failure alias as terminal failure', async () => {
  await expect(waitForAuditTerminal(
    async () => ({ contract_id: 1, status: 'failed' }),
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
