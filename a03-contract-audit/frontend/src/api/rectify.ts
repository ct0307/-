// 整改跟踪接口适配壳。
// mock 开：本地内存态模拟增改（演示可交互）；mock 关：走后端 /rectifications。
import client from './client'
import { MOCK_ENABLED, mockRespond } from '@/mock'
import {
  RECTIFY_ROWS,
  type Rectification,
  type RectificationCreate,
  type RectifyStatus,
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
    }
    mockItems = [item, ...mockItems]
    return mockRespond(item)
  }
  return client.post('/rectifications', payload)
}

export async function updateRectificationStatus(
  id: string,
  status: RectifyStatus,
): Promise<Rectification> {
  if (MOCK_ENABLED.rectify) {
    const it = mockItems.find((r) => r.id === id)
    if (it) it.status = status
    return mockRespond({ ...(it as Rectification) })
  }
  return client.patch(`/rectifications/${id}`, { status })
}
