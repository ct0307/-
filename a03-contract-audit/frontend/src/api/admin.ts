// 权限与审计接口适配壳。
import { MOCK_ENABLED, mockRespond } from '@/mock'
import {
  ACCESS_MATRIX,
  ACCESS_MODULES,
  AUDIT_LOGS,
  type AccessRole,
  type AuditLogRow,
} from '@/mock/admin'

export async function getAccessMatrix(): Promise<{ modules: string[]; roles: AccessRole[] }> {
  if (MOCK_ENABLED.admin) return mockRespond({ modules: ACCESS_MODULES, roles: ACCESS_MATRIX })
  return { modules: [], roles: [] }
}

export async function getAuditLogs(): Promise<AuditLogRow[]> {
  if (MOCK_ENABLED.admin) return mockRespond(AUDIT_LOGS.map((l) => ({ ...l })))
  return []
}
