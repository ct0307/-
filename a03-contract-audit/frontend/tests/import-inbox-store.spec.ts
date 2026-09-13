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

test('generates a new idempotency key for each successful import operation', async () => {
  const keys: string[] = []
  const store = createImportInboxStore(api({
    createImport: async (_files, _department, key) => {
      keys.push(key ?? '')
      return { ...batchFixture, id: keys.length }
    },
  }), 'import-idempotency-success')()

  await store.create([new File(['a'], 'a.pdf')])
  await store.create([new File(['b'], 'b.pdf')])

  expect(keys).toHaveLength(2)
  expect(keys[0]).toBeTruthy()
  expect(keys[1]).toBeTruthy()
  expect(keys[1]).not.toBe(keys[0])
})

test('reuses the idempotency key when the import request fails', async () => {
  const keys: string[] = []
  let attempts = 0
  const store = createImportInboxStore(api({
    createImport: async (_files, _department, key) => {
      keys.push(key ?? '')
      attempts += 1
      if (attempts === 1) throw new Error('network unavailable')
      return batchFixture
    },
  }), 'import-idempotency-retry')()

  await expect(store.create([new File(['a'], 'a.pdf')])).rejects.toThrow('network unavailable')
  await store.create([new File(['a'], 'a.pdf')])

  expect(keys[1]).toBe(keys[0])
})

test('keeps the import key when initial polling fails after creation', async () => {
  const keys: string[] = []
  let pollingAttempts = 0
  const processing = {
    ...batchFixture,
    status: 'processing' as const,
    items: [{ ...readyItem, status: 'parsing' as const }],
  }
  const store = createImportInboxStore(api({
    createImport: async (_files, _department, key) => {
      keys.push(key ?? '')
      return processing
    },
    getImport: async () => {
      pollingAttempts += 1
      if (pollingAttempts === 1) throw new Error('polling unavailable')
      return batchFixture
    },
  }), 'import-idempotency-polling')()

  await expect(store.create([new File(['a'], 'a.pdf')])).rejects.toThrow('polling unavailable')
  await store.create([new File(['a'], 'a.pdf')])

  expect(keys[1]).toBe(keys[0])
})

test('starts a new import operation when files change after a failure', async () => {
  const keys: string[] = []
  const store = createImportInboxStore(api({
    createImport: async (_files, _department, key) => {
      keys.push(key ?? '')
      if (keys.length === 1) throw new Error('network unavailable')
      return batchFixture
    },
  }), 'import-idempotency-changed-input')()

  await expect(store.create([new File(['a'], 'a.pdf')])).rejects.toThrow('network unavailable')
  await store.create([new File(['b'], 'b.pdf')])

  expect(keys[1]).not.toBe(keys[0])
})
