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

test('uses a new idempotency key for each import audit action', async () => {
  const keys: string[] = []
  const useStore = createBatchStore({
    ...fakeApi([batch('done', ['done'])]),
    createBatchFromImport: async (_itemIds, _dimensions, key) => {
      keys.push(key ?? '')
      return batch('done', ['done'])
    },
  }, 'import-action-keys')
  const store = useStore()

  await store.createFromImport([1])
  await store.createFromImport([2])

  expect(keys).toHaveLength(2)
  expect(keys[0]).not.toBe(keys[1])
})

test('uses a new idempotency key for each direct file audit action', async () => {
  const keys: string[] = []
  const useStore = createBatchStore({
    ...fakeApi([batch('done', ['done'])]),
    createBatch: async (_files, _contractType, _dimensions, key) => {
      keys.push(key ?? '')
      return batch('done', ['done'])
    },
  }, 'file-action-keys')
  const store = useStore()

  await store.create([new File(['first'], 'first.txt')])
  await store.create([new File(['second'], 'second.txt')])

  expect(keys).toHaveLength(2)
  expect(keys[0]).not.toBe(keys[1])
})

test('reuses the idempotency key when retrying the same failed audit action', async () => {
  const keys: string[] = []
  let attempts = 0
  const useStore = createBatchStore({
    ...fakeApi([batch('done', ['done'])]),
    createBatchFromImport: async (_itemIds, _dimensions, key) => {
      keys.push(key ?? '')
      attempts += 1
      if (attempts === 1) throw new Error('网络超时')
      return batch('done', ['done'])
    },
  }, 'retry-audit-action-key')
  const store = useStore()

  await expect(store.createFromImport([1], ['legal'])).rejects.toThrow('网络超时')
  await store.createFromImport([1], ['legal'])

  expect(keys).toHaveLength(2)
  expect(keys[1]).toBe(keys[0])
})

test('keeps the idempotency key when initial polling fails after creation', async () => {
  const keys: string[] = []
  let pollingAttempts = 0
  const useStore = createBatchStore({
    ...fakeApi([batch('running', ['auditing'])]),
    createBatch: async (_files, _contractType, _dimensions, key) => {
      keys.push(key ?? '')
      return batch('running', ['auditing'])
    },
    getBatch: async () => {
      pollingAttempts += 1
      if (pollingAttempts === 1) throw new Error('轮询暂时不可用')
      return batch('done', ['done'])
    },
  }, 'polling-retry-action-key')
  const store = useStore()
  const files = [new File(['same'], 'same.txt', { lastModified: 1 })]

  await expect(store.create(files)).rejects.toThrow('轮询暂时不可用')
  await store.create(files)

  expect(keys).toHaveLength(2)
  expect(keys[1]).toBe(keys[0])
})
