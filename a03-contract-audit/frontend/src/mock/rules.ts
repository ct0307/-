// 规则与模板 mock：审查规则库(6) + 合同模板库(3)
export interface AuditRule {
  id: string
  name: string
  dimension: string
  level: 'high' | 'medium' | 'low'
  agent: string
  desc: string
  builtin: boolean
}

export interface ContractTemplate {
  id: string
  name: string
  type: string
  clauses: string[]
  builtin: boolean
}

export const AUDIT_RULES: AuditRule[] = [
  { id: 'R01', name: '违约责任缺失检测', dimension: '违约责任分析', level: 'high', agent: '法务 Agent', desc: '全文未检出违约责任相关条款时，判高风险并提示补充。', builtin: true },
  { id: 'R02', name: '争议解决条款检测', dimension: '争议解决条款', level: 'medium', agent: '法务 Agent', desc: '未约定仲裁或诉讼管辖时，判中风险。', builtin: true },
  { id: 'R03', name: '合同金额币种校验', dimension: '金额与付款条款', level: 'high', agent: '财务 Agent', desc: '金额缺失或未标注币种时判高风险。', builtin: true },
  { id: 'R04', name: '签订日期完整性', dimension: '法律条款合规性', level: 'low', agent: '法务 Agent', desc: '未检出签订日期时判低风险，提示补充。', builtin: true },
  { id: 'R05', name: '主体资格完整性', dimension: '风险条款识别', level: 'high', agent: '法务 Agent', desc: '甲乙方主体信息不完整时判高风险。', builtin: true },
  { id: 'R06', name: '保密条款审查', dimension: '保密条款审查', level: 'medium', agent: '法务 Agent', desc: '涉及商业秘密但无保密条款时判中风险。', builtin: false },
]

export const CONTRACT_TEMPLATES: ContractTemplate[] = [
  {
    id: 'T01',
    name: '软件开发外包合同模板',
    type: '软件开发外包合同',
    clauses: ['甲乙双方主体信息', '开发范围与交付标准', '知识产权归属', '付款节点与方式', '违约责任', '保密条款', '争议解决'],
    builtin: true,
  },
  {
    id: 'T02',
    name: '采购合同模板',
    type: '采购合同',
    clauses: ['货物名称规格数量', '合同金额与币种', '交付与验收', '付款条款', '质量保证', '违约责任', '争议解决'],
    builtin: true,
  },
  {
    id: 'T03',
    name: '技术服务合同模板',
    type: '技术服务合同',
    clauses: ['服务内容与标准', '服务期限', '服务费用', '知识产权', '保密义务', '违约责任'],
    builtin: false,
  },
]
