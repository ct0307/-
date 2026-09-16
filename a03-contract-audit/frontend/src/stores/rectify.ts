import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { RiskOut } from '@/api/types'
import {
  getRectifications,
  createRectification,
  updateRectificationStatus,
} from '@/api/rectify'
import type { Rectification, RectifyStatus } from '@/mock/rectify'

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
    已闭环: items.value.filter((r) => r.status === '已闭环').length,
  }))
  const openCount = computed(() => items.value.filter((r) => r.status !== '已闭环').length)

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
  async function addFromRisk(risk: RiskOut, contract: string, owner: string) {
    const requestGeneration = generation
    const item = await createRectification({
      contract,
      risk: risk.category,
      level: risk.level,
      owner,
      status: '待处理',
      note: risk.suggestion,
      risk_id: risk.id,
    })
    if (requestGeneration !== generation) return
    items.value = [item, ...items.value]
  }

  async function setStatus(id: string, status: RectifyStatus) {
    const requestGeneration = generation
    const updated = await updateRectificationStatus(id, status)
    if (requestGeneration !== generation) return
    const it = items.value.find((r) => r.id === id)
    if (it) it.status = updated.status
  }

  function reset() {
    generation += 1
    items.value = []
    loading.value = false
    error.value = ''
    loaded = false
  }

  return { items, loading, error, total, countByStatus, openCount, load, addFromRisk, setStatus, reset }
})
