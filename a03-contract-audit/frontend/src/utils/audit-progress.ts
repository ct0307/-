import type { AuditProgressStage } from '@/api/types'

export type AuditUiState = 'idle' | 'running' | 'done' | 'failed'

export interface AuditProgressDisplay {
  label: string
  percentage: number | null
  indeterminate: boolean
}

interface AuditTerminalResult {
  status: string
  error_code?: string | null
  error_message?: string | null
  retryable?: boolean
}

interface AuditPollingOptions {
  intervalMs?: number
  maxAttempts?: number
  signal?: AbortSignal
}

const AUDIT_PENDING_STATUSES = new Set([
  'queued',
  'parsing',
  'reviewing',
  'validating',
  'auditing',
])
const AUDIT_SUCCESS_STATUSES = new Set(['done', 'review_required'])
const AUDIT_FAILURE_STATUSES = new Set(['audit_failed', 'failed'])
const BATCH_ITEM_PROGRESS_LABELS: Record<AuditProgressStage, string> = {
  queued: '等待审查',
  claimed: '已领取任务',
  parsing: '正在解析',
  reviewing: '正在审查',
  verifying: '正在校验',
  persisting: '正在保存',
  completed: '审查完成',
  failed: '审查失败',
}

export class AuditTaskError extends Error {
  code: string
  retryable: boolean

  constructor(message: string, code = '', retryable = false) {
    super(message)
    this.name = 'AuditTaskError'
    this.code = code
    this.retryable = retryable
  }
}

// Celery hard limit 为 30 分钟，额外预留 60 秒用于排队和最终状态落库。
export const AUDIT_POLLING_MAX_ATTEMPTS = 1860

export function isAuditPendingStatus(status: string): boolean {
  return AUDIT_PENDING_STATUSES.has(status)
}

export async function waitForAuditTerminal<T extends AuditTerminalResult>(
  fetchStatus: (signal?: AbortSignal) => Promise<T>,
  options: AuditPollingOptions = {},
): Promise<T> {
  const intervalMs = options.intervalMs ?? 1000
  const maxAttempts = options.maxAttempts ?? AUDIT_POLLING_MAX_ATTEMPTS

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const result = await fetchStatus(options.signal)
    if (AUDIT_FAILURE_STATUSES.has(result.status)) {
      throw new AuditTaskError(
        result.error_message || '审查任务执行失败',
        result.error_code || '',
        result.retryable ?? false,
      )
    }
    if (AUDIT_SUCCESS_STATUSES.has(result.status)) {
      return result
    }
    if (!AUDIT_PENDING_STATUSES.has(result.status)) {
      throw new AuditTaskError(`审查任务返回未知状态：${result.status}`, 'UNKNOWN_AUDIT_STATUS')
    }
    if (attempt + 1 < maxAttempts && intervalMs > 0) {
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(resolve, intervalMs)
        options.signal?.addEventListener('abort', () => {
          clearTimeout(timer)
          reject(options.signal?.reason ?? new DOMException('Aborted', 'AbortError'))
        }, { once: true })
      })
    }
  }

  throw new Error('状态查询等待超时，后台任务可能仍在执行，请刷新页面继续查看')
}

export function auditProgressDisplay(state: AuditUiState): AuditProgressDisplay {
  if (state === 'running') {
    return { label: '正在执行合同审查…', percentage: null, indeterminate: true }
  }
  if (state === 'done') {
    return { label: '审查完成', percentage: 100, indeterminate: false }
  }
  if (state === 'failed') {
    return { label: '审查失败，请重试', percentage: 0, indeterminate: false }
  }
  return { label: '', percentage: null, indeterminate: false }
}

export function batchItemProgressDisplay(
  progress: number | null | undefined,
  progressStage: AuditProgressStage,
): AuditProgressDisplay {
  const percentage = Number.isFinite(progress)
    ? Math.min(100, Math.max(0, progress as number))
    : 0

  return {
    label: BATCH_ITEM_PROGRESS_LABELS[progressStage],
    percentage,
    indeterminate: false,
  }
}
