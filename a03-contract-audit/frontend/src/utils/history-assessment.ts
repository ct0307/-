import type { HistoryRow } from '@/mock/history'
import type { AuditResult } from '@/api/types'

/** 对接口附加的质量元数据保留运行时校验，兼容缺字段的旧响应。 */
export type HistoryAuditSnapshot = AuditResult & {
  coverage?: unknown
  quality_reasons?: unknown
  issues?: unknown
}

export function historyAuditCoverage(audit: HistoryAuditSnapshot | null): { planned: number; completed: number } | null {
  const coverage = audit?.coverage
  if (!coverage || typeof coverage !== 'object' || Array.isArray(coverage)) return null
  if (!('planned' in coverage) || !('completed' in coverage)) return null
  const { planned, completed } = coverage
  if (typeof planned !== 'number' || typeof completed !== 'number'
    || !Number.isInteger(planned) || !Number.isInteger(completed)
    || planned < 0 || completed < 0) return null
  return { planned, completed }
}

/** 详情只信当前任务快照，列表旧任务的完整度不能证明重审已完整。 */
export function isHistoryAuditAssessmentComplete(audit: HistoryAuditSnapshot | null): boolean {
  const coverage = historyAuditCoverage(audit)
  return !!audit
    && Number.isInteger(audit.job_id) && (audit.job_id ?? 0) > 0
    && audit.status === 'done'
    && audit.requires_review === false
    && !!coverage && coverage.planned > 0 && coverage.completed === coverage.planned
    && Array.isArray(audit.quality_reasons) && audit.quality_reasons.length === 0
    && Array.isArray(audit.issues) && audit.issues.length === 0
}

/** 缺少完整度证据的旧响应只展示候选，不能推断为低风险或合规。 */
export function isHistoryAssessmentComplete(row: HistoryRow): boolean {
  const coverage = row.coverage
  return row.assessmentComplete === true
    && !['解析失败', '未审查', '审查中', '审查失败'].includes(row.status)
    && !!coverage
    && Number.isInteger(coverage.planned)
    && Number.isInteger(coverage.completed)
    && coverage.planned > 0
    && coverage.completed === coverage.planned
}

export function normalizeHistoryAssessment(row: HistoryRow): HistoryRow {
  if (isHistoryAssessmentComplete(row)) return row
  return {
    ...row,
    level: '尚无法判断',
    status: ['合规', '已整改', '未发现风险'].includes(row.status) ? '待人工复核' : row.status,
    assessmentComplete: false,
  }
}

export function historyRiskCountLabel(row: HistoryRow): string {
  if (isHistoryAssessmentComplete(row)) return String(row.riskCount)
  return row.riskCount > 0 ? `已检出 ${row.riskCount}` : '未完成'
}
