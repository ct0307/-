// 合同相关接口封装
import client from './client'
import type { AuditResult, ContractDocument, ContractOut, LoginResult, ParseResult, RiskOut } from './types'

export const PARSE_TIMEOUT_MS = 150_000

export function login(username: string, password: string): Promise<LoginResult> {
  // 后端 OAuth2PasswordRequestForm 要求 form 编码
  const form = new URLSearchParams()
  form.append('username', username)
  form.append('password', password)
  return client.post('/auth/login', form)
}

export function uploadContract(
  file: File,
  contractType: string,
  idempotencyKey: string,
  department = '',
): Promise<ContractOut> {
  const fd = new FormData()
  fd.append('file', file)
  const params = { ...(contractType ? { contract_type: contractType } : {}), ...(department ? { department } : {}) }
  // 上传接口单独设 120s 超时：大文件需经过加密存储 + 文本解析，30s 默认值不够
  return client.post('/contracts/upload', fd, {
    params,
    headers: { 'Idempotency-Key': idempotencyKey },
    timeout: 120_000,
  })
}

export function parseContract(id: number): Promise<ParseResult> {
  return client.post(`/contracts/${id}/parse`, undefined, { timeout: PARSE_TIMEOUT_MS })
}

export function getContractDocument(id: number, signal?: AbortSignal): Promise<ContractDocument> {
  return client.get(`/contracts/${id}/document`, { signal })
}

export function auditContract(
  id: number,
  contractType: string,
  dimensions?: string[],
  idempotencyKey?: string,
  signal?: AbortSignal,
): Promise<AuditResult> {
  const body = { contract_type: contractType, dimensions: dimensions ?? [] }
  return client.post(`/contracts/${id}/audit`, body, {
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    signal,
    timeout: 180_000,
  })
}

export function getAuditStatus(
  id: number,
  jobId?: number,
  signal?: AbortSignal,
): Promise<AuditResult> {
  return client.get(`/contracts/${id}/audit-status`, {
    params: jobId ? { job_id: jobId } : undefined,
    signal,
  })
}

export function getRisks(id: number, jobId?: number, signal?: AbortSignal): Promise<RiskOut[]> {
  return client.get(`/contracts/${id}/risks`, {
    params: jobId ? { job_id: jobId } : undefined,
    signal,
  })
}

export interface BatchUploadResult {
  filename: string
  status: 'success' | 'failed'
  contract_id?: number
  error?: string
}

/** 批量上传合同，最多50份，逐文件处理互不影响。*/
export function batchUploadContracts(files: File[], contractType = ''): Promise<BatchUploadResult[]> {
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  const params = contractType ? { contract_type: contractType } : {}
  return client.post('/contracts/batch-upload', fd, { params, timeout: 300_000 })
}

export function updateRiskStatus(riskId: number, riskStatus: RiskOut['review_status'], reviewComment = ''): Promise<{ risk_id: number; review_status: RiskOut['review_status']; human_review?: import('@/utils/risk-evidence').HumanReview }> {
  return client.patch(`/risks/${riskId}/status`, { review_status: riskStatus, review_comment: reviewComment })
}
