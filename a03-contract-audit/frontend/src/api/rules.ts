// 规则与模板接口适配壳。mock 关时走后端 /rules 与 /templates。
import client from './client'
import { MOCK_ENABLED, mockRespond } from '@/mock'
import {
  AUDIT_RULES,
  CONTRACT_TEMPLATES,
  type AuditRule,
  type ContractTemplate,
} from '@/mock/rules'

// mock 内存态：避免污染常量，支持 mock 模式下的增删交互
let mockRules: AuditRule[] = AUDIT_RULES.map((r) => ({ ...r }))
let mockTemplates: ContractTemplate[] = CONTRACT_TEMPLATES.map((t) => ({ ...t }))

export async function getRules(): Promise<AuditRule[]> {
  if (MOCK_ENABLED.rules) return mockRespond(mockRules.map((r) => ({ ...r })))
  return client.get('/rules')
}

export async function createRule(
  payload: Omit<AuditRule, 'id' | 'builtin'>,
): Promise<AuditRule> {
  if (MOCK_ENABLED.rules) {
    const item: AuditRule = { id: `R${Date.now()}`, ...payload, builtin: false }
    mockRules = [item, ...mockRules]
    return mockRespond(item)
  }
  return client.post('/rules', payload)
}

export async function deleteRule(id: string): Promise<void> {
  if (MOCK_ENABLED.rules) {
    mockRules = mockRules.filter((r) => r.id !== id)
    return mockRespond(undefined as unknown as void)
  }
  return client.delete(`/rules/${id}`)
}

export async function getTemplates(): Promise<ContractTemplate[]> {
  if (MOCK_ENABLED.rules) return mockRespond(mockTemplates.map((t) => ({ ...t })))
  return client.get('/templates')
}

export async function createTemplate(
  payload: Omit<ContractTemplate, 'id' | 'builtin'>,
): Promise<ContractTemplate> {
  if (MOCK_ENABLED.rules) {
    const item: ContractTemplate = { id: `T${Date.now()}`, ...payload, builtin: false }
    mockTemplates = [item, ...mockTemplates]
    return mockRespond(item)
  }
  return client.post('/templates', payload)
}

export async function deleteTemplate(id: string): Promise<void> {
  if (MOCK_ENABLED.rules) {
    mockTemplates = mockTemplates.filter((t) => t.id !== id)
    return mockRespond(undefined as unknown as void)
  }
  return client.delete(`/templates/${id}`)
}
