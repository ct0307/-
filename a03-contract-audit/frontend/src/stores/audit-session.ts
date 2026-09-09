import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import type { AuditResult, CrossCheckOut, ParseResult, RiskOut } from '@/api/types'
import {
  auditContract,
  getAuditStatus,
  getRisks,
  parseContract,
  updateRiskStatus,
  uploadContract,
} from '@/api/contract'
import { waitForAuditTerminal } from '@/utils/audit-progress'

export type UploadStatus = 'uploading' | 'upload_failed' | 'parsing' | 'parse_failed' | 'parsed'

export interface UploadRecord {
  localId: string
  filename: string
  contractId: number | null
  status: UploadStatus
  errorCode: string
  errorMessage: string
}

function errorInfo(error: unknown): { code: string; message: string } {
  if (error && typeof error === 'object') {
    const candidate = error as { code?: unknown; message?: unknown }
    return {
      code: typeof candidate.code === 'string' ? candidate.code : '',
      message: typeof candidate.message === 'string' && candidate.message
        ? candidate.message
        : '上传或解析失败，请稍后重试',
    }
  }
  return { code: '', message: '上传或解析失败，请稍后重试' }
}

// 审查会话状态：承接 上传→解析→审查→复核 真实闭环，供 AuditView 及子组件共享。
export const useAuditSessionStore = defineStore('auditSession', () => {
  const contractId = ref<number | null>(null)
  const filename = ref('')
  const elements = ref<Record<string, unknown> | null>(null)
  const risks = ref<RiskOut[]>([])
  const crossChecks = ref<CrossCheckOut[]>([])
  const requiresReview = ref(false)
  const ocrConfidence = ref<number | null>(null)
  const reviewReason = ref('')
  const busy = ref(false)
  const uploadRecords = ref<UploadRecord[]>([])
  let uploadSequence = 0
  let _auditAbort: AbortController | null = null
  // 0 未上传 / 1 已解析 / 2 已审查
  const step = ref(0)

  const riskCount = computed(() => risks.value.length)
  const reviewingCount = computed(() => risks.value.filter((r) => r.review_status === 'pending').length)
  const levelCounts = computed(() => ({
    high: risks.value.filter((r) => r.level === 'high').length,
    medium: risks.value.filter((r) => r.level === 'medium').length,
    low: risks.value.filter((r) => r.level === 'low').length,
  }))

  function applyQuality(source: ParseResult | AuditResult) {
    requiresReview.value = source.requires_review ?? false
    ocrConfidence.value = source.ocr_confidence ?? null
    reviewReason.value = source.review_reason ?? ''
  }

  function reset() {
    _auditAbort?.abort()
    _auditAbort = null
    contractId.value = null
    filename.value = ''
    elements.value = null
    risks.value = []
    crossChecks.value = []
    requiresReview.value = false
    ocrConfidence.value = null
    reviewReason.value = ''
    busy.value = false
    uploadRecords.value = []
    step.value = 0
  }

  function applyParsedContract(record: UploadRecord, parsed: ParseResult) {
    contractId.value = record.contractId
    filename.value = record.filename
    elements.value = parsed.elements
    risks.value = []
    crossChecks.value = []
    applyQuality(parsed)
    step.value = 1
  }

  async function parseRecord(record: UploadRecord) {
    if (busy.value) throw new Error('当前任务处理中，请稍后再试')
    if (record.contractId === null) throw new Error('合同尚未上传成功，无法解析')
    busy.value = true
    record.status = 'parsing'
    record.errorCode = ''
    record.errorMessage = ''
    try {
      const parsed = await parseContract(record.contractId)
      applyParsedContract(record, parsed)
      record.status = 'parsed'
      return parsed
    } catch (error) {
      const info = errorInfo(error)
      record.status = 'parse_failed'
      record.errorCode = info.code
      record.errorMessage = info.message
      throw error
    } finally {
      busy.value = false
    }
  }

  // —— 真实接口链路（不改后端契约）——
  async function uploadAndParse(file: File, contractType = '') {
    if (busy.value) throw new Error('当前任务处理中，请稍后再试')
    const record = reactive<UploadRecord>({
      localId: `upload-${Date.now()}-${++uploadSequence}`,
      filename: file.name,
      contractId: null,
      status: 'uploading',
      errorCode: '',
      errorMessage: '',
    })
    uploadRecords.value.push(record)
    busy.value = true
    try {
      const c = await uploadContract(file, contractType)
      record.contractId = c.id
      record.filename = c.filename
      record.status = 'parsing'
      const parsed = await parseContract(c.id)
      applyParsedContract(record, parsed)
      record.status = 'parsed'
      return c
    } catch (error) {
      const info = errorInfo(error)
      record.status = record.contractId === null ? 'upload_failed' : 'parse_failed'
      record.errorCode = info.code
      record.errorMessage = info.message
      throw error
    } finally {
      busy.value = false
    }
  }

  async function retryParse(record: UploadRecord) {
    return parseRecord(record)
  }

  async function selectParsedContract(record: UploadRecord) {
    return parseRecord(record)
  }

  async function runAudit(contractType: string, dimensions?: string[]) {
    if (!contractId.value) return
    busy.value = true
    _auditAbort = new AbortController()
    try {
      const initial = await auditContract(
        contractId.value,
        contractType,
        dimensions,
        _auditAbort.signal,
      )
      const res = initial.status === 'auditing'
        ? await waitForAuditTerminal(
            (signal) => getAuditStatus(contractId.value!, signal),
            { signal: _auditAbort.signal },
          )
        : initial
      applyQuality(res)
      crossChecks.value = res.cross_checks ?? []
      risks.value = await getRisks(contractId.value)
      step.value = 2
    } finally {
      busy.value = false
      _auditAbort = null
    }
  }

  function abortAudit() {
    if (_auditAbort) {
      _auditAbort.abort()
      _auditAbort = null
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
    crossChecks,
    requiresReview,
    ocrConfidence,
    reviewReason,
    busy,
    uploadRecords,
    step,
    riskCount,
    reviewingCount,
    levelCounts,
    reset,
    uploadAndParse,
    retryParse,
    selectParsedContract,
    runAudit,
    abortAudit,
    setRiskStatus,
  }
})
