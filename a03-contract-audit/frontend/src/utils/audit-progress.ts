export type AuditUiState = 'idle' | 'running' | 'done' | 'failed'

export interface AuditProgressDisplay {
  label: string
  percentage: number | null
  indeterminate: boolean
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
