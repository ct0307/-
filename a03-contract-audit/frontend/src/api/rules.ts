// 规则与模板接口适配壳。当前 mock 本地态（增删在页面内存进行）。
import { MOCK_ENABLED, mockRespond } from '@/mock'
import {
  AUDIT_RULES,
  CONTRACT_TEMPLATES,
  type AuditRule,
  type ContractTemplate,
} from '@/mock/rules'

export async function getRules(): Promise<AuditRule[]> {
  if (MOCK_ENABLED.rules) return mockRespond(AUDIT_RULES.map((r) => ({ ...r })))
  return []
}

export async function getTemplates(): Promise<ContractTemplate[]> {
  if (MOCK_ENABLED.rules) return mockRespond(CONTRACT_TEMPLATES.map((t) => ({ ...t })))
  return []
}
