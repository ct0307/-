import { expect, test } from '@playwright/test'
import { createPinia, setActivePinia } from 'pinia'

import { createBatchStore, type BatchApi, type AuditBatch } from '../src/stores/batch'

function batch(status: AuditBatch['status'], itemStatuses: AuditBatch['items'][number]['status'][]): AuditBatch {
  return {
    id: 1,
    status,
    total: itemStatuses.length,
    completed: itemStatuses.filter((item) => item === 'done' || item === 'failed').length,
    failed: itemStatuses.filter((item) => item === 'failed').length,
    created_at: '2026-07-26T10:00:00Z',
    updated_at: '2026-07-26T10:00:00Z',
    items: itemStatuses.map((itemStatus, index) => ({
      id: index + 1,
      contract_id: index + 10,
      filename: `contract-${index}.pdf`,
      status: itemStatus,
      error: itemStatus === 'failed' ? 'OCR 置信度不足' : null,
      attempts: 0,
      started_at: null,
      finished_at: null,
    })),
  }
}

function fakeApi(responses: AuditBatch[]): BatchApi {
  let index = 0
  return {
    createBatch: async () => responses[0],
    createBatchFromImport: async () => responses[0],
    getBatch: async () => responses[Math.min(index++, responses.length - 1)],
    retryBatch: async () => ({ batch_id: 1, retried: 1, status: 'queued' }),
  }
}

test.beforeEach(() => setActivePinia(createPinia()))

test('stops polling when every item is terminal', async () => {
  const useStore = createBatchStore(fakeApi([batch('partial_failed', ['done', 'failed'])]))
  const store = useStore()
  store.polling = true

  await store.pollOnce(1)

  expect(store.polling).toBe(false)
  expect(store.batch?.items[1].error).toBe('OCR 置信度不足')
})

test('keeps polling while an item is running', async () => {
  const useStore = createBatchStore(fakeApi([batch('running', ['done', 'auditing'])]))
  const store = useStore()
  store.polling = true

  await store.pollOnce(1)

  expect(store.polling).toBe(true)
  expect(store.progress).toBe(50)
})

test('creates an audit batch from selected import items', async () => {
  const calls: Array<{ itemIds: number[]; dimensions: string[]; key: string }> = []
  const useStore = createBatchStore({
    ...fakeApi([batch('done', ['done', 'done'])]),
    createBatchFromImport: async (itemIds, dimensions, key) => {
      calls.push({ itemIds, dimensions, key })
      return batch('done', ['done', 'done'])
    },
  }, 'batch-from-import')
  const store = useStore()

  await store.createFromImport([3, 5], ['legal', 'payment'])

  expect(calls).toHaveLength(1)
  expect(calls[0].itemIds).toEqual([3, 5])
  expect(calls[0].dimensions).toEqual(['legal', 'payment'])
  expect(calls[0].key).toBeTruthy()
})
