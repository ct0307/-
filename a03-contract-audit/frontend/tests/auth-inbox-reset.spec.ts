import { expect, test } from '@playwright/test'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '../src/stores/auth'
import { useBatchStore } from '../src/stores/batch'
import { useImportInboxStore } from '../src/stores/import-inbox'

test('logout clears inbox state and stops background polling', () => {
  const values = new Map<string, string>()
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    },
  })
  setActivePinia(createPinia())
  const auth = useAuthStore()
  const inbox = useImportInboxStore()
  const auditBatch = useBatchStore()
  inbox.batch = {
    id: 42,
    status: 'processing',
    total: 1,
    ready: 0,
    failed: 0,
    created_at: '2026-09-11T10:00:00Z',
    updated_at: '2026-09-11T10:00:00Z',
    items: [],
  }
  inbox.polling = true
  auditBatch.polling = true

  auth.logout()

  expect(inbox.batch).toBeNull()
  expect(inbox.polling).toBe(false)
  expect(auditBatch.polling).toBe(false)
})
