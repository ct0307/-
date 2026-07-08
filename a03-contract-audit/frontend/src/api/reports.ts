// 报表接口适配壳：MOCK_ENABLED.reports 为真走 mock，否则走后端。
import client from './client'
import { MOCK_ENABLED, mockRespond } from '@/mock'
import { REPORT_DATA, type RangeKey, type ReportData } from '@/mock/reports'

export async function getReportData(range: RangeKey): Promise<ReportData> {
  if (MOCK_ENABLED.reports) {
    return mockRespond(REPORT_DATA[range], 'reports')
  }
  return client.get('/reports/summary', { params: { range } })
}

/** 导出 Excel 风险台账，触发浏览器下载。*/
export async function exportRiskLedger(): Promise<void> {
  const data: ArrayBuffer = await client.get('/reports/export', {
    responseType: 'arraybuffer',
  })
  const blob = new Blob([data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `风险台账_${new Date().toISOString().slice(0, 10)}.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}
