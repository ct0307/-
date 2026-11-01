import { expect, test } from '@playwright/test'

import { evidenceMeta, isEvidenceVerified, riskEvidenceMeta, relationEvidenceMeta } from '../src/utils/risk-evidence'


test('maps evidence status to explainable review labels', () => {
  expect(evidenceMeta('supported')).toEqual({ label: '依据与原文已核验', type: 'success' })
  expect(evidenceMeta('partially_supported')).toEqual({ label: '已检索可信来源 · 待核验', type: 'warning' })
  expect(evidenceMeta('unsupported')).toEqual({ label: '证据不足 · 待复核', type: 'danger' })
})

test('unknown evidence status defaults to manual review', () => {
  expect(evidenceMeta('legacy')).toEqual({ label: '证据状态未知 · 待复核', type: 'warning' })
})

test('当前证据门禁区分完整有限规则、历史支持和人工确认', () => {
  const risk = { evidence_status: 'supported', support_relation_status: 'supported',
    original_text: '验收后付款',
    support_validator_version: 'support-deterministic-v1', original_text_verified: true,
    support_validation_failed_stage: 'none', support_validation_reason_code: 'EVIDENCE_SUPPORTS_CLAIM',
    evidence_ids: ['KC-1'], rag_sources: [{ source: '民法典', content: '测试法条', reliable: true, applicability_status: 'applicable' }] }
  expect(isEvidenceVerified(risk)).toBe(true)
  expect(riskEvidenceMeta(risk).type).toBe('success')
  expect(isEvidenceVerified({ ...risk, support_validator_version: 'rules-v2' })).toBe(false)
  expect(riskEvidenceMeta({ evidence_status: 'supported' }).type).toBe('warning')
  expect(isEvidenceVerified({ ...risk, evidence_ids: [] })).toBe(false)
  expect(isEvidenceVerified({ ...risk, original_text: '' })).toBe(false)
  expect(isEvidenceVerified({ ...risk, support_validation_failed_stage: 'facts' })).toBe(false)
  expect(isEvidenceVerified({ ...risk, rag_sources: [{ source: '网页', content: '候选', reliable: false, applicability_status: 'applicable' }] })).toBe(false)
  expect(riskEvidenceMeta({ evidence_status: 'unsupported', support_relation_status: 'unclear' }).type).toBe('danger')
  expect(relationEvidenceMeta({ status: 'supported', validator_version: 'rules-v2' }, risk).type).toBe('warning')
  const relation = { status: 'supported', validator_version: 'support-deterministic-v1', failed_stage: 'none', reason_code: 'EVIDENCE_SUPPORTS_CLAIM' }
  expect(relationEvidenceMeta(relation, risk).type).toBe('success')
  expect(relationEvidenceMeta(relation, { evidence_status: 'supported' }).type).toBe('warning')
})
