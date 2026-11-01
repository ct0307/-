// 整改跟踪接口适配壳。
// mock 开：本地内存态模拟增改（演示可交互）；mock 关：走后端 /rectifications。
import client from './client'
import { MOCK_ENABLED, mockRespond } from '@/mock'
import {
  RECTIFY_ROWS,
  type Rectification,
  type RectificationCreate,
  type RectificationUpdate,
  type RectificationPlan,
  type RectificationParticipant,
  type RectificationMaterial,
} from '@/mock/rectify'

// mock 模式下的内存态（复制基线，避免污染常量），并维护自增序号
let mockItems: Rectification[] = RECTIFY_ROWS.map((r) => ({ ...r }))
let mockSeq = RECTIFY_ROWS.length
function nextMockId(): string {
  mockSeq += 1
  return `RC${String(mockSeq).padStart(3, '0')}`
}

export async function getRectifications(): Promise<Rectification[]> {
  if (MOCK_ENABLED.rectify) {
    return mockRespond(mockItems.map((r) => ({ ...r })))
  }
  return client.get('/rectifications')
}

export async function createRectification(payload: RectificationCreate): Promise<Rectification> {
  if (MOCK_ENABLED.rectify) {
    const today = new Date().toISOString().slice(0, 10)
    const due = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10)
    const item: Rectification = {
      id: nextMockId(),
      contract: payload.contract,
      risk: payload.risk,
      level: payload.level,
      owner: payload.owner,
      status: payload.status ?? '待处理',
      created: payload.created ?? today,
      due: payload.due ?? due,
      note: payload.note ?? '',
      risk_id: payload.risk_id ?? null,
      resolution: '',
      review_comment: '',
      submitted_at: null,
      closed_at: null,
      collaborators: payload.collaborators,
      acceptance_criteria: payload.acceptance_criteria,
      contract_stage: payload.contract_stage,
      handling_method: payload.handling_method,
      version: 1,
      evidence: [], events: [],
    }
    mockItems = [item, ...mockItems]
    return mockRespond(item)
  }
  return client.post('/rectifications', payload)
}

export async function updateRectificationStatus(
  id: string,
  payload: RectificationUpdate,
): Promise<Rectification> {
  if (MOCK_ENABLED.rectify) {
    const it = mockItems.find((r) => r.id === id)
    if (!it) throw new Error('整改项不存在')
    if (payload.version !== (it.version ?? 1)) throw new Error('任务已更新，请刷新后重试')
    const previous = it.status
    const { evidence_contract_ids: _materialIds, ...fields } = payload
    Object.assign(it, fields, { version: payload.version + 1 })
    it.status = payload.status
    if (payload.resolution !== undefined) it.resolution = payload.resolution
    if (payload.review_comment !== undefined) it.review_comment = payload.review_comment
    if (payload.status === '待复核') it.submitted_at = new Date().toISOString()
    if (payload.status === '已闭环') it.closed_at = new Date().toISOString()
    if (payload.status === '处理中') it.closed_at = null
    if (payload.status === '已接受风险') { it.closed_at = null; it.accepted_at = new Date().toISOString() }
    it.events = [...(it.events ?? []), { id: Date.now(), action: '演示状态变更', actor: '演示用户', occurred_at: new Date().toISOString(), from_status: previous, to_status: it.status, snapshot: { ...payload } }]
    return mockRespond({ ...(it as Rectification) })
  }
  return client.patch(`/rectifications/${id}`, payload)
}

export async function getRectificationParticipants(riskId: number): Promise<RectificationParticipant[]> {
  if (MOCK_ENABLED.rectify) return mockRespond([{ id: 1, username: '演示责任人', role: 'business', department: '演示部门' }])
  return client.get('/rectifications/participants', { params: { risk_id: riskId } })
}

export async function getRectificationMaterials(riskId: number): Promise<RectificationMaterial[]> {
  if (MOCK_ENABLED.rectify) return mockRespond([])
  return client.get('/rectifications/materials', { params: { risk_id: riskId } })
}

export async function updateRectificationPlan(id: string, payload: RectificationPlan & { version: number }): Promise<Rectification> {
  if (MOCK_ENABLED.rectify) {
    const item = mockItems.find(row => row.id === id)
    if (!item) throw new Error('整改项不存在')
    if (payload.version !== (item.version ?? 1)) throw new Error('任务已更新，请刷新后重试')
    Object.assign(item, payload, { version: payload.version + 1 })
    return mockRespond({ ...item })
  }
  return client.patch(`/rectifications/${id}/plan`, payload)
}

export async function escalateRectification(id: string, reason: string, version: number): Promise<Rectification> {
  if (MOCK_ENABLED.rectify) throw new Error('演示模式不登记正式升级，请连接后端')
  return client.post(`/rectifications/${id}/escalate`, { reason, version })
}
