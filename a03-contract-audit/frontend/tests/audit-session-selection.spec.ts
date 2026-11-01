import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { createPinia, setActivePinia } from 'pinia'
import * as pinia from 'pinia'
import * as vue from 'vue'
import ts from 'typescript'
import * as progress from '../src/utils/audit-progress'
import { SESSION_KEYS } from '../src/utils/session'
import type { useAuditSessionStore } from '../src/stores/audit-session'

type Result = { contract_id: number; job_id: number; status: string }
type Risk = { id: number; contract_id: number }

let originalGlobals: Record<string, PropertyDescriptor | undefined>
test.beforeEach(() => {
  originalGlobals = Object.fromEntries(['window', 'localStorage'].map(key => [
    key, Object.getOwnPropertyDescriptor(globalThis, key),
  ]))
})
test.afterEach(() => {
  for (const [key, descriptor] of Object.entries(originalGlobals)) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor)
    else Reflect.deleteProperty(globalThis, key)
  }
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

function transpile(source: string) {
  return ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
}

// 使用真实 store 和路由监听，仅将网络边界替换为可手动完成的请求。
function harness() {
  setActivePinia(createPinia())
  const storage = new Map<string, string>()
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    },
  })
  Object.defineProperty(globalThis, 'window', {
    configurable: true, value: { localStorage: globalThis.localStorage },
  })
  const risks = new Map<number, ReturnType<typeof deferred<Risk[]>>>()
  const started = new Map<number, ReturnType<typeof deferred<void>>>()
  for (const id of [301, 302]) {
    risks.set(id, deferred<Risk[]>())
    started.set(id, deferred<void>())
  }
  const statusRequests: { id: number; signal?: AbortSignal }[] = []
  const riskRequests: { id: number; signal?: AbortSignal }[] = []
  const initialAudit = deferred<Result>()
  const statusGate = deferred<Result>()
  let holdStatus = false
  let auditSignal: AbortSignal | undefined
  const api = {
    getAuditStatus: async (id: number, jobId?: number, signal?: AbortSignal) => {
      statusRequests.push({ id, signal })
      if (holdStatus) return statusGate.promise
      return { contract_id: id, job_id: jobId ?? id + 3000, status: 'done' }
    },
    // 故意忽略 signal，验证即使底层取消太迟，旧 Promise 也不能写回。
    getRisks: (id: number, _jobId?: number, signal?: AbortSignal) => {
      riskRequests.push({ id, signal })
      started.get(id)!.resolve()
      return risks.get(id)!.promise
    },
    auditContract: (_id: number, _type: string, _dimensions: string[], _key: string, signal?: AbortSignal) => {
      auditSignal = signal
      return initialAudit.promise
    },
  }
  const dependencies: Record<string, unknown> = {
    pinia,
    vue,
    '@/api/contract': api,
    '@/utils/audit-progress': progress,
    '@/utils/idempotency': { createAuditIdempotencyKey: async () => 'selection-test' },
    '@/utils/session': { SESSION_KEYS },
  }
  const module = { exports: {} as { useAuditSessionStore: typeof useAuditSessionStore } }
  const source = readFileSync(new URL('../src/stores/audit-session.ts', import.meta.url), 'utf8')
  new Function('require', 'module', 'exports', transpile(source))(
    (name: string) => {
      if (!(name in dependencies)) throw new Error(`未配置依赖：${name}`)
      return dependencies[name]
    }, module, module.exports,
  )
  const session = module.exports.useAuditSessionStore()
  const view = readFileSync(new URL('../src/views/AuditView.vue', import.meta.url), 'utf8')
  const route = vue.reactive({ query: { contractId: '301', jobId: '3301', filename: '合同 A' } })
  const selectedContext = vue.ref(null)
  const warnings: string[] = []
  function startWatcher() {
    const start = view.indexOf('watch(() => [route.query.contractId, route.query.jobId]')
    const end = view.indexOf('}, { immediate: true })', start) + '}, { immediate: true })'.length
    expect(start).toBeGreaterThan(0)
    return new Function('watch', 'route', 'session', 'selectedContext', 'getAuditStatus', 'ElMessage', 'router',
      transpile(`return ${view.slice(start, end)}`))(
      vue.watch, route, session, selectedContext, api.getAuditStatus,
      { warning: (value: string) => warnings.push(value) }, { replace: async () => {} },
    ) as () => void
  }
  function unmount() {
    const start = view.indexOf('onBeforeUnmount(() => {')
    const end = view.indexOf('\n})', start) + '\n})'.length
    new Function('onBeforeUnmount', 'session', 'inbox', 'batchStore', transpile(view.slice(start, end)))(
      (callback: () => void) => callback(), session, { stopPolling() {} }, { stopPolling() {} },
    )
  }
  return {
    session, route, warnings, storage, statusRequests, riskRequests, startWatcher, unmount,
    started: (id: number) => started.get(id)!.promise,
    release: (id: number) => risks.get(id)!.resolve([{ id, contract_id: id }]),
    initialAudit, getAuditSignal: () => auditSignal,
    holdStatus: () => { holdStatus = true }, statusGate,
  }
}

