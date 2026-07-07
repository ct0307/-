// 双 Agent 协作页 mock：Agent 元数据（对齐后端 auditor._AGENTS）+ 一套预设协作演示数据。
// 真实会话（audit-session 有风险数据）时页面用真实数据；无会话时降级到此处 DEMO_* 展示。

export type AgentKey = 'legal' | 'finance'

// Agent 名片元数据：职责维度 / RAG 检索主题 / prompt 侧重。
// 与 backend/app/services/audit/auditor.py 的 _AGENTS 定义保持一致。
export interface AgentMeta {
  key: AgentKey
  name: string
  role: string
  icon: string // 全局注册的 Element Plus 图标名
  accent: string // CSS 变量名，泳道/名片主色
  focus: string[] // 关注维度
  ragTopics: string[] // 定向 RAG 检索主题
  promptBias: string // 角色化 prompt 侧重描述
}

export const AGENTS: Record<AgentKey, AgentMeta> = {
  legal: {
    key: 'legal',
    name: '法务专家 Agent',
    role: '查合规',
    icon: 'Stamp',
    accent: 'var(--brass)',
    focus: ['违约责任', '争议解决', '知识产权归属', '保密条款', '验收标准', '合同主体资格'],
    ragTopics: ['违约 违约责任 违约金', '争议 仲裁 诉讼 管辖', '知识产权 著作权 保密', '合同主体 甲方 乙方'],
    promptBias: '只输出法律条款合规维度的风险，禁止越界评价财务事项，每条须附原文引用与法规依据。',
  },
  finance: {
    key: 'finance',
    name: '财务会计 Agent',
    role: '对账目',
    icon: 'Coin',
    accent: 'var(--sage)',
    focus: ['合同金额', '付款节点', '发票绑定', '违约金上限', '币种与大小写一致性', '预算合规'],
    ragTopics: ['金额 价款 币种', '付款 发票 结算', '违约金 上限 赔偿', '期限 履约'],
    promptBias: '只输出金额与付款维度的风险，聚焦资金安全与预算合规，每条须给出置信度与修改建议。',
  },
}

// —— 主从串行协作链路（对齐组员建议的 SOP：法务先行 → 共享上下文 → 财务二次加工 → 交叉验证 → 统一决策）——
// 与双泳道平行展示不同，这里强调 Agent 之间的数据依赖与先后次序。
export interface ChainStage {
  key: string
  title: string
  owner: AgentKey | 'router' | 'both' // 归属：法务/财务/路由分发/双方协同
  desc: string
  output?: string // 该阶段产出、传递给下游的关键数据（共享上下文）
}

export const COLLAB_CHAIN: ChainStage[] = [
  {
    key: 'route',
    title: '① 输入分发',
    owner: 'router',
    desc: 'Router 拆解合同，分离"法律条款"与"金额/节点/税点"，分派给两个专家 Agent。',
    output: '合同要素 JSON（甲乙方 / 标的 / 金额 / 收付款节点 / 关键条款）',
  },
  {
    key: 'legal',
    title: '② 法务先行',
    owner: 'legal',
    desc: '法务 Agent 检索法规 RAG，做前置合规判断：违约责任、争议管辖、关联交易识别。',
    output: '合法条款结构化结论 + 关联交易标记（写入共享记忆窗口）',
  },
  {
    key: 'finance',
    title: '③ 财务二次加工',
    owner: 'finance',
    desc: '财务 Agent 读取法务输出（不重复解析），基于价格与支付条款检索财务 RAG，校验现金流与税率。',
    output: '资金/税务风险结论 + 收款账户与价格公允性判定',
  },
  {
    key: 'cross',
    title: '④ 交叉验证',
    owner: 'both',
    desc: '关联交易触发财务价格公允性复查；收款账户异常回传法务提示法律风险。冲突进入联合推理。',
    output: '冲突项清单 + 联合思维链推理结论',
  },
  {
    key: 'decide',
    title: '⑤ 统一决策',
    owner: 'router',
    desc: '中央节点综合两位专家结论，给出打分、修改建议与风险预警，输出一份报告。',
    output: '综合审查报告（风险分级 / 修改建议 / 人工介入档位）',
  },
]

// —— 交叉验证 / 冲突消解场景（协同核心）——
// 展示跨 Agent 触发：一个 Agent 的发现强制拉起另一个 Agent 的定向复查。
export interface CrossCheck {
  id: string
  from: AgentKey
  to: AgentKey
  trigger: string // 触发条件
  action: string // 触发后的动作
  verdict: 'conflict' | 'confirmed' | 'watch' // 冲突 / 已确认 / 待观察
  note: string // 联合推理结论
}

export const CROSS_CHECKS: CrossCheck[] = [
  {
    id: 'X1',
    from: 'legal',
    to: 'finance',
    trigger: '法务识别合同为「关联方交易」',
    action: '强制触发财务 Agent 对交易价格做「公允性」审查',
    verdict: 'conflict',
    note: '法务认可付款方式，但财务判定价格显著偏离市场公允价，存在利益输送嫌疑 → 联合推理判高风险，需三员会审。',
  },
  {
    id: 'X2',
    from: 'finance',
    to: 'legal',
    trigger: '财务发现「收款账户与合同主体不一致」',
    action: '阻断流程并回传法务 Agent 提示法律与舞弊风险',
    verdict: 'conflict',
    note: '收款账户为第三方个人账户，法务复核认定存在合同主体资格与资金安全双重风险 → 建议驳回。',
  },
  {
    id: 'X3',
    from: 'legal',
    to: 'finance',
    trigger: '法务认可分期支付条款合法',
    action: '财务二次核对支付节奏是否匹配现金流规划',
    verdict: 'watch',
    note: '条款合法但首付比例 60% 偏高，财务提示资金前置风险 → 建议协商分期，列为待观察。',
  },
]

