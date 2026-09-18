// 后端返回的数据类型（与 backend/app/schemas 对齐）

export type AuditItemStatus =
  | 'queued'
  | 'parsing'
  | 'reviewing'
  | 'validating'
  | 'done'
  | 'review_required'
  | 'failed'

export type AuditBatchStatus =
  | 'queued'
  | 'running'
  | 'done'
  | 'review_required'
  | 'partial_failed'
  | 'failed'

export type AuditProgressStage =
  | 'queued'
  | 'claimed'
  | 'parsing'
  | 'reviewing'
  | 'verifying'
  | 'persisting'
  | 'completed'
  | 'failed'

export type AuditStatus = Exclude<AuditItemStatus, 'failed'> | 'audit_failed'

export type ContractStatus =
  | 'uploaded'
  | 'failed'
  | 'parsed'
  | 'reviewing'
  | 'validating'
  | 'done'
  | 'review_required'
  | 'audit_failed'
  | 'three_review'
  | 'purged'

export interface ContractQualityFields {
  requires_review?: boolean
  ocr_confidence?: number | null
  review_reason?: string | null
}

export interface LoginResult {
  access_token: string
  token_type: string
  role: string
  username: string
  department: string
  authorized_departments: string[]
}

export interface ContractOut extends ContractQualityFields {
  id: number
  filename: string
  contract_type: string
  status: ContractStatus
  created_at: string
}

export interface ParseResult extends ContractQualityFields {
  contract_id: number
  elements: Record<string, unknown>
  text_length: number
  total_pages?: number | null
  missing_pages?: number[]
}

// 交叉验证 / 冲突消解项（后端审查态动态结果，不落库，随 audit 响应返回）
export interface CrossCheckOut {
  id: string
  from_agent: 'legal' | 'finance' | 'system'
  to_agent: 'legal' | 'finance' | 'system'
  trigger: string
  action: string
  verdict: 'conflict' | 'watch' | 'confirmed'
  note: string
  category: string
}

export interface AuditResult {
  contract_id: number
  risk_count?: number
  task_id?: string
  job_id?: number
  batch_id?: number
  status: AuditStatus
  error_code?: string | null
  error_message?: string | null
  retryable?: boolean
  cross_checks?: CrossCheckOut[]
  requires_review?: boolean
  ocr_confidence?: number | null
  review_reason?: string | null
}

export interface RiskOut {
  id: number
  agent: 'legal' | 'finance' | 'system'
  level: 'high' | 'medium' | 'low'
  category: string
  original_text: string
  risk_reason: string
  basis: string
  suggestion: string
  confidence: number
  tier: 'green' | 'yellow' | 'red' // 人工干预档位
  review_status: 'pending' | 'confirmed' | 'ignored' | 'to_modify'
  rag_sources: Array<{ content: string; source: string; score: number }> // RAG 检索溯源
  evidence_status: 'supported' | 'partially_supported' | 'unsupported' | string
  original_text_verified: boolean | null
  requires_manual_review: boolean
  support_relation_status: 'supported' | 'unclear' | 'contradicted' | string
  support_validation_reason: string
  support_validator_version: string
  secondary_review_status?: 'not_required' | 'confirmed' | 'rejected' | 'conflict' | 'manual_required'
  secondary_review_reason?: string
  applicability_status?: 'applicable' | 'unknown_as_of' | 'expired' | 'not_yet_effective' | 'unresolved' | string
  applicability_reason_codes?: string[]
  rule_executions?: Array<{
    rule_id?: string
    rule_version?: string
    status?: string
    reason_code?: string
    calculation?: string
  }>
  decision_trace?: {
    status?: string
    reason_codes?: string[]
  }
  collaboration_trace?: {
    discovered_by?: 'legal' | 'finance' | 'system' | string
    reviewed_by?: string[]
    corrected?: boolean
    conflict?: boolean
  } | null
}
