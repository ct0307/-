// 报表接口适配壳：MOCK_ENABLED.reports 为真走 mock，否则走后端。
// 后端补齐 /reports/* 后关开关即可，ReportsView 零改动。
import client from './client'
import { MOCK_ENABLED, mockRespond } from '@/mock'
import { REPORT_DATA, type RangeKey, type ReportData } from '@/mock/reports'

export async function getReportData(range: RangeKey): Promise<ReportData> {
  if (MOCK_ENABLED.reports) {
    return mockRespond(REPORT_DATA[range], 'reports')
  }
  return client.get('/reports/summary', { params: { range } })
}
