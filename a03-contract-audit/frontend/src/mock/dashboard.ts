// 工作台 mock：后端 /dashboard/summary 的形状 + 演示基线值。
// KPI 中「本月审查合同」「合规通过率」等运营指标真实系统需时间序列聚合，
// 当前后端 summary 只给总量/分布，故这些运营基线保留为演示态。

// 对齐后端 dashboard_summary 返回结构
export interface DashboardSummary {
  total_contracts: number
  total_risks: number
  level_distribution: Record<string, number> // {高/中/低: n}
  category_distribution: { category: string; count: number }[]
  contract_status: Record<string, number>
  review_status: Record<string, number> // {待处理/已确认/已忽略/需修改: n}
  agent_distribution: Record<string, number>
}

// mock 基线：数值与前端旧写死值一致，切真接口后由 summary 派生
export const DASHBOARD_SUMMARY: DashboardSummary = {
  total_contracts: 148,
  total_risks: 312,
  level_distribution: { 高: 42, 中: 128, 低: 142 },
  category_distribution: [
    { category: '付款条款', count: 58 },
    { category: '违约责任', count: 47 },
    { category: '知识产权', count: 39 },
    { category: '争议解决', count: 31 },
  ],
  contract_status: { done: 120, auditing: 18, parsed: 6, uploaded: 4 },
  review_status: { 待处理: 96, 已确认: 148, 已忽略: 42, 需修改: 26 },
  agent_distribution: { '法务专家 Agent': 186, '财务会计 Agent': 126 },
}
