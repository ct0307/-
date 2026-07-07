// 权限与审计 mock：权限矩阵(7模块×3角色) + 审计日志
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
  { key: 'legal', label: '法务主管', perms: ['读写', '读写', '读写', '只读', '读写', '只读', '无'] },
  { key: 'finance', label: '财务主管', perms: ['读写', '读写', '读写', '读写', '只读', '无', '无'] },
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
  { id: 'L2051', user: '曾庆豪', role: '法务主管', action: '确认风险并生成整改', target: 'risk:8', time: '2026-07-06 14:25', ip: '10.12.3.42' },
  { id: 'L2050', user: '曾庆豪', role: '法务主管', action: '触发合规审查', target: 'contract:72', time: '2026-07-06 14:22', ip: '10.12.3.42' },
  { id: 'L2049', user: '陈嘉禾', role: '财务主管', action: '上传合同', target: 'contract:71', time: '2026-07-06 10:15', ip: '10.12.3.88' },
  { id: 'L2048', user: '王督政', role: '系统管理员', action: '新增审查规则', target: 'rule:R06', time: '2026-07-05 17:30', ip: '10.12.3.10' },
  { id: 'L2047', user: '王督政', role: '系统管理员', action: '修改角色权限', target: 'role:finance', time: '2026-07-05 16:05', ip: '10.12.3.10' },
  { id: 'L2046', user: '曾庆豪', role: '法务主管', action: '导出风险报告', target: 'contract:70', time: '2026-07-05 15:12', ip: '10.12.3.42' },
  { id: 'L2045', user: '陈嘉禾', role: '财务主管', action: '登录系统', target: 'chenjh', time: '2026-07-05 09:02', ip: '10.12.3.88' },
]
