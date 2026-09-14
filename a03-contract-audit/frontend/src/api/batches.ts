import client from './client'
import type {
  AuditBatchStatus,
  AuditItemStatus,
  AuditProgressStage,
} from './types'

export type BatchStatus = AuditBatchStatus
export type BatchItemStatus = AuditItemStatus

export interface AuditBatchItem {
  id: number
  contract_id: number
  filename: string
  status: BatchItemStatus
  progress: number
  progress_stage: AuditProgressStage
  error: string | null
  error_code?: string | null
  attempts: number
  started_at: string | null
  finished_at: string | null
  requires_review?: boolean
  ocr_confidence?: number | null
  review_reason?: string | null
}

export interface AuditBatch {
  id: number
  status: BatchStatus
  total: number
  completed: number
  failed: number
  progress: number
  created_at: string
  updated_at: string
  items: AuditBatchItem[]
}

export interface BatchRetryResult {
  batch_id: number
  retried: number
  status: BatchStatus
}

export function createBatch(
  files: File[],
  contractType = '',
  dimensions: string[] = [],
  idempotencyKey = crypto.randomUUID(),
): Promise<AuditBatch> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  form.append('contract_type', contractType)
  dimensions.forEach((dimension) => form.append('dimensions', dimension))
  return client.post('/batches', form, {
    headers: { 'Idempotency-Key': idempotencyKey },
    timeout: 300_000,
  })
}

export function createBatchFromImport(
  importItemIds: number[],
  dimensions: string[] = [],
  idempotencyKey = crypto.randomUUID(),
): Promise<AuditBatch> {
  return client.post('/batches/from-import', {
    import_item_ids: importItemIds,
    dimensions,
  }, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })
}

export function getBatch(batchId: number): Promise<AuditBatch> {
  return client.get(`/batches/${batchId}`)
}

export function retryBatch(batchId: number, dimensions: string[] = []): Promise<BatchRetryResult> {
  return client.post(`/batches/${batchId}/retry`, dimensions.length ? dimensions : undefined)
}
