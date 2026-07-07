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
