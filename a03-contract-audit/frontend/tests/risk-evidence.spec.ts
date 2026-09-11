import { expect, test } from '@playwright/test'

import { evidenceMeta } from '../src/utils/risk-evidence'


test('maps evidence status to explainable review labels', () => {
  expect(evidenceMeta('supported')).toEqual({ label: '依据与原文已核验', type: 'success' })
  expect(evidenceMeta('partially_supported')).toEqual({ label: '已检索可信来源 · 待核验', type: 'warning' })
  expect(evidenceMeta('unsupported')).toEqual({ label: '证据不足 · 待复核', type: 'danger' })
})

test('unknown evidence status defaults to manual review', () => {
  expect(evidenceMeta('legacy')).toEqual({ label: '证据状态未知 · 待复核', type: 'warning' })
})
