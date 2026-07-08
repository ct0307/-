// 权限与审计 mock：权限矩阵(7模块×4角色) + 审计日志 + LLM 调用记录
export type Perm = '读写' | '只读' | '无'

export const ACCESS_MODULES = [
  '工作台',
  '合同审查',
  '整改跟踪',
  '多维报表',
  '法规知识库',
  '规则与模板',
  '权限与审计',
]

export interface AccessRole {
  key: string
  label: string
  perms: Perm[] // 与 ACCESS_MODULES 一一对应
}

export const ACCESS_MATRIX: AccessRole[] = [
  { key: 'business', label: '业务人员', perms: ['只读', '读写', '只读', '只读', '只读', '无', '无'] },
  { key: 'legal', label: '法务主管', perms: ['只读', '读写', '读写', '只读', '读写', '只读', '无'] },
  { key: 'finance', label: '财务主管', perms: ['只读', '读写', '读写', '读写', '只读', '无', '无'] },
  { key: 'admin', label: '系统管理员', perms: ['读写', '读写', '读写', '读写', '读写', '读写', '读写'] },
]

export interface AuditLogRow {
  id: string
  user: string
  role: string
  action: string
  target: string
  time: string
  ip: string
}

export const AUDIT_LOGS: AuditLogRow[] = [
  { id: 'L2051', user: '曾庆豪', role: 'legal', action: '确认风险并生成整改', target: 'risk:8', time: '2026-07-06 14:25', ip: '10.12.3.42' },
  { id: 'L2050', user: '曾庆豪', role: 'legal', action: '触发合规审查', target: 'contract:72', time: '2026-07-06 14:22', ip: '10.12.3.42' },
  { id: 'L2049', user: '陈嘉禾', role: 'finance', action: '上传合同', target: 'contract:71', time: '2026-07-06 10:15', ip: '10.12.3.88' },
  { id: 'L2048', user: '王督政', role: 'admin', action: '新增审查规则', target: 'rule:R06', time: '2026-07-05 17:30', ip: '10.12.3.10' },
  { id: 'L2047', user: '王督政', role: 'admin', action: '修改角色权限', target: 'role:finance', time: '2026-07-05 16:05', ip: '10.12.3.10' },
  { id: 'L2046', user: '曾庆豪', role: 'legal', action: '导出风险报告', target: 'contract:70', time: '2026-07-05 15:12', ip: '10.12.3.42' },
  { id: 'L2045', user: '陈嘉禾', role: 'finance', action: '登录系统', target: 'chenjh', time: '2026-07-05 09:02', ip: '10.12.3.88' },
]

// LLM 调用记录：每次 Agent chat 调用的元数据，供算力对比与可解释性审计
export interface LlmCallRow {
  id: string
  contract_id: number | null
  agent: string        // legal / finance
  provider: string     // deepseek / qwen / openclaw
  model: string
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
  mode: string         // llm / mock
  time: string
}

export const LLM_CALL_ROWS: LlmCallRow[] = [
  { id: 'LC0012', contract_id: 6, agent: 'finance', provider: 'deepseek', model: 'deepseek-chat', prompt_tokens: 612, completion_tokens: 748, latency_ms: 7140, mode: 'llm', time: '2026-07-06 14:23' },
  { id: 'LC0011', contract_id: 6, agent: 'legal',   provider: 'deepseek', model: 'deepseek-chat', prompt_tokens: 541, completion_tokens: 693, latency_ms: 6520, mode: 'llm', time: '2026-07-06 14:22' },
  { id: 'LC0010', contract_id: 4, agent: 'finance', provider: 'deepseek', model: 'deepseek-chat', prompt_tokens: 588, completion_tokens: 712, latency_ms: 6890, mode: 'llm', time: '2026-07-05 11:30' },
  { id: 'LC0009', contract_id: 4, agent: 'legal',   provider: 'deepseek', model: 'deepseek-chat', prompt_tokens: 502, completion_tokens: 644, latency_ms: 6210, mode: 'llm', time: '2026-07-05 11:29' },
  { id: 'LC0008', contract_id: 7, agent: 'finance', provider: 'deepseek', model: 'deepseek-chat', prompt_tokens: 571, completion_tokens: 680, latency_ms: 6640, mode: 'llm', time: '2026-07-05 10:15' },
  { id: 'LC0007', contract_id: 7, agent: 'legal',   provider: 'deepseek', model: 'deepseek-chat', prompt_tokens: 488, completion_tokens: 601, latency_ms: 5980, mode: 'llm', time: '2026-07-05 10:14' },
  { id: 'LC0006', contract_id: 2, agent: 'finance', provider: 'openclaw', model: 'openclaw-v2',   prompt_tokens: 612, completion_tokens: 748, latency_ms: 1820, mode: 'llm', time: '2026-07-04 16:20' },
  { id: 'LC0005', contract_id: 2, agent: 'legal',   provider: 'openclaw', model: 'openclaw-v2',   prompt_tokens: 541, completion_tokens: 693, latency_ms: 1640, mode: 'llm', time: '2026-07-04 16:19' },
  { id: 'LC0004', contract_id: 1, agent: 'finance', provider: 'openclaw', model: 'openclaw-v2',   prompt_tokens: 503, completion_tokens: 621, latency_ms: 1530, mode: 'llm', time: '2026-07-04 14:08' },
  { id: 'LC0003', contract_id: 1, agent: 'legal',   provider: 'openclaw', model: 'openclaw-v2',   prompt_tokens: 441, completion_tokens: 580, latency_ms: 1410, mode: 'llm', time: '2026-07-04 14:07' },
  { id: 'LC0002', contract_id: 3, agent: 'finance', provider: 'qwen',     model: 'qwen3-14b',     prompt_tokens: 598, completion_tokens: 724, latency_ms: 4320, mode: 'llm', time: '2026-07-03 09:45' },
  { id: 'LC0001', contract_id: 3, agent: 'legal',   provider: 'qwen',     model: 'qwen3-14b',     prompt_tokens: 511, completion_tokens: 658, latency_ms: 4110, mode: 'llm', time: '2026-07-03 09:44' },
]
