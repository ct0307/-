import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { RiskOut } from '@/api/types'
import {
  getRectifications,
  createRectification,
  updateRectificationStatus,
  updateRectificationPlan,
  escalateRectification,
} from '@/api/rectify'
import type { Rectification, RectificationPlan, RectificationUpdate, RectifyStatus } from '@/mock/rectify'

export type { Rectification, RectifyStatus } from '@/mock/rectify'

export const useRectifyStore = defineStore('rectify', () => {
  const items = ref<Rectification[]>([])
  const loading = ref(false)
  const error = ref('')
  let loaded = false
  let generation = 0

  const total = computed(() => items.value.length)
  const countByStatus = computed(() => ({
    待处理: items.value.filter((r) => r.status === '待处理').length,
    处理中: items.value.filter((r) => r.status === '处理中').length,
    待复核: items.value.filter((r) => r.status === '待复核').length,
    已闭环: items.value.filter((r) => r.status === '已闭环').length,
    待风险接受: items.value.filter((r) => r.status === '待风险接受').length,
    已接受风险: items.value.filter((r) => r.status === '已接受风险').length,
  }))
  const openCount = computed(() => items.value.filter((r) => !['已闭环', '已接受风险'].includes(r.status)).length)

  // 拉取整改项列表（首次进入或强制刷新）
  async function load(force = false) {
    if (loaded && !force) return
    const requestGeneration = generation
    loading.value = true
    error.value = ''
    try {
      const nextItems = await getRectifications()
      if (requestGeneration !== generation) return
      items.value = nextItems
      loaded = true
    } catch (e) {
      if (requestGeneration === generation) {
        error.value = e instanceof Error ? e.message : '整改项加载失败'
      }
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  // 从一条确认的风险生成整改项（AuditView 复核闭环调用）
  async function addFromRisk(risk: RiskOut, contract: string, plan: RectificationPlan) {
    const requestGeneration = generation
    const item = await createRectification({
      contract,
      risk: risk.category,
      level: risk.level,
      ...plan,
      status: '待处理',
      risk_id: risk.id,
    })
    if (requestGeneration !== generation) return
    items.value = [item, ...items.value]
    return item
  }

  async function update(id: string, payload: RectificationUpdate) {
    const requestGeneration = generation
    const updated = await updateRectificationStatus(id, payload)
    if (requestGeneration !== generation) return
    const index = items.value.findIndex((r) => r.id === id)
    if (index >= 0) items.value[index] = updated
  }

  async function setStatus(id: string, status: RectifyStatus) {
    return update(id, { status, version: items.value.find(item => item.id === id)?.version ?? 1 })
  }

  async function savePlan(id: string, plan: RectificationPlan, version: number) {
    const requestGeneration = generation
    const updated = await updateRectificationPlan(id, { ...plan, version })
    if (requestGeneration !== generation) return
    const index = items.value.findIndex(item => item.id === id)
    if (index >= 0) items.value[index] = updated
  }

  async function escalate(id: string, reason: string, version: number) {
    const requestGeneration = generation
    const updated = await escalateRectification(id, reason, version)
    if (requestGeneration !== generation) return
    const index = items.value.findIndex(item => item.id === id)
    if (index >= 0) items.value[index] = updated
  }

  function reset() {
    generation += 1
    items.value = []
    loading.value = false
    error.value = ''
    loaded = false
  }

  return { items, loading, error, total, countByStatus, openCount, load, addFromRisk, update, setStatus, savePlan, escalate, reset }
})
