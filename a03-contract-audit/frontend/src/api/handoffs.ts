import client from './client'

export interface Handoff {
  contract_id: number
  filename: string
  contract_type: string
  audit_job_id: number | null
  department: string
  contract_status: string
  state: 'draft' | 'submitted' | 'accepted' | 'returned'
  version: number
  assigned_to: number | null
  reason: string
  can_submit: boolean
  can_accept: boolean
  can_return: boolean
  can_review: boolean
  review_reason_code: string
}

export function getHandoffs(): Promise<{ state: string; items: Handoff[] }> {
  return client.get('/handoffs')
}

export function actOnHandoff(row: Handoff, action: 'submit' | 'accept' | 'return', reason = ''): Promise<Handoff> {
  return client.post(`/handoffs/${row.contract_id}`, { action, reason, expected_version: row.version })
}
