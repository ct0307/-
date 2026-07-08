// 风险追问接口适配壳。调用 POST /chat，后端带上风险上下文构造 system prompt。
import client from './client'
import type { RiskOut } from './types'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatRequest {
  risk_context: {
    category: string
    original_text: string
    basis: string
    suggestion: string
    confidence: number
  }
  message: string
  history: ChatMessage[]
}

export interface ChatResponse {
  reply: string
  model: string
}

export async function chatWithRisk(
  risk: Pick<RiskOut, 'category' | 'original_text' | 'basis' | 'suggestion' | 'confidence'>,
  message: string,
  history: ChatMessage[],
): Promise<ChatResponse> {
  return client.post('/chat', {
    risk_context: {
      category: risk.category,
      original_text: risk.original_text,
      basis: risk.basis,
      suggestion: risk.suggestion,
      confidence: risk.confidence,
    },
    message,
    history,
  })
}
