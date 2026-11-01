export type TraceTagType = 'success' | 'warning' | 'danger'

export function applicabilityMeta(status?: string): { label: string; type: TraceTagType } {
  if (status === 'applicable') return { label: '适用性已核验', type: 'success' }
  if (status === 'expired' || status === 'not_yet_effective') {
    return { label: '法规时点不适用', type: 'danger' }
  }
  return { label: '待核验', type: 'warning' }
}

export function ruleStatusMeta(status?: string): { label: string; type: TraceTagType } {
  if (status === 'hit') return { label: '命中', type: 'danger' }
  if (status === 'not_hit') return { label: '未命中', type: 'success' }
  return { label: '待核验', type: 'warning' }
}

export function decisionMeta(status?: string): { label: string; type: TraceTagType } {
  if (status === 'accepted') return { label: '已接受', type: 'success' }
  if (status === 'manual_review') return { label: '人工复核', type: 'warning' }
  if (status === 'rejected') return { label: '已拒绝', type: 'danger' }
  return { label: '待核验', type: 'warning' }
}
