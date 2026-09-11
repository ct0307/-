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

export interface LookupItem {
  id: number
  category: string
  value: string
  sort_order: number
}

export interface DepartmentScopeUser {
  id: number
  username: string
  role: string
  department: string
  authorized_departments: string[]
}

export function getDepartmentScopeUsers(): Promise<DepartmentScopeUser[]> {
  return client.get('/admin/users/department-scopes')
}

export function updateUserDepartments(
  userId: number,
  departments: string[],
): Promise<DepartmentScopeUser> {
  return client.put(`/admin/users/${userId}/departments`, { departments })
}

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

// ── 下拉选项配置（department / contract_type）──
export function getLookups(category: string): Promise<LookupItem[]> {
  return client.get(`/admin/lookups/${category}`)
}

export function createLookup(category: string, value: string): Promise<LookupItem> {
  return client.post('/admin/lookups', { category, value, sort_order: 0 })
}

export function deleteLookup(id: number): Promise<void> {
  return client.delete(`/admin/lookups/${id}`)
}
