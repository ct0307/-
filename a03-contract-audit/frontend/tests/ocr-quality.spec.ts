import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { formatOcrConfidence, reviewStatusLabel } from '../src/utils/ocr-quality'


test('formats bounded OCR confidence for review display', () => {
  expect(formatOcrConfidence(0.423)).toBe('42.3%')
  expect(formatOcrConfidence(null)).toBe('未提供')
})

test('keeps machine completion distinct from business review', () => {
  expect(reviewStatusLabel({ status: 'done', requires_review: true })).toBe('需人工复核')
  expect(reviewStatusLabel({ status: 'done', requires_review: false })).toBe('已完成')
})

test('history supports and highlights the manual review status', () => {
  const historyTypeSource = readFileSync(
    fileURLToPath(new URL('../src/mock/history.ts', import.meta.url)),
    'utf8',
  )
  const historyViewSource = readFileSync(
    fileURLToPath(new URL('../src/views/HistoryView.vue', import.meta.url)),
    'utf8',
  )

  expect(historyTypeSource).toContain("'待人工复核'")
  expect(historyViewSource).toContain("待人工复核: 'danger'")
  expect(historyViewSource).toContain("const statusFilter = ref('全部')")
  expect(historyViewSource).toContain('r.status === statusFilter.value')
})
