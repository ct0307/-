// 审查历史 mock：14 行台账
export interface HistoryRow {
  id: string
  name: string
  type: string
  submitter: string
  time: string
  level: '高风险' | '中风险' | '低风险'
  riskCount: number
  status: '合规' | '待整改' | '已整改'
}

export const HISTORY_ROWS: HistoryRow[] = [
  { id: 'C2026072', name: '某科技软件开发外包合同', type: '软件开发外包合同', submitter: '曾庆豪', time: '2026-07-06 14:22', level: '高风险', riskCount: 5, status: '待整改' },
  { id: 'C2026071', name: '办公设备采购合同', type: '采购合同', submitter: '陈嘉禾', time: '2026-07-06 10:15', level: '中风险', riskCount: 3, status: '待整改' },
  { id: 'C2026070', name: '云服务技术服务合同', type: '技术服务合同', submitter: '曾庆豪', time: '2026-07-05 16:40', level: '低风险', riskCount: 1, status: '已整改' },
  { id: 'C2026069', name: '厂房租赁合同', type: '租赁合同', submitter: '王督政', time: '2026-07-05 09:30', level: '中风险', riskCount: 2, status: '合规' },
  { id: 'C2026068', name: '市场推广服务合同', type: '技术服务合同', submitter: '陈嘉禾', time: '2026-07-04 15:12', level: '高风险', riskCount: 4, status: '待整改' },
  { id: 'C2026067', name: '原材料采购框架协议', type: '采购合同', submitter: '曾庆豪', time: '2026-07-04 11:08', level: '低风险', riskCount: 1, status: '已整改' },
  { id: 'C2026066', name: '软件维护服务合同', type: '技术服务合同', submitter: '陈嘉禾', time: '2026-07-03 14:50', level: '中风险', riskCount: 2, status: '合规' },
  { id: 'C2026065', name: '劳务派遣合同', type: '劳动合同', submitter: '王督政', time: '2026-07-03 10:20', level: '高风险', riskCount: 6, status: '待整改' },
  { id: 'C2026064', name: '设备融资租赁合同', type: '租赁合同', submitter: '陈嘉禾', time: '2026-07-02 16:33', level: '中风险', riskCount: 3, status: '已整改' },
  { id: 'C2026063', name: 'App 定制开发合同', type: '软件开发外包合同', submitter: '曾庆豪', time: '2026-07-02 09:45', level: '低风险', riskCount: 1, status: '合规' },
  { id: 'C2026062', name: '广告投放服务合同', type: '技术服务合同', submitter: '陈嘉禾', time: '2026-07-01 15:20', level: '中风险', riskCount: 2, status: '待整改' },
  { id: 'C2026061', name: '办公家具采购合同', type: '采购合同', submitter: '王督政', time: '2026-07-01 11:00', level: '低风险', riskCount: 1, status: '已整改' },
  { id: 'C2026060', name: '数据中心运维合同', type: '技术服务合同', submitter: '曾庆豪', time: '2026-06-30 14:15', level: '高风险', riskCount: 4, status: '待整改' },
  { id: 'C2026059', name: '员工培训服务合同', type: '技术服务合同', submitter: '陈嘉禾', time: '2026-06-30 10:05', level: '低风险', riskCount: 1, status: '合规' },
]
