// 知识库接口适配壳：MOCK_ENABLED.knowledge 为真走 mock，否则走后端。
import client from './client'
import { MOCK_ENABLED, mockRespond } from '@/mock'
import {
  KNOWLEDGE_CARDS,
  KNOWLEDGE_STATS,
  type KnowledgeCard,
} from '@/mock/knowledge'

/** 分页结果包装。 */
export interface KnowledgeCardsResult {
  total: number
  page: number
  size: number
  items: KnowledgeCard[]
}

export async function getKnowledgeCards(
  page = 1,
  size = 24,
  q = '',
  category = '',
): Promise<KnowledgeCardsResult> {
  if (MOCK_ENABLED.knowledge) {
    const all = KNOWLEDGE_CARDS.filter((c) => {
      const catOk = !category || c.cat === category
      const qOk = !q || c.title.includes(q) || c.desc.includes(q)
      return catOk && qOk
    })
    const start = (page - 1) * size
    return mockRespond(
      { total: all.length, page, size, items: all.slice(start, start + size) },
      'knowledge',
    )
  }
  return client.get('/knowledge/cards', { params: { page, size, q, category } })
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

/** 批量导入结果：入库切片数 + 去重跳过数 + 切片模式（法条/段落）+ 自动识别分类。*/
export interface ImportFileResult {
  source: string
  category: string
  detected_category: string | null
  auto_detected: boolean
  imported_chunks: number
  skipped_duplicates: number
  filtered_placeholders: number   // 被过滤的占位符条文数
  split_mode: 'article' | 'clause' | 'paragraph' | 'empty'
  article_count: number
  overlap_warning: string | null  // 同分类已有大量其他来源时的预警
  scope_mode: string              // global / scoped / unclassified
  retrievable: boolean            // false 表示导入的知识不参与检索
  scope_warning: string | null    // unclassified（导入即死数据）时的预警
}

export interface LegalImportPreview {
  candidate: boolean
  allowed: boolean
  source_id: string | null
  title: string | null
  file_sha256: string
  hash_matches: boolean
  article_count: number
  chunk_count: number
  replace_article_count: number
  replace_chunk_count: number
  errors: string[]
  token: string | null
}

export interface LegalImportResult {
  source_id: string
  article_count: number
  chunk_count: number
  reused_embeddings: number
  rebuilt_embeddings: number
  embedding_model: string
  embedding_dimension: number
  embedding_signature: string
  first_article_ok: boolean
  article_585_ok: boolean
  last_article_ok: boolean
}

/** 单条知识库详情，返回完整 content（不截断）。 */
export interface KnowledgeDetail {
  id: number
  title: string
  cat: string
  content: string
  date: string
}

export async function getKnowledgeDetail(numericId: number): Promise<KnowledgeDetail> {
  return client.get(`/knowledge/${numericId}`)
}

/** 删除知识库条目（仅 admin，id 为后端数字主键，前端卡片 id 格式为 "K01"）。*/
export async function deleteKnowledge(numericId: number): Promise<void> {
  if (MOCK_ENABLED.knowledge) return
  await client.delete(`/knowledge/${numericId}`)
}
export async function importKnowledgeFile(
  file: File,
  category: string,
  overwrite = false,
): Promise<ImportFileResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('category', category)
  form.append('overwrite', String(overwrite))
  // 知识库文件可能含大量条文，embedding 耗时长，单独设 180s 超时
  return client.post('/knowledge/import-file', form, { timeout: 180_000 })
}

export async function previewLegalImport(file: File): Promise<LegalImportPreview> {
  const form = new FormData()
  form.append('file', file)
  return client.post('/knowledge/legal-import/preview', form)
}

export async function applyLegalImport(
  file: File,
  token: string,
): Promise<LegalImportResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('token', token)
  return client.post('/knowledge/legal-import/apply', form, { timeout: 600_000 })
}
