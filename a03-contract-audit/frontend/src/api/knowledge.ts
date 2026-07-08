// 知识库接口适配壳：MOCK_ENABLED.knowledge 为真走 mock，否则走后端。
import client from './client'
import { MOCK_ENABLED, mockRespond } from '@/mock'
import {
  KNOWLEDGE_CARDS,
  KNOWLEDGE_STATS,
  type KnowledgeCard,
} from '@/mock/knowledge'

export async function getKnowledgeCards(): Promise<KnowledgeCard[]> {
  if (MOCK_ENABLED.knowledge) {
    return mockRespond(KNOWLEDGE_CARDS, 'knowledge')
  }
  return client.get('/knowledge/cards')
}

export async function getKnowledgeStats(): Promise<typeof KNOWLEDGE_STATS> {
  if (MOCK_ENABLED.knowledge) {
    return mockRespond(KNOWLEDGE_STATS)
  }
  return client.get('/knowledge/stats')
}

/** 导入知识片段到知识库（持久化到后端）。*/
export async function importKnowledge(payload: {
  category: string // law / rule / template / case
  source: string   // 来源/标题
  content: string  // 正文
}): Promise<void> {
  if (MOCK_ENABLED.knowledge) {
    return // mock 模式下无需持久化
  }
  await client.post('/knowledge/import', payload)
}
