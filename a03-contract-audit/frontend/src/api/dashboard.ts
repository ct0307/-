// 工作台接口适配壳：MOCK_ENABLED.dashboard 为真走 mock，否则走后端 /dashboard/summary。
import client from './client'
import { MOCK_ENABLED, mockRespond } from '@/mock'
import { DASHBOARD_SUMMARY, type DashboardSummary } from '@/mock/dashboard'

export async function getDashboardSummary(): Promise<DashboardSummary> {
  if (MOCK_ENABLED.dashboard) {
    return mockRespond(DASHBOARD_SUMMARY)
  }
  return client.get('/dashboard/summary')
}
