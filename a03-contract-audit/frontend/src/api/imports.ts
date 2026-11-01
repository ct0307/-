import client from './client'
import type { ContractQualityFields } from './types'
import { parseUploadLimits, type UploadLimits } from '@/config/upload-limits'

export async function getImportLimits(): Promise<UploadLimits> {
  return parseUploadLimits(await client.get<unknown>('/imports/limits'))
}

export type ImportItemStatus =
  | 'queued'
  | 'parsing'
  | 'awaiting_confirmation'
  | 'ready'
  | 'failed'
  | 'auditing'
  | 'done'
  | 'deleted'

export interface ImportItem extends ContractQualityFields {
  id: number
  contract_id: number | null
  filename: string
  status: ImportItemStatus
  error_code: string | null
  error_message: string | null
  error_action?: string | null
  retryable?: boolean
  correlation_id?: string | null
  suggested_type: string
  confidence: number | null
  confirmed_type: string
  department: string
  requires_review: boolean
}

export interface ImportBatch {
  id: number
  status: 'processing' | 'needs_attention' | 'ready'
  total: number
  ready: number
  failed: number
  created_at: string
  updated_at: string
  items: ImportItem[]
}

export function createImport(
  files: File[],
  department = '',
  idempotencyKey = crypto.randomUUID(),
): Promise<ImportBatch> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  form.append('department', department)
  return client.post('/imports', form, {
    headers: { 'Idempotency-Key': idempotencyKey },
    timeout: 300_000,
  })
}

export function appendImport(
  batchId: number,
  files: File[],
  idempotencyKey = crypto.randomUUID(),
): Promise<ImportBatch> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  return client.post(`/imports/${batchId}/items`, form, {
    headers: { 'Idempotency-Key': idempotencyKey },
    timeout: 300_000,
  })
}

export function getImport(batchId: number): Promise<ImportBatch> {
  return client.get(`/imports/${batchId}`)
}

export function confirmItem(
  batchId: number,
  itemId: number,
  contractType: string,
  department: string,
): Promise<ImportItem> {
  return client.patch(`/imports/${batchId}/items/${itemId}`, {
    contract_type: contractType,
    department,
  })
}

export function retryItem(batchId: number, itemId: number): Promise<ImportItem> {
  return client.post(`/imports/${batchId}/items/${itemId}/retry`)
}

export function removeFailedRecord(batchId: number, itemId: number): Promise<void> {
  return client.delete(`/imports/${batchId}/items/${itemId}/record`)
}

export function deleteDraft(batchId: number, itemId: number): Promise<ImportItem> {
  return client.delete(`/imports/${batchId}/items/${itemId}/draft`)
}

export function importErrorMessage(cause: unknown): string {
  const response = (cause as { response?: { data?: { detail?: unknown } } })?.response
  const detail = response?.data?.detail
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) return message
  }
  if (cause instanceof Error && /[一-鿿]/.test(cause.message)) return cause.message
  return '操作失败，请稍后重试'
}
