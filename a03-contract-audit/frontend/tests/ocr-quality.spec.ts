import { expect, test } from '@playwright/test'

import { formatOcrConfidence, reviewStatusLabel } from '../src/utils/ocr-quality'


test('formats bounded OCR confidence for review display', () => {
  expect(formatOcrConfidence(0.423)).toBe('42.3%')
  expect(formatOcrConfidence(null)).toBe('未提供')
})

test('keeps machine completion distinct from business review', () => {
  expect(reviewStatusLabel({ status: 'done', requires_review: true })).toBe('需人工复核')
  expect(reviewStatusLabel({ status: 'done', requires_review: false })).toBe('已完成')
})
