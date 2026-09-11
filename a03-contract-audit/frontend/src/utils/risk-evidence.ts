export type EvidenceStatus = 'supported' | 'partially_supported' | 'unsupported'

export type EvidenceMeta = {
  label: string
  type: 'success' | 'warning' | 'danger'
}

const META: Record<EvidenceStatus, EvidenceMeta> = {
  supported: { label: '依据与原文已核验', type: 'success' },
  partially_supported: { label: '已检索可信来源 · 待核验', type: 'warning' },
  unsupported: { label: '证据不足 · 待复核', type: 'danger' },
}

export function evidenceMeta(status: string | null | undefined): EvidenceMeta {
  if (status && status in META) return META[status as EvidenceStatus]
  return { label: '证据状态未知 · 待复核', type: 'warning' }
}
