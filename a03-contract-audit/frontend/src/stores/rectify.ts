import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { RiskOut } from '@/api/types'

export type RectifyStatus = '待处理' | '处理中' | '已闭环'

export interface Rectification {
  id: string
  contract: string
  risk: string
  level: RiskOut['level']
  owner: string
  status: RectifyStatus
  created: string
  due: string
  note: string
}

let seq = 0
function nextId() {
  seq += 1
  return `RC${String(seq).padStart(3, '0')}`
}

export const useRectifyStore = defineStore('rectify', () => {
  // 预置几条演示整改项（含"演示数据"语义，页面会标注）
  const items = ref<Rectification[]>([
    {
      id: nextId(),
      contract: '软件开发外包合同（示例）',
      risk: '缺失违约责任条款',
      level: 'high',
      owner: '曾庆豪',
      status: '处理中',
      created: '2026-07-02',
      due: '2026-07-10',
      note: '已联系业务部门补充违约责任条款草案。',
    },
    {
      id: nextId(),
      contract: '采购合同（示例）',
      risk: '合同金额未标注币种',
      level: 'medium',
      owner: '陈嘉禾',
      status: '待处理',
      created: '2026-07-04',
      due: '2026-07-12',
      note: '',
    },
  ])

  const total = computed(() => items.value.length)
  const countByStatus = computed(() => ({
    待处理: items.value.filter((r) => r.status === '待处理').length,
    处理中: items.value.filter((r) => r.status === '处理中').length,
    已闭环: items.value.filter((r) => r.status === '已闭环').length,
  }))
  const openCount = computed(() => items.value.filter((r) => r.status !== '已闭环').length)

  // 从一条确认的风险生成整改项（AuditView 复核闭环调用）
  function addFromRisk(risk: RiskOut, contract: string, owner: string) {
    const today = new Date().toISOString().slice(0, 10)
    const due = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10)
    items.value.unshift({
      id: nextId(),
      contract,
      risk: risk.category,
      level: risk.level,
      owner,
      status: '待处理',
      created: today,
      due,
      note: risk.suggestion,
    })
  }

  function setStatus(id: string, status: RectifyStatus) {
    const it = items.value.find((r) => r.id === id)
    if (it) it.status = status
  }

  return { items, total, countByStatus, openCount, addFromRisk, setStatus }
})
