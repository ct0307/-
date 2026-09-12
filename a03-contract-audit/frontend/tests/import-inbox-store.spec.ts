import { expect, test } from '@playwright/test'
import { createPinia, setActivePinia } from 'pinia'

import type { ImportBatch, ImportItem } from '../src/api/imports'
import { createImportInboxStore, type ImportApi } from '../src/stores/import-inbox'

const readyItem: ImportItem = {
  id: 1,
  contract_id: 11,
  filename: '采购合同.pdf',
  status: 'ready',
  error_code: null,
  error_message: null,
  suggested_type: '采购合同',
  confidence: 0.91,
  confirmed_type: '采购合同',
  department: '法务部',
  requires_review: false,
}

const failedItem: ImportItem = {
  ...readyItem,
  id: 2,
  contract_id: 12,
  filename: '扫描件.pdf',
  status: 'failed',
  error_code: 'PARSE_FAILED',
  error_message: '合同解析失败，请重新解析或删除草稿',
}

const failedWithoutContract: ImportItem = {
  ...failedItem,
  id: 3,
  contract_id: null,
  filename: '病毒.exe',
  error_code: 'UNSUPPORTED_FILE_TYPE',
  error_message: '不支持的文件类型',
  suggested_type: '',
  confidence: null,
  confirmed_type: '',
  department: '',
}

const batchFixture: ImportBatch = {
  id: 12,
  status: 'needs_attention',
  total: 3,
  ready: 1,
  failed: 2,
  created_at: '2026-09-11T10:00:00Z',
  updated_at: '2026-09-11T10:00:00Z',
  items: [readyItem, failedItem, failedWithoutContract],
}

function api(overrides: Partial<ImportApi> = {}): ImportApi {
  return {
    createImport: async () => batchFixture,
    appendImport: async () => batchFixture,
    getImport: async () => batchFixture,
    confirmItem: async () => readyItem,
    retryItem: async () => ({ ...failedItem, status: 'queued', error_code: null, error_message: null }),
    removeFailedRecord: async () => undefined,
    deleteDraft: async () => ({ ...failedItem, status: 'deleted' }),
    ...overrides,
  }
}

test.beforeEach(() => setActivePinia(createPinia()))

test('keeps failed items while allowing only ready items to be selected', async () => {
  const store = createImportInboxStore(api(), 'test-import')()

  await store.resume(12)
  store.toggleSelected(readyItem.id)
  store.toggleSelected(failedItem.id)

  expect(store.selectedIds).toEqual([readyItem.id])
  expect(store.summary).toEqual({ total: 3, ready: 1, needsConfirmation: 0, failed: 2 })
})

test('removes an upload failure through the record endpoint only', async () => {
  let removed = 0
  const store = createImportInboxStore(api({
    removeFailedRecord: async () => { removed += 1 },
  }), 'remove-import')()

  await store.resume(12)
  await store.removeRecord(failedWithoutContract.id)

  expect(removed).toBe(1)
  expect(store.batch?.items).not.toContainEqual(expect.objectContaining({ id: failedWithoutContract.id }))
})

test('replaces one item with the server-confirmed state', async () => {
  const awaiting = { ...readyItem, status: 'awaiting_confirmation' as const, confirmed_type: '' }
  const confirmed = { ...awaiting, status: 'ready' as const, confirmed_type: '采购合同' }
  const store = createImportInboxStore(api({
    getImport: async () => ({ ...batchFixture, items: [awaiting] }),
    confirmItem: async () => confirmed,
  }), 'confirm-import')()

  await store.resume(12)
  await store.confirm(awaiting.id, '采购合同', '法务部')

  expect(store.batch?.items[0]).toEqual(confirmed)
})

test('appends a second file to the active inbox with a new action key', async () => {
  const createKeys: string[] = []
  const appendCalls: Array<{ batchId: number; key: string }> = []
  const appendedItem = { ...readyItem, id: 4, contract_id: 14, filename: '追加合同.txt' }
  const appendedBatch = {
    ...batchFixture,
    total: 4,
    ready: 2,
    items: [...batchFixture.items, appendedItem],
  }
  const store = createImportInboxStore(api({
    createImport: async (_files, _department, key) => {
      createKeys.push(key ?? '')
      return batchFixture
    },
    appendImport: async (batchId, _files, key) => {
      appendCalls.push({ batchId, key })
      return appendedBatch
    },
  }), 'append-import')()

  await store.create([new File(['first'], 'first.txt')], '法务部')
  store.toggleSelected(readyItem.id)
  await store.create([new File(['second'], 'second.txt')], '法务部')

  expect(appendCalls).toHaveLength(1)
  expect(appendCalls[0].batchId).toBe(batchFixture.id)
  expect(appendCalls[0].key).not.toBe(createKeys[0])
  expect(store.batch?.items).toHaveLength(4)
  expect(store.selectedIds).toEqual([readyItem.id])
})

test('keeps the current inbox and selection when append fails', async () => {
  const store = createImportInboxStore(api({
    appendImport: async () => { throw new Error('追加失败') },
  }), 'failed-append-import')()
  await store.create([new File(['first'], 'first.txt')], '法务部')
  store.toggleSelected(readyItem.id)

  await expect(store.create([new File(['second'], 'second.txt')], '法务部')).rejects.toThrow('追加失败')

  expect(store.batch).toEqual(batchFixture)
  expect(store.selectedIds).toEqual([readyItem.id])
})

test('reuses the action key when retrying the same failed upload', async () => {
  const keys: string[] = []
  let attempts = 0
  const store = createImportInboxStore(api({
    createImport: async (_files, _department, key) => {
      keys.push(key ?? '')
      attempts += 1
      if (attempts === 1) throw new Error('网络超时')
      return batchFixture
    },
  }), 'retry-import-key')()
  const files = [new File(['same'], 'same.txt', { lastModified: 1 })]

  await expect(store.create(files, '法务部')).rejects.toThrow('网络超时')
  await store.create(files, '法务部')

  expect(keys).toHaveLength(2)
  expect(keys[1]).toBe(keys[0])
})

test('uses a new action key when files change after a failed upload', async () => {
  const keys: string[] = []
  const store = createImportInboxStore(api({
    createImport: async (_files, _department, key) => {
      keys.push(key ?? '')
      throw new Error('网络超时')
    },
  }), 'changed-import-key')()

  await expect(store.create([new File(['first'], 'first.txt')], '法务部')).rejects.toThrow()
  await expect(store.create([new File(['second'], 'second.txt')], '法务部')).rejects.toThrow()

  expect(keys).toHaveLength(2)
  expect(keys[1]).not.toBe(keys[0])
})

test('reports zero additions when the server replays an existing batch', async () => {
  const store = createImportInboxStore(api(), 'replayed-import')()
  await store.resume(batchFixture.id)

  await store.create([new File(['same'], readyItem.filename)], '法务部')

  expect(store.lastAddedCount).toBe(0)
})

test('rejects a concurrent upload before sending another request', async () => {
  let releaseFirst: ((value: ImportBatch) => void) | undefined
  let calls = 0
  const firstResponse = new Promise<ImportBatch>((resolve) => { releaseFirst = resolve })
  const store = createImportInboxStore(api({
    createImport: async () => {
      calls += 1
      return calls === 1 ? firstResponse : batchFixture
    },
  }), 'concurrent-import')()

  const first = store.create([new File(['first'], 'first.txt')], '法务部')
  await expect(
    store.create([new File(['second'], 'second.txt')], '法务部'),
  ).rejects.toThrow('合同正在上传，请稍候')
  releaseFirst?.(batchFixture)
  await first

  expect(calls).toBe(1)
})
