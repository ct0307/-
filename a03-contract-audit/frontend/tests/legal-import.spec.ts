import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'


const apiSource = readFileSync(
  fileURLToPath(new URL('../src/api/knowledge.ts', import.meta.url)),
  'utf8',
)
const viewSource = readFileSync(
  fileURLToPath(new URL('../src/views/KnowledgeView.vue', import.meta.url)),
  'utf8',
)


test('defines authoritative legal preview and apply API contracts', () => {
  expect(apiSource).toContain('export interface LegalImportPreview')
  expect(apiSource).toContain('export interface LegalImportResult')
  expect(apiSource).toContain("client.post('/knowledge/legal-import/preview'")
  expect(apiSource).toContain("client.post('/knowledge/legal-import/apply'")
})


test('keeps a fixed import state machine and generic import fallback', () => {
  expect(viewSource).toContain("type ImportState = 'idle' | 'previewing' | 'generic-ready' | 'legal-ready' | 'applying' | 'success' | 'error'")
  expect(viewSource).toContain('preview.candidate')
  expect(viewSource).toContain('importKnowledgeFile(item.file')
})


test('shows controlled legal replacement evidence without fake progress', () => {
  expect(viewSource).toContain('1260 条父法条')
  expect(viewSource).toContain('文件 SHA-256')
  expect(viewSource).toContain('替换现有')
  expect(viewSource).toContain('第 1、585、1260 条均已核验')
  expect(viewSource).not.toContain('legalImportProgress')
})
