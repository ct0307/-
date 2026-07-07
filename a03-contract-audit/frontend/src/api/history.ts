// 审查历史接口适配壳。后端补齐 GET /contracts 后可切换。
import client from './client'
import { MOCK_ENABLED, mockRespond } from '@/mock'
import { HISTORY_ROWS, type HistoryRow } from '@/mock/history'

export async function getHistory(): Promise<HistoryRow[]> {
  if (MOCK_ENABLED.history) {
    return mockRespond(HISTORY_ROWS, 'history')
  }
  return client.get('/contracts')
}
