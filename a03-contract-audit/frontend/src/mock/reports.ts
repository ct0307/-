// 报表页 mock 数据：按 月/季/年 三档，各含 KPI + 趋势 + 风险分布 + 部门 + TOP5
export type RangeKey = 'month' | 'quarter' | 'year'

export interface ReportData {
  kpi: { total: number; pass: number; risk: number; time: string }
  kpiTrend: { total: string; pass: string; risk: string; time: string }
  trend: { labels: string[]; total: number[]; pass: number[]; risk: number[] }
  donut: { name: string; value: number }[]
  depts: { name: string; risk: number; money: string }[]
  tops: { name: string; value: number }[]
}

export const REPORT_DATA: Record<RangeKey, ReportData> = {
  month: {
    kpi: { total: 148, pass: 87, risk: 32, time: '4.2min' },
    kpiTrend: { total: '+12.5%', pass: '+3.2%', risk: '-8.1%', time: '效率 +18%' },
    trend: {
      labels: ['第1周', '第2周', '第3周', '第4周', '第5周', '第6周', '第7周'],
      total: [18, 24, 21, 30, 27, 35, 32],
      pass: [15, 20, 18, 26, 23, 30, 28],
      risk: [4, 6, 5, 7, 6, 8, 7],
    },
    donut: [
      { name: '高风险', value: 32 },
      { name: '中风险', value: 56 },
      { name: '低风险', value: 74 },
    ],
    depts: [
      { name: '采购中心', risk: 42, money: '¥1,280万' },
      { name: '研发外包部', risk: 35, money: '¥960万' },
      { name: '市场运营部', risk: 28, money: '¥620万' },
      { name: '行政人事部', risk: 15, money: '¥210万' },
    ],
    tops: [
      { name: '违约责任缺失', value: 38 },
      { name: '付款条款模糊', value: 31 },
      { name: '争议解决未约定', value: 26 },
      { name: '知识产权归属不清', value: 19 },
      { name: '保密条款缺失', value: 14 },
    ],
  },
  quarter: {
    kpi: { total: 426, pass: 89, risk: 88, time: '4.0min' },
    kpiTrend: { total: '+9.3%', pass: '+4.1%', risk: '-6.2%', time: '效率 +22%' },
    trend: {
      labels: ['1月', '2月', '3月', '4月', '5月', '6月', '7月'],
      total: [52, 61, 58, 70, 66, 78, 74],
      pass: [45, 54, 51, 63, 58, 70, 66],
      risk: [12, 15, 14, 18, 16, 20, 18],
    },
    donut: [
      { name: '高风险', value: 88 },
      { name: '中风险', value: 152 },
      { name: '低风险', value: 210 },
    ],
    depts: [
      { name: '采购中心', risk: 118, money: '¥3,860万' },
      { name: '研发外包部', risk: 96, money: '¥2,740万' },
      { name: '市场运营部', risk: 74, money: '¥1,820万' },
      { name: '行政人事部', risk: 41, money: '¥680万' },
    ],
    tops: [
      { name: '违约责任缺失', value: 102 },
      { name: '付款条款模糊', value: 86 },
      { name: '争议解决未约定', value: 71 },
      { name: '知识产权归属不清', value: 53 },
      { name: '保密条款缺失', value: 40 },
    ],
  },
  year: {
    kpi: { total: 1286, pass: 87, risk: 326, time: '4.2min' },
    kpiTrend: { total: '+15.8%', pass: '+5.6%', risk: '-11.4%', time: '效率 +25%' },
    trend: {
      labels: ['Q1', 'Q2', 'Q3', 'Q4', '上年Q3', '上年Q4', '本季'],
      total: [286, 342, 318, 340, 260, 295, 74],
      pass: [248, 300, 278, 300, 220, 254, 66],
      risk: [68, 82, 76, 100, 60, 72, 18],
    },
    donut: [
      { name: '高风险', value: 326 },
      { name: '中风险', value: 452 },
      { name: '低风险', value: 508 },
    ],
    depts: [
      { name: '采购中心', risk: 386, money: '¥1.28亿' },
      { name: '研发外包部', risk: 312, money: '¥9,600万' },
      { name: '市场运营部', risk: 248, money: '¥6,200万' },
      { name: '行政人事部', risk: 136, money: '¥2,100万' },
    ],
    tops: [
      { name: '违约责任缺失', value: 342 },
      { name: '付款条款模糊', value: 286 },
      { name: '争议解决未约定', value: 231 },
      { name: '知识产权归属不清', value: 178 },
      { name: '保密条款缺失', value: 132 },
    ],
  },
}
