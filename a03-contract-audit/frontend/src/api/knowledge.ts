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

/** 批量导入结果：入库切片数 + 去重跳过数 + 切片模式（法条/段落）。*/
export interface ImportFileResult {
  source: string
  category: string
  imported_chunks: number
  skipped_duplicates: number
  split_mode: 'article' | 'paragraph' | 'empty'
  article_count: number
}

/** 上传文件批量导入知识库（txt/docx/pdf → 智能切片向量化）。*/
export async function importKnowledgeFile(
  file: File,
  category: string,
): Promise<ImportFileResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('category', category)
  return client.post('/knowledge/import-file', form)
}
