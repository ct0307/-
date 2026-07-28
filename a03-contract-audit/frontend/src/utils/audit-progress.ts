export type AuditUiState = 'idle' | 'running' | 'done' | 'failed'

export interface AuditProgressDisplay {
  label: string
  percentage: number | null
  indeterminate: boolean
}

interface AuditTerminalResult {
  status: string
}

interface AuditPollingOptions {
  intervalMs?: number
  maxAttempts?: number
  signal?: AbortSignal
}

const AUDIT_PENDING_STATUSES = new Set(['queued', 'parsing', 'auditing'])

export async function waitForAuditTerminal<T extends AuditTerminalResult>(
  fetchStatus: (signal?: AbortSignal) => Promise<T>,
  options: AuditPollingOptions = {},
): Promise<T> {
  const intervalMs = options.intervalMs ?? 1000
  const maxAttempts = options.maxAttempts ?? 120

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const result = await fetchStatus(options.signal)
    if (result.status === 'audit_failed') {
      throw new Error('审查任务执行失败')
    }
    if (!AUDIT_PENDING_STATUSES.has(result.status)) {
      return result
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

  throw new Error('审查任务等待超时')
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