test('显式合同路由切换必须加载 B，A 的迟到风险不能覆盖 B', async () => {
  const h = harness()
  const stop = h.startWatcher()
  try {
    await h.started(301)
    expect(h.session.busy).toBe(true)
    h.route.query = { contractId: '302', jobId: '3302', filename: '合同 B' }
    await vue.nextTick()
    await expect.poll(() => h.riskRequests.map(request => request.id)).toEqual([301, 302])
    h.release(302)
    await expect.poll(() => h.session.busy).toBe(false)
    expect(h.session.contractId).toBe(302)
    h.release(301)
    await vue.nextTick()
    await vue.nextTick()
    expect(h.session.contractId).toBe(302)
    expect(h.session.filename).toBe('合同 B')
    expect(h.session.risks.map(risk => risk.contract_id)).toEqual([302])
    expect(h.riskRequests.map(request => request.id)).toEqual([301, 302])
    expect(h.riskRequests[0].signal?.aborted).toBe(true)
    expect(h.warnings).toEqual([])
    expect(JSON.parse(h.storage.get(SESSION_KEYS.completedAudit)!).contractId).toBe(302)
  } finally { stop() }
})

test('状态请求尚未完成时 reset 也会取消，迟到状态不得继续请求风险', async () => {
  const h = harness()
  h.holdStatus()
  const old = h.session.loadCompletedAudit(301, '合同 A', 3301)
  expect(h.statusRequests).toHaveLength(1)
  h.session.reset()
  expect(h.statusRequests[0].signal?.aborted).toBe(true)
  h.statusGate.resolve({ contract_id: 301, job_id: 3301, status: 'done' })
  await old
  expect(h.riskRequests).toEqual([])
  expect(h.session.contractId).toBeNull()
  expect(h.session.busy).toBe(false)
})

test('取消 A 后其迟到 finally 不能提前清除 B 的 busy', async () => {
  const h = harness()
  const old = h.session.loadCompletedAudit(301, '合同 A', 3301)
  await h.started(301)
  h.session.cancelCompletedAuditLoad()
  const current = h.session.loadCompletedAudit(302, '合同 B', 3302)
  await h.started(302)
  h.release(301)
  await old
  expect(h.session.busy).toBe(true)
  expect(h.session.risks).toEqual([])
  h.release(302)
  await current
  expect(h.session.contractId).toBe(302)
  expect(h.session.busy).toBe(false)
})

for (const action of ['reset', 'unmount', 'watcher-stop'] as const) {
  test(`${action} 取消已完成审查加载的状态和风险请求，迟到数据不得恢复会话`, async () => {
    const h = harness()
    const stop = h.startWatcher()
    try {
      await h.started(301)
      const before = h.session.contractId
      if (action === 'reset') h.session.reset()
      else if (action === 'unmount') h.unmount()
      else stop()
      expect(h.riskRequests[0].signal?.aborted).toBe(true)
      expect(h.statusRequests.at(-1)?.signal?.aborted).toBe(true)
      expect(h.session.busy).toBe(false)
      h.release(301)
      await vue.nextTick()
      await vue.nextTick()
      expect(h.session.risks).toEqual([])
      expect(h.session.contractId).toBe(action === 'reset' ? null : before)
      expect(h.storage.has(SESSION_KEYS.completedAudit)).toBe(false)
    } finally { stop() }
  })
}

test('专用取消不影响真实审查，busy 仍阻止切换已完成结果', async () => {
  const h = harness()
  h.session.contractId = 301
  const audit = h.session.runAudit('采购合同')
  await vue.nextTick()
  h.session.cancelCompletedAuditLoad()
  expect(h.getAuditSignal()?.aborted).toBe(false)
  expect(h.session.busy).toBe(true)
  await expect(h.session.loadCompletedAudit(302, '合同 B', 3302)).rejects.toThrow('当前任务处理中')
  h.initialAudit.resolve({ contract_id: 301, job_id: 3301, status: 'done' })
  await h.started(301)
  h.release(301)
  await audit
  expect(h.session.contractId).toBe(301)
  expect(h.session.busy).toBe(false)
})
