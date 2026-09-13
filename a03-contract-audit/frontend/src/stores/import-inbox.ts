import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import * as importRequests from '@/api/imports'
import type { ImportBatch, ImportItem } from '@/api/imports'

export type { ImportBatch, ImportItem } from '@/api/imports'

export interface ImportApi {
  createImport(files: File[], department?: string, idempotencyKey?: string): Promise<ImportBatch>
  getImport(batchId: number): Promise<ImportBatch>
  confirmItem(
    batchId: number,
    itemId: number,
    contractType: string,
    department: string,
  ): Promise<ImportItem>
  retryItem(batchId: number, itemId: number): Promise<ImportItem>
  removeFailedRecord(batchId: number, itemId: number): Promise<void>
  deleteDraft(batchId: number, itemId: number): Promise<ImportItem>
}

const ACTIVE_STATUSES = new Set<ImportItem['status']>(['queued', 'parsing', 'auditing'])
let testStoreSequence = 0

export function createImportInboxStore(
  api: ImportApi = importRequests,
  storeId = `import-inbox-${++testStoreSequence}`,
) {
  return defineStore(storeId, () => {
    const batch = ref<ImportBatch | null>(null)
    const selectedIds = ref<number[]>([])
    const loading = ref(false)
    const polling = ref(false)
    const error = ref('')
    const idempotencyKey = ref('')
    const idempotencySignature = ref('')
    let timer: ReturnType<typeof setTimeout> | null = null

    const selectableIds = computed(() => new Set(
      batch.value?.items.filter((item) => item.status === 'ready').map((item) => item.id) ?? [],
    ))
    const summary = computed(() => {
      const items = batch.value?.items ?? []
      return {
        total: items.length,
        ready: items.filter((item) => item.status === 'ready').length,
        needsConfirmation: items.filter((item) => item.status === 'awaiting_confirmation').length,
        failed: items.filter((item) => item.status === 'failed').length,
      }
    })

    function stopPolling() {
      polling.value = false
      if (timer) {
        clearTimeout(timer)
        timer = null
      }
    }

    function hasActiveItems(value: ImportBatch) {
      return value.items.some((item) => ACTIVE_STATUSES.has(item.status))
    }

    function updateSelection() {
      selectedIds.value = selectedIds.value.filter((id) => selectableIds.value.has(id))
    }

    function replaceItem(next: ImportItem) {
      if (!batch.value) return
      batch.value = {
        ...batch.value,
        items: batch.value.items.map((item) => item.id === next.id ? next : item),
      }
      updateSelection()
    }

    function recordError(cause: unknown) {
      error.value = importRequests.importErrorMessage(cause)
    }

    function prepareIdempotency(files: File[], department: string) {
      const signature = JSON.stringify({
        department,
        files: files.map((file) => [file.name, file.size, file.type]),
      })
      if (!idempotencyKey.value || idempotencySignature.value !== signature) {
        idempotencyKey.value = crypto.randomUUID()
        idempotencySignature.value = signature
      }
    }

    async function pollOnce(batchId = batch.value?.id): Promise<ImportBatch | null> {
      if (!batchId) return null
      try {
        const next = await api.getImport(batchId)
        batch.value = next
        error.value = ''
        updateSelection()
        if (!hasActiveItems(next)) stopPolling()
        return next
      } catch (cause) {
        stopPolling()
        recordError(cause)
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

    async function create(files: File[], department = '') {
      loading.value = true
      error.value = ''
      prepareIdempotency(files, department)
      try {
        batch.value = await api.createImport(files, department, idempotencyKey.value)
        selectedIds.value = []
        if (hasActiveItems(batch.value)) await startPolling(batch.value.id)
        idempotencyKey.value = ''
        idempotencySignature.value = ''
        return batch.value
      } catch (cause) {
        recordError(cause)
        throw cause
      } finally {
        loading.value = false
      }
    }

    async function resume(batchId: number) {
      loading.value = true
      try {
        return await startPolling(batchId)
      } finally {
        loading.value = false
      }
    }

    function toggleSelected(id: number) {
      if (!selectableIds.value.has(id)) return
      selectedIds.value = selectedIds.value.includes(id)
        ? selectedIds.value.filter((value) => value !== id)
        : [...selectedIds.value, id]
    }

    async function confirm(itemId: number, contractType: string, department: string) {
      if (!batch.value) return null
      loading.value = true
      try {
        const item = await api.confirmItem(batch.value.id, itemId, contractType, department)
        replaceItem(item)
        error.value = ''
        return item
      } catch (cause) {
        recordError(cause)
        throw cause
      } finally {
        loading.value = false
      }
    }

    async function retry(itemId: number) {
      if (!batch.value) return null
      const item = await api.retryItem(batch.value.id, itemId)
      replaceItem(item)
      await startPolling(batch.value.id)
      return item
    }

    async function removeRecord(itemId: number) {
      if (!batch.value) return
      await api.removeFailedRecord(batch.value.id, itemId)
      batch.value = {
        ...batch.value,
        items: batch.value.items.filter((item) => item.id !== itemId),
      }
      updateSelection()
    }

    async function deleteDraft(itemId: number) {
      if (!batch.value) return null
      const item = await api.deleteDraft(batch.value.id, itemId)
      batch.value = {
        ...batch.value,
        items: batch.value.items.filter((candidate) => candidate.id !== item.id),
      }
      updateSelection()
      return item
    }

    function reset() {
      stopPolling()
      batch.value = null
      selectedIds.value = []
      loading.value = false
      error.value = ''
      idempotencyKey.value = ''
      idempotencySignature.value = ''
    }

    return {
      batch,
      selectedIds,
      loading,
      polling,
      error,
      selectableIds,
      summary,
      create,
      resume,
      pollOnce,
      startPolling,
      stopPolling,
      toggleSelected,
      confirm,
      retry,
      removeRecord,
      deleteDraft,
      reset,
    }
  })
}

export const useImportInboxStore = createImportInboxStore(importRequests, 'import-inbox')
