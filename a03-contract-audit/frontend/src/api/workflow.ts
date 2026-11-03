import client from './client'

export interface WorkflowView {
  state: 'not_available' | 'stale' | 'awaiting_review' | 'review_changed' | 'published'
  message?: string
  version?: number; generation?: number; can_finalize?: boolean; review_fingerprint?: string
  groups?: Array<{ issue_id: string; category: string; original_text: string; claim_ids: string[]; agents: string[]; level: string; views: Array<Record<string, unknown>> }>
  conflicts?: Array<{ id: string; trigger: string; note: string }>
  directed_reviews?: Array<{ check_id: string; target_agent: string; status: string; verdict: string; reason_code: string }>
  pending_count?: number; requires_quality_ack?: boolean
  missing_rectifications?: Array<{ risk_id: number; category: string }>
  budget?: { calls?: number; charged_tokens?: number; max_calls?: number; max_tokens?: number }
}
export function getWorkflow(contractId: number): Promise<WorkflowView> { return client.get(`/workflows/${contractId}`) }
export function finalizeWorkflow(contractId: number, payload: Record<string, unknown>): Promise<WorkflowView> { return client.post(`/workflows/${contractId}/finalize`, payload) }
