// 整改跟踪 mock：演示基线整改项。后端 /rectifications 就绪后由 api 层切换。
import type { RiskOut } from '@/api/types'

export type RectifyStatus = '待处理' | '处理中' | '待复核' | '已闭环' | '待风险接受' | '已接受风险'
export type ContractStage = 'unsigned' | 'signed' | 'unknown'
export type HandlingMethod = 'revision' | 'supplement' | 'performance'

export interface RectificationPlan {
  owner: string
  collaborators: string[]
  due: string
  note: string
  acceptance_criteria: string
  contract_stage: ContractStage
  handling_method: HandlingMethod
}
export interface RectificationParticipant { id: number; username: string; role: string; department: string }
export interface RectificationMaterial { id: number; filename: string; content_sha256: string }
export interface RectificationEvidence { contract_id: number; filename: string; content_sha256: string; description?: string }
export interface RectificationEvent {
  id: number; action: string; actor_id?: number; actor: string; occurred_at: string
  from_status: string | null; to_status: string; snapshot: Record<string, unknown>
}

export interface Rectification {
  id: string
  contract: string
  risk: string
  level: RiskOut['level']
  owner: string
  status: RectifyStatus
  created: string
  due: string
  note: string
  risk_id?: number | null
  resolution: string
  review_comment: string
  submitted_at: string | null
  closed_at: string | null
  contract_id?: number | null
  department?: string
  acceptance_criteria?: string
  collaborators?: string[]
  contract_stage?: ContractStage
  handling_method?: HandlingMethod
  before_text?: string
  original_text_verified?: boolean
  after_text?: string
  evidence?: RectificationEvidence[]
  events?: RectificationEvent[]
  submitted_by?: string | number | null
  reviewed_by?: string | number | null
  reviewed_at?: string | null
  acceptance_reason?: string
  residual_risk?: string
  accepted_at?: string | null
  escalation_reason?: string
  escalated_at?: string | null
  escalated_by?: string | number | null
  version?: number
  can_manage?: boolean
  can_execute?: boolean
  can_review?: boolean
  can_accept?: boolean
  can_escalate?: boolean
  can_reopen?: boolean
}

// 新建整改项入参（对齐后端 RectificationCreate）
export interface RectificationCreate extends RectificationPlan {
  contract: string
  risk: string
  level: RiskOut['level']
  owner: string
  status?: RectifyStatus
  created?: string
  risk_id?: number
}

export interface RectificationUpdate {
  status: RectifyStatus
  version: number
  resolution?: string
  review_comment?: string
  evidence_contract_ids?: number[]
  after_text?: string
  acceptance_reason?: string
  residual_risk?: string
}

export const RECTIFY_ROWS: Rectification[] = [
  {
    id: 'RC001',
    contract: '软件开发外包合同（示例）',
    risk: '缺失违约责任条款',
    level: 'high',
    owner: '曾庆豪',
    status: '处理中',
    created: '2026-07-02',
    due: '2026-07-10',
    note: '已联系业务部门补充违约责任条款草案。',
    resolution: '',
    review_comment: '',
    submitted_at: null,
    closed_at: null,
  },
  {
    id: 'RC002',
    contract: '采购合同（示例）',
    risk: '合同金额未标注币种',
    level: 'medium',
    owner: '陈嘉禾',
    status: '待处理',
    created: '2026-07-04',
    due: '2026-07-12',
    note: '',
    resolution: '',
    review_comment: '',
    submitted_at: null,
    closed_at: null,
  },
]
