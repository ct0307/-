interface ReviewState {
  status: string
  requires_review?: boolean
}

export function formatOcrConfidence(confidence: number | null | undefined): string {
  if (confidence == null || !Number.isFinite(confidence)) return '未提供'
  const bounded = Math.min(1, Math.max(0, confidence))
  return `${(bounded * 100).toFixed(1)}%`
}

export function reviewStatusLabel(item: ReviewState): string {
  if (item.requires_review) return '需人工复核'
  if (item.status === 'done') return '已完成'
  return item.status
}
