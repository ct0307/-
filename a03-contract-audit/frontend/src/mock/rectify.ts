// 整改跟踪 mock：演示基线整改项。后端 /rectifications 就绪后由 api 层切换。
import type { RiskOut } from '@/api/types'

export type RectifyStatus = '待处理' | '处理中' | '待复核' | '已闭环'

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
}

// 新建整改项入参（对齐后端 RectificationCreate）
export interface RectificationCreate {
  contract: string
  risk: string
  level: RiskOut['level']
  owner: string
  status?: RectifyStatus
  created?: string
  due?: string
  note?: string
  risk_id?: number
}

export interface RectificationUpdate {
  status: RectifyStatus
  resolution?: string
  review_comment?: string
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
