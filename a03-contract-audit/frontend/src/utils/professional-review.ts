import type { RiskOut } from '@/api/types'
import type { AuditBatchItem } from '@/api/batches'
import { isEvidenceVerified } from './risk-evidence'

// 只转换展示文案，不参与证据、权限或人工复核状态的计算。
const reasonLabels: Record<string, string> = {
  SOURCE_NOT_APPLICABLE: '法规适用性待核对',
  AS_OF_DATE_UNKNOWN: '法规审查时点待确认',
  SOURCE_EXPIRED: '法规在审查时点已失效',
  SOURCE_NOT_YET_EFFECTIVE: '法规在审查时点尚未生效',
  ORIGINAL_TEXT_UNRESOLVED: '合同原文待定位核对',
  ORIGINAL_CONTEXT_UNRESOLVED: '合同上下文待核对',
  SOURCE_AUTHORITY_UNRESOLVED: '依据来源可靠性待核对',
  FACTS_NOT_ALIGNED: '依据与合同事实待核对',
  FACT_VALIDATION_FAILED: '合同事实待人工核对',
  CONFLICTING_EVIDENCE: '支持与反驳依据并存，需人工裁决',
  EVIDENCE_CONTRADICTS_CLAIM: '依据与风险判断存在矛盾',
  EVIDENCE_UNRESOLVED: '风险依据待核验',
  SECONDARY_REVIEW_PENDING: '二次复核尚未完成',
  SECONDARY_REVIEW_CONFLICT: '二次复核存在冲突',
  INCOMPLETE_COVERAGE: '审查覆盖不完整',
  DETERMINISTIC_RULE_NOT_PROVEN: '有限规则的事实条件尚未确认',
  SEMANTIC_VERIFIER_UNAVAILABLE: '依据支持关系待人工核验',
  SEMANTIC_VERIFIER_FAILED: '依据支持关系待人工核验',
  SEMANTIC_RELATION_UNRESOLVED: '依据支持关系待人工核验',
}

export function reviewReasonSummary(reason?: string | null, limit = 100): string {
  const businessText = (reason || '')
    .replace(/来源适用性未确认或已失效/g, '法规适用性待核对')
    .replace(/（([A-Z][A-Z0-9_]+)）|\(([A-Z][A-Z0-9_]+)\)/g, (match, fullWidthCode: string | undefined, code: string | undefined) => {
      const label = reasonLabels[fullWidthCode || code || '']
      return label ? `；${label}；` : match
    })
    .replace(/\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g, code => reasonLabels[code] || code)
  const parts = businessText.split(/[；;\n]+/).map(part => part.trim()).filter(Boolean)
  const summary = [...new Set(parts)].join('；')
  return summary.length > limit ? `${summary.slice(0, limit - 1)}…` : summary
}

export function applicabilityGuidance(risk: Pick<RiskOut, 'applicability_status' | 'applicability_reason_codes'> & Partial<Pick<RiskOut, 'rag_sources'>>) {
  const statusByReason: Record<string, string> = {
    AS_OF_DATE_UNKNOWN: 'unknown_as_of',
    SOURCE_EXPIRED: 'expired',
    SOURCE_NOT_YET_EFFECTIVE: 'not_yet_effective',
    SOURCE_APPLICABLE: 'applicable',
  }
  const statuses = new Set((risk.applicability_reason_codes || []).map(code => statusByReason[code] || 'unresolved'))
  for (const source of risk.rag_sources || []) {
    if (source.reliable === true) statuses.add(source.applicability_status || 'unresolved')
  }
  if (risk.applicability_status && risk.applicability_status !== 'unresolved') statuses.add(risk.applicability_status)
  // 未知时点优先，防止将缺日期或相互冲突的来源记录概括成全部失效。
  if (statuses.has('unknown_as_of')) return {
    displayStatus: 'unknown_as_of',
    explanation: '适用时点未知，不能据此认定法规已失效。',
    nextStep: '请核对合同已确认的签订日期，再核验法规在该日期是否适用。',
  }
  if (statuses.size > 1) return {
    displayStatus: 'unresolved',
    explanation: '依据来源存在多种适用状态，请逐条核对各法规的适用时点。',
    nextStep: '逐条核对各依据来源的适用状态及对应的合同事实。',
  }
  if (statuses.has('expired')) return {
    displayStatus: 'expired',
    explanation: '该法规在审查时点已失效，请核对替代规定及过渡条款。',
    nextStep: '核对审查时点有效的替代规定及过渡条款。',
  }
  if (statuses.has('not_yet_effective')) return {
    displayStatus: 'not_yet_effective',
    explanation: '该法规在审查时点尚未生效，请核对当时有效的规定。',
    nextStep: '核对审查时点已经生效的规定。',
  }
  if (statuses.has('applicable')) return {
    displayStatus: 'applicable',
    explanation: '已核验记录中的法规适用时点，仍需结合合同事实判断。',
    nextStep: '',
  }
  return {
    displayStatus: 'unresolved',
    explanation: '法规适用条件尚未确认，请核对法规版本、地域及合同事实。',
    nextStep: '核对法规版本、适用地域及合同事实。',
  }
}

export function originalTextLocated(risk: Pick<RiskOut, 'original_text' | 'original_text_verified'>): boolean {
  return risk.original_text_verified === true && !!risk.original_text?.trim()
}

export function riskReviewGuidance(risk: RiskOut) {
  const applicability = applicabilityGuidance(risk)
  const nextSteps: string[] = []
  if (!originalTextLocated(risk)) nextSteps.push('对照合同全文定位相关条款，核对完整上下文。')
  if (applicability.nextStep) nextSteps.push(applicability.nextStep)
  if (risk.support_relation_status === 'contradicted' || ['CONFLICTING_EVIDENCE', 'EVIDENCE_CONTRADICTS_CLAIM'].includes(risk.support_validation_reason_code || '')
    || risk.secondary_review_status === 'conflict') nextSteps.push('比对冲突依据及合同事实，记录人工裁决理由。')
  if (!isEvidenceVerified(risk)) nextSteps.push('补充或核对可靠依据，确认其支持当前风险判断后再作决定。')
  if (!nextSteps.length) nextSteps.push('核对问题与修改建议，记录人工复核决定。')
  const originalSummary = (risk.risk_reason || risk.category || '').trim()
  return {
    summary: (originalSummary.length > 280 ? `${originalSummary.slice(0, 279)}…` : originalSummary) || '请结合合同条款核对这项风险。',
    nextSteps,
    supportExplanation: isEvidenceVerified(risk)
      ? '依据与原文已通过当前核验规则，法律判断仍以人工复核为准。'
      : reasonLabels[risk.support_validation_reason_code || ''] || '当前依据尚不足以确认风险判断，需人工核对。',
    applicability,
  }
}

export function batchTimingSummary(item: Pick<AuditBatchItem, 'queue_wait_ms' | 'processing_ms' | 'total_ms'>): string {
  const fields = [
    ['排队', item.queue_wait_ms], ['处理', item.processing_ms], ['总耗时', item.total_ms],
  ] as const
  return fields.filter(([, value]) => typeof value === 'number' && Number.isFinite(value) && value >= 0)
    .map(([label, value]) => `${label} ${Number((value! / 1000).toFixed(1))} 秒`).join(' · ')
}
