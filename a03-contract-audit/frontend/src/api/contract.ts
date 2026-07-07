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
  return client.post('/contracts/upload', fd, { params })
}

export function parseContract(id: number): Promise<ParseResult> {
  return client.post(`/contracts/${id}/parse`)
}

export function auditContract(id: number): Promise<AuditResult> {
  return client.post(`/contracts/${id}/audit`)
}

export function getRisks(id: number): Promise<RiskOut[]> {
  return client.get(`/contracts/${id}/risks`)
}

export function updateRiskStatus(riskId: number, status: RiskOut['review_status']): Promise<unknown> {
  return client.patch(`/risks/${riskId}/status`, { review_status: status })
}
