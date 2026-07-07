import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { RiskOut } from '@/api/types'
import {
  auditContract,
  getRisks,
  parseContract,
  updateRiskStatus,
  uploadContract,
} from '@/api/contract'

// 审查会话状态：承接 上传→解析→审查→复核 真实闭环，供 AuditView 及子组件共享。
export const useAuditSessionStore = defineStore('auditSession', () => {
  const contractId = ref<number | null>(null)
  const filename = ref('')
  const elements = ref<Record<string, unknown> | null>(null)
  const risks = ref<RiskOut[]>([])
  const busy = ref(false)
  // 0 未上传 / 1 已解析 / 2 已审查
  const step = ref(0)

  const riskCount = computed(() => risks.value.length)
  const reviewingCount = computed(() => risks.value.filter((r) => r.review_status === 'pending').length)
  const levelCounts = computed(() => ({
    high: risks.value.filter((r) => r.level === 'high').length,
    medium: risks.value.filter((r) => r.level === 'medium').length,
    low: risks.value.filter((r) => r.level === 'low').length,
  }))

  function reset() {
    contractId.value = null
    filename.value = ''
    elements.value = null
    risks.value = []
    step.value = 0
  }

  // —— 真实接口链路（不改后端契约）——
  async function uploadAndParse(file: File, contractType = '') {
    busy.value = true
    try {
      const c = await uploadContract(file, contractType)
      contractId.value = c.id
      filename.value = c.filename
      const parsed = await parseContract(c.id)
      elements.value = parsed.elements
      risks.value = []
      step.value = 1
      return c
    } finally {
      busy.value = false
    }
  }

  async function runAudit() {
    if (!contractId.value) return
    busy.value = true
    try {
      await auditContract(contractId.value)
      risks.value = await getRisks(contractId.value)
      step.value = 2
    } finally {
      busy.value = false
    }
  }

  async function setRiskStatus(risk: RiskOut, status: RiskOut['review_status']) {
    await updateRiskStatus(risk.id, status)
    risk.review_status = status
  }

  return {
    contractId,
    filename,
    elements,
    risks,
    busy,
    step,
    riskCount,
    reviewingCount,
    levelCounts,
    reset,
    uploadAndParse,
    runAudit,
    setRiskStatus,
  }
})
