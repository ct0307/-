import client from './client'

export type BatchStatus = 'queued' | 'running' | 'done' | 'partial_failed' | 'failed'
export type BatchItemStatus = 'queued' | 'parsing' | 'auditing' | 'done' | 'failed'

export interface AuditBatchItem {
  id: number
  contract_id: number
  filename: string
  status: BatchItemStatus
  error: string | null
  attempts: number
  started_at: string | null
  finished_at: string | null
}

export interface AuditBatch {
  id: number
  status: BatchStatus
  total: number
  completed: number
  failed: number
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

export function getBatch(batchId: number): Promise<AuditBatch> {
  return client.get(`/batches/${batchId}`)
}

export function retryBatch(batchId: number, dimensions: string[] = []): Promise<BatchRetryResult> {
  return client.post(`/batches/${batchId}/retry`, dimensions.length ? dimensions : undefined)
}
