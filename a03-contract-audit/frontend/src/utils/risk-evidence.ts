export type EvidenceStatus = 'supported' | 'partially_supported' | 'unsupported' | 'unclear' | 'contradicted'

export type EvidenceMeta = {
  label: string
  type: 'success' | 'warning' | 'danger'
}

const META: Record<EvidenceStatus, EvidenceMeta> = {
  supported: { label: '依据与原文已核验', type: 'success' },
  partially_supported: { label: '已检索可信来源 · 待核验', type: 'warning' },
  unsupported: { label: '证据不足 · 待复核', type: 'danger' },
  unclear: { label: '核验不确定 · 待人工复核', type: 'warning' },
  contradicted: { label: '依据存在矛盾 · 待人工裁决', type: 'danger' },
}

export function evidenceMeta(status: string | null | undefined): EvidenceMeta {
  if (status && status in META) return META[status as EvidenceStatus]
  return { label: '证据状态未知 · 待复核', type: 'warning' }
}

export interface HumanReview {
  operator_id: number
  reviewed_at: string
  status: string
  reason: string
}

export interface DecisionTrace {
  status?: string
  reason_codes?: string[]
  evidence_validation?: { mode?: string; version?: string; failed_stage?: string; reason_code?: string }
  human_review?: HumanReview
}

interface EvidenceRisk {
  original_text?: string
  evidence_status?: string | null
  support_relation_status?: string
  support_validator_version?: string
  support_validation_failed_stage?: string
  support_validation_reason_code?: string
  original_text_verified?: boolean | null
  evidence_ids?: string[]
  rag_sources?: Array<{ source?: string; content?: string; reliable?: boolean; applicability_status?: string }>
}

export function isEvidenceVerified(risk: EvidenceRisk | null | undefined): boolean {
  const sources = risk?.rag_sources
  const ids = risk?.evidence_ids
  return risk?.evidence_status === 'supported' && risk.support_relation_status === 'supported'
    && !!risk.original_text?.trim()
    && ['support-v4', 'support-deterministic-v1'].includes(risk.support_validator_version || '')
    && risk.support_validation_failed_stage === 'none' && risk.support_validation_reason_code === 'EVIDENCE_SUPPORTS_CLAIM'
    && risk.original_text_verified === true && !!sources?.length && !!ids?.length
    && sources.length === ids.length && ids.every(id => typeof id === 'string' && !!id.trim())
    && sources.every(source => source?.reliable === true && source.applicability_status === 'applicable'
      && !!source.source?.trim() && !!source.content?.trim())
}

export function riskEvidenceMeta(risk: EvidenceRisk): EvidenceMeta {
  if (risk.evidence_status === 'supported' && !isEvidenceVerified(risk)) return evidenceMeta('unclear')
  return evidenceMeta(risk.evidence_status)
}

export function relationEvidenceMeta(relation: {
  status?: string; validator_version?: string; failed_stage?: string; reason_code?: string
}, risk: EvidenceRisk): EvidenceMeta {
  if (relation.status === 'supported' && (!isEvidenceVerified(risk)
    || !['support-v4', 'support-deterministic-v1'].includes(relation.validator_version || '')
    || relation.failed_stage !== 'none' || relation.reason_code !== 'EVIDENCE_SUPPORTS_CLAIM')) {
    return evidenceMeta('unclear')
  }
  return evidenceMeta(relation.status)
}

export function validationModeLabel(mode: string | null | undefined): string {
  return ({ deterministic: '有限规则核验', manual_only: '人工核验', semantic: '语义核验' } as Record<string, string>)[mode || ''] || '核验方式未记录'
}
