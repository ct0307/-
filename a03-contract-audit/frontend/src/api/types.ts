// 后端返回的数据类型（与 backend/app/schemas 对齐）

export interface LoginResult {
  access_token: string
  token_type: string
  role: string
  username: string
  department: string
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

// 交叉验证 / 冲突消解项（后端审查态动态结果，不落库，随 audit 响应返回）
export interface CrossCheckOut {
  id: string
  from_agent: 'legal' | 'finance'
  to_agent: 'legal' | 'finance'
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
  status: string
  cross_checks?: CrossCheckOut[]
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
  tier: 'green' | 'yellow' | 'red' // 人工干预档位
  review_status: 'pending' | 'confirmed' | 'ignored' | 'to_modify'
  rag_sources: Array<{ content: string; source: string; score: number }> // RAG 检索溯源
}
