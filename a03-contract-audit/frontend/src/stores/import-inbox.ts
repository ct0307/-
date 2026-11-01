import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import * as importRequests from '@/api/imports'
import type { ImportBatch, ImportItem } from '@/api/imports'

export type { ImportBatch, ImportItem } from '@/api/imports'

export interface ImportApi {
  createImport(files: File[], department?: string, idempotencyKey?: string): Promise<ImportBatch>
  appendImport(batchId: number, files: File[], idempotencyKey?: string): Promise<ImportBatch>
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

interface PendingUpload {
  signature: string
  key: string
}

function uploadSignature(batchId: number | null, department: string, files: File[]): string {
  return JSON.stringify({
    batchId,
    department,
    files: files.map((file) => ({
      name: file.name,
      size: file.size,
      type: file.type,
    })),
  })
}

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
    const lastAddedCount = ref(0)
    let pendingUpload: PendingUpload | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    let pollingVersion = 0
    let inboxVersion = 0

    const readyIds = computed(() => (
      batch.value?.items.filter((item) => item.status === 'ready').map((item) => item.id) ?? []
    ))
    const selectableIds = computed(() => new Set(readyIds.value))
    const auditTargetIds = computed(() => (
      selectedIds.value.length ? [...selectedIds.value] : [...readyIds.value]
    ))
    const allReadySelected = computed(() => (
      readyIds.value.length > 0 && selectedIds.value.length === readyIds.value.length
    ))
    const someReadySelected = computed(() => (
      selectedIds.value.length > 0 && !allReadySelected.value
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
      pollingVersion++
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

    async function pollOnce(batchId = batch.value?.id, expectedVersion = pollingVersion): Promise<ImportBatch | null> {
      if (!batchId) return null
      try {
        const next = await api.getImport(batchId)
        if (expectedVersion !== pollingVersion) return null
        batch.value = next
        error.value = ''
        updateSelection()
        if (!hasActiveItems(next)) stopPolling()
        return next
      } catch (cause) {
        if (expectedVersion !== pollingVersion) return null
        stopPolling()
        recordError(cause)
        throw cause
      }
    }

    async function startPolling(batchId = batch.value?.id) {
      if (!batchId) return
      stopPolling()
      const expectedVersion = pollingVersion
      polling.value = true
      const tick = async () => {
        try {
          await pollOnce(batchId, expectedVersion)
        } finally {
          if (polling.value && expectedVersion === pollingVersion) timer = setTimeout(() => {
            // pollOnce 已记录错误并停止轮询；首次调用仍向调用者报告失败。
            void tick().catch(() => {})
          }, 1500)
        }
      }
      await tick()
    }

    async function create(files: File[], department = '') {
      if (loading.value) {
        const message = '合同正在上传，请稍候'
        error.value = message
        throw new Error(message)
      }
      const expectedVersion = ++inboxVersion
      stopPolling()
      loading.value = true
      error.value = ''
      const currentBatch = batch.value
      const signature = uploadSignature(currentBatch?.id ?? null, department, files)
      const actionKey = pendingUpload?.signature === signature
        ? pendingUpload.key
        : crypto.randomUUID()
      pendingUpload = { signature, key: actionKey }
      lastAddedCount.value = 0
      try {
        const next = currentBatch
          ? await api.appendImport(currentBatch.id, files, actionKey)
          : await api.createImport(files, department, actionKey)
        if (expectedVersion !== inboxVersion) return next
        const previousIds = new Set(currentBatch?.items.map((item) => item.id) ?? [])
        lastAddedCount.value = next.items.filter((item) => !previousIds.has(item.id)).length
        batch.value = next
        pendingUpload = null
        error.value = ''
        if (currentBatch) updateSelection()
        else selectedIds.value = []
        if (hasActiveItems(next)) await startPolling(next.id)
        return next
      } catch (cause) {
        if (expectedVersion === inboxVersion) recordError(cause)
        throw cause
      } finally {
        if (expectedVersion === inboxVersion) loading.value = false
      }
    }

    async function resume(batchId: number) {
      const expectedVersion = ++inboxVersion
      loading.value = true
      try {
        return await startPolling(batchId)
      } finally {
        if (expectedVersion === inboxVersion) loading.value = false
      }
    }

    function toggleSelected(id: number) {
      if (!selectableIds.value.has(id)) return
      selectedIds.value = selectedIds.value.includes(id)
        ? selectedIds.value.filter((value) => value !== id)
        : [...selectedIds.value, id]
    }

    function toggleAllReady() {
      selectedIds.value = allReadySelected.value ? [] : [...readyIds.value]
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
      inboxVersion++
      stopPolling()
      batch.value = null
      selectedIds.value = []
      loading.value = false
      error.value = ''
      lastAddedCount.value = 0
      pendingUpload = null
    }

    return {
      batch,
      selectedIds,
      loading,
      polling,
      error,
      lastAddedCount,
      readyIds,
      selectableIds,
      auditTargetIds,
      allReadySelected,
      someReadySelected,
      summary,
      create,
      resume,
      pollOnce,
      startPolling,
      stopPolling,
      toggleSelected,
      toggleAllReady,
      confirm,
      retry,
      removeRecord,
      deleteDraft,
      reset,
    }
  })
}

export const useImportInboxStore = createImportInboxStore(importRequests, 'import-inbox')
