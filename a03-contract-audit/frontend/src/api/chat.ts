// 风险追问接口适配壳。调用 POST /chat，后端带上风险上下文构造 system prompt。
import client from './client'
import type { RiskOut } from './types'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  state?: string
  references?: { evidence_id: string; kind: string }[]
}

export interface ChatRequest {
  risk_id: number
  message: string
}

export interface ChatResponse {
  reply: string
  model: string
  state: string
  references: { evidence_id: string; kind: string }[]
}

export async function chatWithRisk(
  risk: Pick<RiskOut, 'id'>,
  message: string,
): Promise<ChatResponse> {
  return client.post('/chat', {
    risk_id: risk.id,
    message,
  })
}
