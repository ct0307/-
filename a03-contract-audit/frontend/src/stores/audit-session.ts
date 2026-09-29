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
import { SESSION_KEYS } from '@/utils/session'

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

const ACTIVE_AUDIT_STORAGE_KEY = SESSION_KEYS.activeAudit

function readActiveAudit(): ActiveAudit | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(ACTIVE_AUDIT_STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<ActiveAudit>
    const currentOwner = window.localStorage.getItem(SESSION_KEYS.username) || ''
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
  let generation = 0
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

  function rememberCompleted(selectedContractId: number, selectedFilename: string, jobId?: number) {
    if (typeof window === 'undefined' || !jobId) return
    try {
      localStorage.setItem(SESSION_KEYS.completedAudit, JSON.stringify({
        owner: localStorage.getItem(SESSION_KEYS.username) || '',
        contractId: selectedContractId, filename: selectedFilename, jobId,
      }))
    } catch { /* 浏览器禁用存储不影响已获取的审查结果。 */ }
  }

  async function restoreCompletedAudit() {
    if (step.value >= 2 || busy.value || activeAudit.value) return
    let selected: { owner: string; contractId: number; filename: string; jobId: number }
    try {
      const raw = localStorage.getItem(SESSION_KEYS.completedAudit)
      if (!raw) return
      selected = JSON.parse(raw)
      if (!selected || selected.owner !== localStorage.getItem(SESSION_KEYS.username)
        || !Number.isInteger(selected.contractId) || selected.contractId <= 0
        || !Number.isInteger(selected.jobId) || selected.jobId <= 0 || typeof selected.filename !== 'string') {
        localStorage.removeItem(SESSION_KEYS.completedAudit)
        return
      }
    } catch {
      try { localStorage.removeItem(SESSION_KEYS.completedAudit) } catch { /* 存储不可用时保留页面可用性。 */ }
      return
    }
    try {
      return await loadCompletedAudit(selected.contractId, selected.filename, selected.jobId)
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status
      if (status === 403 || status === 404) {
        try { localStorage.removeItem(SESSION_KEYS.completedAudit) } catch { /* 不覆盖原始请求错误。 */ }
      }
      throw error
    }
  }

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
    generation += 1
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
    if (typeof window !== 'undefined') localStorage.removeItem(SESSION_KEYS.completedAudit)
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
    const requestGeneration = generation
    busy.value = true
    record.status = 'parsing'
    record.errorCode = ''
    record.errorMessage = ''
    try {
      const parsed = await parseContract(record.contractId)
      if (requestGeneration !== generation) return parsed
      applyParsedContract(record, parsed)
      record.status = 'parsed'
      return parsed
    } catch (error) {
      if (requestGeneration === generation) {
        const info = errorInfo(error)
        record.status = 'parse_failed'
        record.errorCode = info.code
        record.errorMessage = info.message
      }
      throw error
    } finally {
      if (requestGeneration === generation) busy.value = false
    }
  }

  // —— 真实接口链路（不改后端契约）——
  async function uploadAndParse(file: File, contractType = '') {
    if (busy.value) throw new Error('当前任务处理中，请稍后再试')
    const requestGeneration = generation
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
      if (requestGeneration !== generation) return
      const c = await uploadContract(file, contractType, idempotencyKey)
      if (requestGeneration !== generation) return c
      record.contractId = c.id
      record.filename = c.filename
      record.status = 'parsing'
      const parsed = await parseContract(c.id)
      if (requestGeneration !== generation) return c
      applyParsedContract(record, parsed)
      record.status = 'parsed'
      return c
    } catch (error) {
      if (requestGeneration === generation) {
        const info = errorInfo(error)
        record.status = record.contractId === null ? 'upload_failed' : 'parse_failed'
        record.errorCode = info.code
        record.errorMessage = info.message
      }
      throw error
    } finally {
      if (requestGeneration === generation) busy.value = false
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
    const requestGeneration = generation
    const selectedDimensions = dimensions ?? []
    busy.value = true
    try {
      const owner = typeof window === 'undefined' ? '' : window.localStorage.getItem(SESSION_KEYS.username) || ''
      const pending = activeAudit.value
      let recovery: ActiveAudit
      if (pending && pending.owner === owner && pending.contractId === currentContractId) {
        recovery = pending
      } else {
        const idempotencyKey = await createAuditIdempotencyKey()
        if (requestGeneration !== generation) return
        recovery = {
            owner,
            contractId: currentContractId,
            filename: filename.value,
            idempotencyKey,
            contractType,
            dimensions: selectedDimensions,
          }
      }
      saveActiveAudit(recovery)
      const abortController = new AbortController()
      _auditAbort = abortController
      const initial = recovery.jobId
        ? await getAuditStatus(currentContractId, recovery.jobId, abortController.signal)
        : await auditContract(
            currentContractId,
            recovery.contractType,
            recovery.dimensions,
            recovery.idempotencyKey,
            abortController.signal,
          )
      if (requestGeneration !== generation) return initial
      saveActiveAudit({
        ...recovery,
        jobId: initial.job_id,
        batchId: initial.batch_id,
      })
      const res = isAuditPendingStatus(initial.status)
        ? await waitForAuditTerminal(
            (signal) => getAuditStatus(currentContractId, initial.job_id, signal),
            { signal: abortController.signal },
          )
        : await waitForAuditTerminal(
            async () => initial,
            { intervalMs: 0, maxAttempts: 1, signal: abortController.signal },
          )
      if (requestGeneration !== generation) return res
      const loadedRisks = await getRisks(currentContractId, res.job_id ?? initial.job_id)
      if (requestGeneration !== generation) return res
      applyQuality(res)
      crossChecks.value = res.cross_checks ?? []
      risks.value = loadedRisks
      step.value = 2
      rememberCompleted(currentContractId, filename.value, res.job_id ?? initial.job_id)
      saveActiveAudit(null)
      return res
    } catch (error) {
      if (
        requestGeneration === generation
        && (error instanceof AuditTaskError || isMissingPersistedAudit(error))
      ) saveActiveAudit(null)
      throw error
    } finally {
      if (requestGeneration === generation) {
        busy.value = false
        _auditAbort = null
      }
    }
  }

  async function resumeActiveAudit() {
    const recovery = activeAudit.value
    if (!recovery) return null
    const requestGeneration = generation
    contractId.value = recovery.contractId
    filename.value = recovery.filename
    busy.value = true
    const abortController = new AbortController()
    _auditAbort = abortController
    try {
      const initial = recovery.jobId
        ? await getAuditStatus(recovery.contractId, recovery.jobId, abortController.signal)
        : await auditContract(
            recovery.contractId,
            recovery.contractType,
            recovery.dimensions,
            recovery.idempotencyKey,
            abortController.signal,
          )
      if (requestGeneration !== generation) return initial
      if (!recovery.jobId && initial.job_id) {
        saveActiveAudit({
          ...recovery,
          jobId: initial.job_id,
          batchId: initial.batch_id,
        })
      }
      const result = await waitForAuditTerminal(
        (signal) => getAuditStatus(recovery.contractId, initial.job_id, signal),
        { signal: abortController.signal },
      )
      if (requestGeneration !== generation) return result
      const loadedRisks = await getRisks(recovery.contractId, result.job_id ?? initial.job_id)
      if (requestGeneration !== generation) return result
      applyQuality(result)
      crossChecks.value = result.cross_checks ?? []
      risks.value = loadedRisks
      step.value = 2
      rememberCompleted(recovery.contractId, recovery.filename, result.job_id ?? initial.job_id)
      saveActiveAudit(null)
      return result
    } catch (error) {
      if (
        requestGeneration === generation
        && (error instanceof AuditTaskError || isMissingPersistedAudit(error))
      ) saveActiveAudit(null)
      throw error
    } finally {
      if (requestGeneration === generation) {
        busy.value = false
        _auditAbort = null
      }
    }
  }

  async function loadCompletedAudit(
    selectedContractId: number,
    selectedFilename: string,
    selectedJobId: number,
  ) {
    if (busy.value) throw new Error('当前任务处理中，请稍后再试')
    const requestGeneration = generation
    busy.value = true
    try {
      const initial = await getAuditStatus(selectedContractId, selectedJobId)
      const result = await waitForAuditTerminal(
        async () => initial,
        { intervalMs: 0, maxAttempts: 1 },
      )
      const loadedRisks = await getRisks(selectedContractId, result.job_id ?? selectedJobId)
      if (requestGeneration !== generation) return result

      contractId.value = selectedContractId
      filename.value = selectedFilename
      elements.value = null
      applyQuality(result)
      crossChecks.value = result.cross_checks ?? []
      risks.value = loadedRisks
      step.value = 2
      rememberCompleted(selectedContractId, selectedFilename, result.job_id ?? selectedJobId)
      return result
    } finally {
      if (requestGeneration === generation) busy.value = false
    }
  }

  function abortAudit() {
    if (_auditAbort) {
      _auditAbort.abort()
      _auditAbort = null
      busy.value = false
    }
  }

  async function setRiskStatus(risk: RiskOut, status: RiskOut['review_status'], reviewComment = '') {
    const requestGeneration = generation
    await updateRiskStatus(risk.id, status, reviewComment)
    if (requestGeneration !== generation) return
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
    restoreCompletedAudit,
    abortAudit,
    setRiskStatus,
  }
})
