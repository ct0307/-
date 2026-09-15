import { expect, test } from '@playwright/test'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '../src/stores/auth'
import { useBatchStore } from '../src/stores/batch'
import { useImportInboxStore } from '../src/stores/import-inbox'
import { useNotifyStore } from '../src/stores/notify'
import { useRectifyStore } from '../src/stores/rectify'

test('logout clears all user-scoped state and stops background polling', () => {
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
  const rectify = useRectifyStore()
  const notify = useNotifyStore()
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
  rectify.items = [{
    id: 'RC-PRIVATE', contract: '用户甲合同', risk: '敏感风险', level: 'high',
    owner: '用户甲', status: '待处理', created: '2026-09-15', due: '2026-09-20', note: '内部说明',
  }]
  notify.push('rectify', '用户甲通知', '敏感风险内容')

  auth.logout()

  expect(inbox.batch).toBeNull()
  expect(inbox.polling).toBe(false)
  expect(auditBatch.polling).toBe(false)
  expect(rectify.items).toEqual([])
  expect(notify.items).toEqual([])
})
