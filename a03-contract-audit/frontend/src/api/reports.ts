// 报表接口适配壳：MOCK_ENABLED.reports 为真走 mock，否则走后端。
import client from './client'
import { MOCK_ENABLED, mockRespond } from '@/mock'
import { REPORT_DATA, type RangeKey, type ReportData } from '@/mock/reports'

export async function getReportData(range: RangeKey): Promise<ReportData> {
  if (MOCK_ENABLED.reports) {
    return mockRespond(REPORT_DATA[range], 'reports')
  }
  return client.get('/reports/summary', { params: { range } })
}

/** 合同要素汇总：甲方 / 合同标的 / 收付款节点 + 风险统计。*/
export interface ContractMeta {
  id: number
  filename: string
  contract_type: string
  department: string
  party_a: string
  subject: string
  payment_terms: string
  amount: string
  risk_high: number
  risk_medium: number
  risk_low: number
  risk_total: number
  status: string
  job_id?: number | null
  job_status?: string | null
  created_at?: string | null
  coverage?: { planned?: number; completed?: number } | null
  review_reason?: string | null
  payment_analysis?: PaymentAnalysis
}

export interface PaymentAnalysis {
  status: string
  calculation: string
  total_percentage?: string | null
  events: { quote: string; clause_id: string; condition: string; percentage: string | null; base: string }[]
  issues: { kind: string; message: string; quotes: string[]; clause_ids: string[] }[]
}

export interface ReportRisk {
  id: number
  contract_id: number
  filename: string
  category: string
  level: string
  agent: string
  original_text: string
  risk_reason: string
  basis: string
  suggestion: string
  evidence_status: string | null
  original_text_verified: boolean | null
  review_status: string
  contract_evidence: { clause_id?: string; match_type?: string; anchors?: { page?: number; page_number?: number }[] }[]
  rag_sources: { source?: string; title?: string; content?: string; quote?: string }[]
  support_validation_reason?: string
  applicability_status?: string
  applicability_reason_codes?: string[]
  rule_executions?: Array<{
    rule_id?: string
    rule_version?: string
    status?: string
    reason?: string
  }>
  decision_trace?: {
    status?: string
    reason_codes?: string[]
  }
}

export interface ReportSnapshot {
  schema_version?: string
  state?: string
  operations?: {
    metric_version: string
    as_of_date: string
    high_risk_contracts: number
    pending_risk_count: number
    overdue_count: number
    unknown_due_count: number
    amount_note: string
    risk_count_basis: string
    departments: { department: string; contract_count: number; risk_count: number; high_risk_contracts: number; high_risk_rate: number; contract_ids: number[]; high_risk_contract_ids: number[] }[]
    overdue_actions: { id: number; risk: string; owner: string; overdue_days: number; due: string }[]
  }
  report_id: string
  generated_at: string
  contract_ids: number[]
  contracts: ContractMeta[]
  summary: { total: number; completed: number; review_required: number; failed: number; unreviewed: number; running: number; risks: number; high: number; medium: number; low: number; supported: number }
  risks: ReportRisk[]
  matrix: { categories: string[]; rows: { contract_id: number; filename: string; counts: number[] }[] }
  rectifications: { id: number; risk_id: number; contract: string; risk: string; owner: string; status: string; due: string }[]
  notes: string[]
}

export function previewReport(contractIds: number[] | null): Promise<ReportSnapshot> {
  return client.post('/reports/preview', { contract_ids: contractIds })
}

export async function exportEvidenceReport(snapshot: ReportSnapshot, format: 'xlsx' | 'docx', all = false): Promise<void> {
  const params = new URLSearchParams({ format, report_id: snapshot.report_id })
  if (!all) snapshot.contract_ids.forEach(id => params.append('contract_ids', String(id)))
  let data: ArrayBuffer
  try {
    data = await client.get(`/reports/export?${params}`, { responseType: 'arraybuffer' })
  } catch (error) {
    const failure = error as { response?: { status: number }; message?: string }
    if (failure.response?.status === 409) throw new Error('数据已变化，请重新生成预览后导出')
    throw error
  }
  const blob = new Blob([data], { type: format === 'xlsx' ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `合同审查证据报告_${snapshot.contract_ids.length}份_${snapshot.report_id.slice(0, 12)}.${format}`
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function getContractsMetadata(): Promise<ContractMeta[]> {
  return client.get('/reports/contracts-metadata')
}

/** 导出 Excel 风险台账，触发浏览器下载。*/
export async function exportRiskLedger(): Promise<void> {
  const data: ArrayBuffer = await client.get('/reports/export', {
    responseType: 'arraybuffer',
  })
  const blob = new Blob([data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `风险台账_${new Date().toISOString().slice(0, 10)}.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}
