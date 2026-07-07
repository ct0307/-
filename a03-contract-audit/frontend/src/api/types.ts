// 后端返回的数据类型（与 backend/app/schemas 对齐）

export interface LoginResult {
  access_token: string
  token_type: string
  role: string
}

export interface ContractOut {
  id: number
  filename: string
  contract_type: string
  status: string
  created_at: string
}

export interface ParseResult {
  contract_id: number
  elements: Record<string, unknown>
  text_length: number
}

export interface AuditResult {
  contract_id: number
  risk_count?: number
  task_id?: string
  status: string
}

export interface RiskOut {
  id: number
  agent: 'legal' | 'finance'
  level: 'high' | 'medium' | 'low'
  category: string
  original_text: string
  basis: string
  suggestion: string
  confidence: number
  review_status: 'pending' | 'confirmed' | 'ignored' | 'to_modify'
}
