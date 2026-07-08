// 权限与审计接口适配壳。
import client from './client'
import { MOCK_ENABLED, mockRespond } from '@/mock'
import {
  ACCESS_MATRIX,
  ACCESS_MODULES,
  AUDIT_LOGS,
  LLM_CALL_ROWS,
  type AccessRole,
  type AuditLogRow,
  type LlmCallRow,
} from '@/mock/admin'

export type { LlmCallRow } from '@/mock/admin'

export async function getAccessMatrix(): Promise<{ modules: string[]; roles: AccessRole[] }> {
  if (MOCK_ENABLED.admin) return mockRespond({ modules: ACCESS_MODULES, roles: ACCESS_MATRIX })
  return client.get('/admin/access-matrix')
}

export async function getAuditLogs(): Promise<AuditLogRow[]> {
  if (MOCK_ENABLED.admin) return mockRespond(AUDIT_LOGS.map((l) => ({ ...l })))
  return client.get('/admin/audit-logs')
}

export async function getLlmCalls(): Promise<LlmCallRow[]> {
  if (MOCK_ENABLED.admin) return mockRespond(LLM_CALL_ROWS.map((l) => ({ ...l })))
  return client.get('/admin/llm-calls')
}