// —— 分级风险人工干预（对齐组员建议：绿/黄/红三档，动态决定人工介入深度）——
// 不盲目要求人工审全部，按 AI 置信度 + 风险等级 + 冲突情况分档，红档强制三员会审。
export type TierKey = 'green' | 'yellow' | 'red'

export interface TierMeta {
  key: TierKey
  label: string
  accent: string // CSS 变量
  criteria: string // 分档判定标准
  intervention: string // 人工介入策略
  approvers: string // 审批人配置
  actionLabel: string // 操作按钮文案
}

export const RISK_TIERS: Record<TierKey, TierMeta> = {
  green: {
    key: 'green',
    label: '绿档 · 低风险',
    accent: 'var(--sage)',
    criteria: '低风险且 AI 置信度 > 95%',
    intervention: 'AI 自动审查通过，推送至「自动归档待签批」池',
    approvers: '审批人一键签批',
    actionLabel: '一键签批',
  },
  yellow: {
    key: 'yellow',
    label: '黄档 · 中风险',
    accent: 'var(--amber)',
    criteria: '中风险，或存在个别条款歧义 / 财税不一致',
    intervention: 'AI 输出详细建议，必须人工逐条核实',
    approvers: '经办人逐条核实',
    actionLabel: '逐条核实',
  },
  red: {
    key: 'red',
    label: '红档 · 高风险',
    accent: 'var(--seal)',
    criteria: '高风险，或涉及关联交易 / 重大赔偿 / 税法争议 / 跨 Agent 冲突',
    intervention: '系统强制三员会审，人工参与方可解锁下一步',
    approvers: '法务专家 + 财务专家 + 合规总监',
    actionLabel: '发起三员会审',
  },
}

// —— 演示态风险数据（无真实会话时降级使用），结构对齐 api/types.ts 的 RiskOut ——
export interface DemoRisk {
  id: number
  agent: AgentKey
  level: 'high' | 'medium' | 'low'
  category: string
  original_text: string
  basis: string
  suggestion: string
  confidence: number
  review_status: 'pending' | 'confirmed' | 'ignored' | 'to_modify'
}

export const DEMO_CONTRACT = '软件开发外包合同（演示）.pdf'

export const DEMO_RISKS: DemoRisk[] = [
  {
    id: 1,
    agent: 'legal',
    level: 'high',
    category: '条款缺失',
    original_text: '（全文未检出违约责任相关条款）',
    basis: '合同应明确违约情形及违约金计算方式（依据：《民法典》第577条 违约责任）',
    suggestion: '补充违约责任条款，明确违约情形、违约金计算方式及赔偿范围。',
    confidence: 88,
    review_status: 'pending',
  },
  {
    id: 2,
    agent: 'legal',
    level: 'medium',
    category: '条款缺失',
    original_text: '（全文未检出争议解决条款）',
    basis: '争议解决方式应明确约定（依据：《民事诉讼法》管辖规定）',
    suggestion: '增加争议解决条款，明确仲裁机构或诉讼管辖法院。',
    confidence: 82,
    review_status: 'pending',
  },
  {
    id: 3,
    agent: 'legal',
    level: 'high',
    category: '主体缺失',
    original_text: '（乙方主体资格信息不完整）',
    basis: '合同主体应完整明确，否则可能影响合同效力（依据：合同主体条款标准）',
    suggestion: '核对并补全乙方名称及主体资格信息。',
    confidence: 90,
    review_status: 'confirmed',
  },
  {
    id: 4,
    agent: 'finance',
    level: 'high',
    category: '要素缺失',
    original_text: '合同总价：人民币 __________ 元',
    basis: '合同金额应大小写一致并标注币种（依据：企业财务合规规则 F-02）',
    suggestion: '明确合同金额，大小写一致并标注币种，避免结算争议。',
    confidence: 85,
    review_status: 'pending',
  },
  {
    id: 5,
    agent: 'finance',
    level: 'medium',
    category: '付款风险',
    original_text: '首付款为合同总额的 60%，签订后 3 日内支付。',
    basis: '预付比例偏高，资金前置风险大（依据：企业付款节点规则 F-05）',
    suggestion: '建议降低首付比例或绑定交付里程碑分期支付，控制资金前置风险。',
    confidence: 76,
    review_status: 'pending',
  },
  {
    id: 6,
    agent: 'finance',
    level: 'low',
    category: '要素缺失',
    original_text: '（未检出签订日期）',
    basis: '签订日期是生效与期限计算起点（依据：期限履约规则 F-08）',
    suggestion: '补充合同签订日期，作为生效与期限计算的起点。',
    confidence: 70,
    review_status: 'ignored',
  },
]
