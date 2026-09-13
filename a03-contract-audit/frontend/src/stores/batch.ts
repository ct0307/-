import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import * as batchRequests from '@/api/batches'
import type { AuditBatch, BatchRetryResult } from '@/api/batches'

export type { AuditBatch } from '@/api/batches'

export interface BatchApi {
  createBatch(
    files: File[],
    contractType?: string,
    dimensions?: string[],
    idempotencyKey?: string,
  ): Promise<AuditBatch>
  createBatchFromImport(
    importItemIds: number[],
    dimensions?: string[],
    idempotencyKey?: string,
  ): Promise<AuditBatch>
  getBatch(batchId: number): Promise<AuditBatch>
  retryBatch(batchId: number, dimensions?: string[]): Promise<BatchRetryResult>
}

const TERMINAL_STATUSES = new Set<AuditBatch['status']>(['done', 'partial_failed', 'failed'])
let testStoreSequence = 0

interface PendingAction {
  signature: string
  key: string
}

function fileActionSignature(files: File[], contractType: string, dimensions: string[]): string {
  return JSON.stringify({
    kind: 'files',
    contractType,
    dimensions,
    files: files.map((file) => ({
      name: file.name,
      size: file.size,
      type: file.type,
    })),
  })
}

function importActionSignature(importItemIds: number[], dimensions: string[]): string {
  return JSON.stringify({ kind: 'import', importItemIds, dimensions })
}

export function createBatchStore(
  api: BatchApi = batchRequests,
  storeId = `batch-${++testStoreSequence}`,
) {
  return defineStore(storeId, () => {
    const batch = ref<AuditBatch | null>(null)
    const loading = ref(false)
    const polling = ref(false)
    const error = ref('')
    let pendingAction: PendingAction | null = null
    let timer: ReturnType<typeof setTimeout> | null = null

    function actionKey(signature: string): string {
      const key = pendingAction?.signature === signature
        ? pendingAction.key
        : crypto.randomUUID()
      pendingAction = { signature, key }
      return key
    }

    const progress = computed(() => {
      if (!batch.value?.total) return 0
      return Math.round((batch.value.completed / batch.value.total) * 100)
    })
    const isTerminal = computed(() => Boolean(batch.value && TERMINAL_STATUSES.has(batch.value.status)))

    function stopPolling() {
      polling.value = false
      if (timer) {
        clearTimeout(timer)
        timer = null
      }
    }

    async function pollOnce(batchId = batch.value?.id): Promise<AuditBatch | null> {
      if (!batchId) return null
      try {
        const next = await api.getBatch(batchId)
        batch.value = next
        error.value = ''
        if (TERMINAL_STATUSES.has(next.status)) stopPolling()
        return next
      } catch (cause) {
        stopPolling()
        error.value = cause instanceof Error ? cause.message : '批次状态查询失败'
        throw cause
      }
    }

    async function startPolling(batchId = batch.value?.id) {
      if (!batchId) return
      stopPolling()
      polling.value = true

      const tick = async () => {
        try {
          await pollOnce(batchId)
        } finally {
          if (polling.value) timer = setTimeout(tick, 1500)
        }
      }
      await tick()
    }

    async function create(files: File[], contractType = '', dimensions: string[] = []) {
      loading.value = true
      error.value = ''
      const key = actionKey(fileActionSignature(files, contractType, dimensions))
      try {
        batch.value = await api.createBatch(files, contractType, dimensions, key)
        if (TERMINAL_STATUSES.has(batch.value.status)) stopPolling()
        else await startPolling(batch.value.id)
        pendingAction = null
        return batch.value
      } catch (cause) {
        error.value = cause instanceof Error ? cause.message : '批次创建失败'
        throw cause
      } finally {
        loading.value = false
      }
    }

    async function createFromImport(importItemIds: number[], dimensions: string[] = []) {
      loading.value = true
      error.value = ''
      const key = actionKey(importActionSignature(importItemIds, dimensions))
      try {
        batch.value = await api.createBatchFromImport(
          importItemIds,
          dimensions,
          key,
        )
        if (TERMINAL_STATUSES.has(batch.value.status)) stopPolling()
        else await startPolling(batch.value.id)
        pendingAction = null
        return batch.value
      } catch (cause) {
        error.value = cause instanceof Error ? cause.message : '批次创建失败'
        throw cause
      } finally {
        loading.value = false
      }
    }

    async function resume(batchId: number) {
      loading.value = true
      try {
        await startPolling(batchId)
      } finally {
        loading.value = false
      }
    }

    async function retry(dimensions: string[] = []) {
      if (!batch.value) return null
      loading.value = true
      try {
        const result = await api.retryBatch(batch.value.id, dimensions)
        await startPolling(batch.value.id)
        return result
      } finally {
        loading.value = false
      }
    }

    function reset() {
      stopPolling()
      batch.value = null
      error.value = ''
      pendingAction = null
    }

    return {
      batch,
      loading,
      polling,
      error,
      progress,
      isTerminal,
      pollOnce,
      startPolling,
      create,
      createFromImport,
      resume,
      retry,
      stopPolling,
      reset,
    }
  })
}

export const useBatchStore = createBatchStore(batchRequests, 'batch')
