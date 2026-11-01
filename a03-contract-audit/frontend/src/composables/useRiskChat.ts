import { onScopeDispose, ref, watch } from 'vue'
import type { ChatMessage, ChatResponse } from '../api/chat'

// 每次独立问答；显示列表只是当前抽屉的记录，不作为模型上下文。
export function useRiskChat(
  risk: () => { id: number } | null,
  visible: () => boolean,
  request: (risk: { id: number }, message: string) => Promise<ChatResponse>,
  onError: () => void,
) {
  const messages = ref<ChatMessage[]>([])
  const userInput = ref('')
  const chatLoading = ref(false)
  let version = 0
  function invalidate() {
    version++
    messages.value = []
    userInput.value = ''
    chatLoading.value = false
  }
  watch([() => risk()?.id, visible], invalidate, { flush: 'sync' })
  onScopeDispose(invalidate)

  async function sendMessage() {
    const text = userInput.value.trim()
    const currentRisk = risk()
    if (!text || !currentRisk || !visible() || chatLoading.value) return
    const expected = version
    messages.value.push({ role: 'user', content: text })
    userInput.value = ''
    chatLoading.value = true
    try {
      const response = await request({ id: currentRisk.id }, text)
      if (version !== expected) return
      messages.value.push({ role: 'assistant', content: response.reply,
        state: response.state, references: response.references })
    } catch {
      if (version !== expected) return
      messages.value.pop()
      userInput.value = text
      onError()
    } finally {
      if (version === expected) chatLoading.value = false
    }
  }
  return { messages, userInput, chatLoading, sendMessage }
}
