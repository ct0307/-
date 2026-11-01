import { expect, test } from '@playwright/test'
import { effectScope, ref } from 'vue'
import { useRiskChat } from '../src/composables/useRiskChat'
import type { ChatResponse } from '../src/api/chat'

for (const fails of [false, true]) {
  test(`切换风险后忽略旧请求${fails ? '失败' : '成功'}，不清除新请求状态`, async () => {
    let resolve!: (response: ChatResponse) => void
    let reject!: (error: Error) => void
    const scope = effectScope()
    const risk = ref({ id: 1 })
    const visible = ref(true)
    let errors = 0
    const chat = scope.run(() => useRiskChat(() => risk.value, () => visible.value,
      () => new Promise<ChatResponse>((done, fail) => { resolve = done; reject = fail }),
      () => { errors++ }))!
    chat.userInput.value = '旧问题'
    const pending = chat.sendMessage()
    const oldResolve = resolve
    const oldReject = reject
    risk.value = { id: 2 }
    chat.userInput.value = '新问题'
    const next = chat.sendMessage()
    if (fails) oldReject(new Error('失败'))
    else oldResolve({ reply: '旧回答', model: 'test', state: 'ANSWERED', references: [] })
    await pending
    expect(chat.messages.value.map((m) => m.content)).toEqual(['新问题'])
    expect(chat.chatLoading.value).toBe(true)
    expect(errors).toBe(0)
    resolve({ reply: '新回答', model: 'test', state: 'ANSWERED', references: [] })
    await next
    expect(chat.messages.value.map((m) => m.content)).toEqual(['新问题', '新回答'])
    scope.stop()
  })
}

test('关闭及卸载会使待处理回答失效', async () => {
  let resolve!: (response: ChatResponse) => void
  const visible = ref(true)
  const scope = effectScope()
  const chat = scope.run(() => useRiskChat(() => ({ id: 1 }), () => visible.value,
    () => new Promise<ChatResponse>((done) => { resolve = done }), () => {}))!
  chat.userInput.value = '问题'
  const pending = chat.sendMessage()
  visible.value = false
  scope.stop()
  resolve({ reply: '迟到回答', model: 'test', state: 'ANSWERED', references: [] })
  await pending
  expect(chat.messages.value).toEqual([])
  expect(chat.chatLoading.value).toBe(false)
})
