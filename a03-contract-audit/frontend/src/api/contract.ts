// 合同相关接口封装
import client from './client'
import type { AuditResult, ContractOut, LoginResult, ParseResult, RiskOut } from './types'

export function login(username: string, password: string): Promise<LoginResult> {
  // 后端 OAuth2PasswordRequestForm 要求 form 编码
  const form = new URLSearchParams()
  form.append('username', username)
  form.append('password', password)
  return client.post('/auth/login', form)
}

export function uploadContract(file: File, contractType = ''): Promise<ContractOut> {
  const fd = new FormData()
  fd.append('file', file)
  const params = contractType ? { contract_type: contractType } : {}
  // 上传接口单独设 120s 超时：大文件需经过加密存储 + 文本解析，30s 默认值不够
  return client.post('/contracts/upload', fd, { params, timeout: 120_000 })
}

export function parseContract(id: number): Promise<ParseResult> {
  return client.post(`/contracts/${id}/parse`)
}

export function auditContract(
  id: number,
  contractType: string,
  dimensions?: string[],
  signal?: AbortSignal,
): Promise<AuditResult> {
  const body = { contract_type: contractType, dimensions: dimensions ?? [] }
  return client.post(`/contracts/${id}/audit`, body, { signal, timeout: 180_000 })
}

export function getAuditStatus(id: number, signal?: AbortSignal): Promise<AuditResult> {
  return client.get(`/contracts/${id}/audit-status`, { signal })
}

export function getRisks(id: number): Promise<RiskOut[]> {
  return client.get(`/contracts/${id}/risks`)
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

export function updateRiskStatus(riskId: number, riskStatus: RiskOut['review_status']): Promise<unknown> {
  return client.patch(`/risks/${riskId}/status`, { review_status: riskStatus })
}
