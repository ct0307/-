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
import {
  AuditTaskError,
  isAuditPendingStatus,
  waitForAuditTerminal,
} from '@/utils/audit-progress'
import {
  createAuditIdempotencyKey,
  createUploadIdempotencyKey,
} from '@/utils/idempotency'

export type UploadStatus = 'uploading' | 'upload_failed' | 'parsing' | 'parse_failed' | 'parsed'

export interface UploadRecord {
  localId: string
  filename: string
  contractId: number | null
  status: UploadStatus
  errorCode: string
  errorMessage: string
}

interface ActiveAudit {
  owner: string
  contractId: number
  filename: string
  idempotencyKey: string
  contractType: string
  dimensions: string[]
  jobId?: number
  batchId?: number
}

const ACTIVE_AUDIT_STORAGE_KEY = 'qijian-active-audit'

function readActiveAudit(): ActiveAudit | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(ACTIVE_AUDIT_STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<ActiveAudit>
    const currentOwner = window.localStorage.getItem('username') || ''
    if (
      value.owner !== currentOwner
      || !Number.isInteger(value.contractId)
      || typeof value.filename !== 'string'
      || typeof value.idempotencyKey !== 'string'
      || typeof value.contractType !== 'string'
      || !Array.isArray(value.dimensions)
      || !value.dimensions.every(item => typeof item === 'string')
    ) {
      window.localStorage.removeItem(ACTIVE_AUDIT_STORAGE_KEY)
      return null
    }
    return value as ActiveAudit
  } catch {
    window.localStorage.removeItem(ACTIVE_AUDIT_STORAGE_KEY)
    return null
  }
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

function isMissingPersistedAudit(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const response = (error as { response?: { status?: unknown } }).response
  return response?.status === 404
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
  const activeAudit = ref<ActiveAudit | null>(readActiveAudit())
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
  const hasActiveAudit = computed(() => activeAudit.value !== null)

  function saveActiveAudit(value: ActiveAudit | null) {
    activeAudit.value = value
    if (typeof window === 'undefined') return
    if (value) {
      window.localStorage.setItem(ACTIVE_AUDIT_STORAGE_KEY, JSON.stringify(value))
    } else {
      window.localStorage.removeItem(ACTIVE_AUDIT_STORAGE_KEY)
    }
  }

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
    saveActiveAudit(null)
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
      const idempotencyKey = await createUploadIdempotencyKey(file)
      const c = await uploadContract(file, contractType, idempotencyKey)
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
    if (busy.value) throw new Error('当前任务处理中，请稍后再试')
    const currentContractId = contractId.value
    const selectedDimensions = dimensions ?? []
    busy.value = true
    try {
      const owner = typeof window === 'undefined' ? '' : window.localStorage.getItem('username') || ''
      const pending = activeAudit.value
      const recovery: ActiveAudit = pending
        && pending.owner === owner
        && pending.contractId === currentContractId
        ? pending
        : {
            owner,
            contractId: currentContractId,
            filename: filename.value,
            idempotencyKey: await createAuditIdempotencyKey(),
            contractType,
            dimensions: selectedDimensions,
          }
      saveActiveAudit(recovery)
      _auditAbort = new AbortController()
      const initial = recovery.jobId
        ? await getAuditStatus(currentContractId, recovery.jobId, _auditAbort.signal)
        : await auditContract(
            currentContractId,
            recovery.contractType,
            recovery.dimensions,
            recovery.idempotencyKey,
            _auditAbort.signal,
          )
      saveActiveAudit({
        ...recovery,
        jobId: initial.job_id,
        batchId: initial.batch_id,
      })
      const res = isAuditPendingStatus(initial.status)
        ? await waitForAuditTerminal(
            (signal) => getAuditStatus(currentContractId, initial.job_id, signal),
            { signal: _auditAbort.signal },
          )
        : await waitForAuditTerminal(
            async () => initial,
            { intervalMs: 0, maxAttempts: 1, signal: _auditAbort.signal },
          )
      applyQuality(res)
      crossChecks.value = res.cross_checks ?? []
      risks.value = await getRisks(currentContractId, res.job_id ?? initial.job_id)
      step.value = 2
      saveActiveAudit(null)
      return res
    } catch (error) {
      if (error instanceof AuditTaskError || isMissingPersistedAudit(error)) saveActiveAudit(null)
      throw error
    } finally {
      busy.value = false
      _auditAbort = null
    }
  }

  async function resumeActiveAudit() {
    const recovery = activeAudit.value
    if (!recovery) return null
    contractId.value = recovery.contractId
    filename.value = recovery.filename
    busy.value = true
    _auditAbort = new AbortController()
    try {
      const initial = recovery.jobId
        ? await getAuditStatus(recovery.contractId, recovery.jobId, _auditAbort.signal)
        : await auditContract(
            recovery.contractId,
            recovery.contractType,
            recovery.dimensions,
            recovery.idempotencyKey,
            _auditAbort.signal,
          )
      if (!recovery.jobId && initial.job_id) {
        saveActiveAudit({
          ...recovery,
          jobId: initial.job_id,
          batchId: initial.batch_id,
        })
      }
      const result = await waitForAuditTerminal(
        (signal) => getAuditStatus(recovery.contractId, initial.job_id, signal),
        { signal: _auditAbort.signal },
      )
      applyQuality(result)
      crossChecks.value = result.cross_checks ?? []
      risks.value = await getRisks(recovery.contractId, result.job_id ?? initial.job_id)
      step.value = 2
      saveActiveAudit(null)
      return result
    } catch (error) {
      if (error instanceof AuditTaskError || isMissingPersistedAudit(error)) saveActiveAudit(null)
      throw error
    } finally {
      busy.value = false
      _auditAbort = null
    }
  }

  async function loadCompletedAudit(selectedContractId: number, selectedFilename: string) {
    if (busy.value) throw new Error('当前任务处理中，请稍后再试')
    busy.value = true
    try {
      const initial = await getAuditStatus(selectedContractId)
      const result = await waitForAuditTerminal(
        async () => initial,
        { intervalMs: 0, maxAttempts: 1 },
      )
      const loadedRisks = await getRisks(selectedContractId, result.job_id)

      contractId.value = selectedContractId
      filename.value = selectedFilename
      elements.value = null
      applyQuality(result)
      crossChecks.value = result.cross_checks ?? []
      risks.value = loadedRisks
      step.value = 2
      return result
    } finally {
      busy.value = false
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
    hasActiveAudit,
    reset,
    uploadAndParse,
    retryParse,
    selectParsedContract,
    runAudit,
    resumeActiveAudit,
    loadCompletedAudit,
    abortAudit,
    setRiskStatus,
  }
})
