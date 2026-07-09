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

/** 合同要素汇总：甲方 / 合同标的 / 收付款节点 + 风险统计。*/
export interface ContractMeta {
  id: number
  filename: string
  contract_type: string
  department: string
  party_a: string
  subject: string
  payment_terms: string
  amount: string
  risk_high: number
  risk_total: number
  status: string
}

export async function getContractsMetadata(): Promise<ContractMeta[]> {
  return client.get('/reports/contracts-metadata')
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
