<script setup lang="ts">
// 完整解析正文与风险联动；只对精确匹配的引用进行定位。
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getContractDocument, parseContract } from '@/api/contract'
import type { ContractDocument, RiskOut } from '@/api/types'
import { useAuditSessionStore } from '@/stores/audit-session'

const props = defineProps<{ modelValue: boolean; risks: RiskOut[]; filename: string; contractId: number | null; allowParse?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean] }>()

const session = useAuditSessionStore()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const applyingId = ref<number | null>(null)
const documentData = ref<ContractDocument | null>(null)
const loading = ref(false)
const loadError = ref('')
const parsing = ref(false)
const parseError = ref('')
let parseVersion = 0
const selectedId = ref<number | null>(null)
const matchIndex = ref(0)
let requestVersion = 0
let controller: AbortController | null = null

function cancelLoad() {
  requestVersion++
  controller?.abort()
  controller = null
}

async function loadDocument() {
  cancelLoad()
  const version = requestVersion
  const id = props.contractId
  documentData.value = null
  loadError.value = ''
  if (!props.modelValue || !id) { loading.value = false; return }
  controller = new AbortController()
  const request = controller
  loading.value = true
  try {
    const result = await getContractDocument(id, request.signal)
    if (version !== requestVersion) return
    if (result.contract_id !== id || typeof result.text !== 'string') throw new Error('正文响应无效')
    documentData.value = result
  } catch {
    if (version === requestVersion && !request.signal.aborted) loadError.value = '正文加载失败，请重试。'
  } finally {
    if (version === requestVersion) { loading.value = false; controller = null }
  }
}

watch(() => [props.modelValue, props.contractId] as const, () => {
  parseVersion++
  parsing.value = false
  parseError.value = ''
  selectedId.value = props.risks[0]?.id ?? null
  matchIndex.value = 0
  void loadDocument()
}, { immediate: true })
onBeforeUnmount(cancelLoad)

async function parseDocument() {
  const id = props.contractId
  if (!props.allowParse || !id || parsing.value) return
  const version = ++parseVersion
  parsing.value = true; parseError.value = ''
  try {
    await parseContract(id)
    if (version === parseVersion) await loadDocument()
  } catch (error) {
    if (version === parseVersion) parseError.value = error instanceof Error ? error.message : '正文解析失败，请重试。'
  } finally {
    if (version === parseVersion) parsing.value = false
  }
}

const selectedRisk = computed(() => props.risks.find(r => r.id === selectedId.value))
const documentText = computed(() => documentData.value?.text ?? '')
const matches = computed(() => {
  const quote = selectedRisk.value?.original_text?.trim()
  if (!quote) return []
  const found: { start: number; end: number }[] = []
  let offset = 0
  while (offset < documentText.value.length) {
    const start = documentText.value.indexOf(quote, offset)
    if (start < 0) break
    found.push({ start, end: start + quote.length })
    offset = start + quote.length
  }
  return found
})
const currentMatch = computed(() => matches.value[matchIndex.value])
const textParts = computed(() => {
  const match = currentMatch.value
  return match
    ? [documentText.value.slice(0, match.start), documentText.value.slice(match.start, match.end), documentText.value.slice(match.end)]
    : [documentText.value, '', '']
})

async function applyAsSuggestion(risk: RiskOut) {
  if (risk.review_status === 'to_modify' || applyingId.value !== null) return
  applyingId.value = risk.id
  try {
    const { value } = await ElMessageBox.prompt('请说明修改建议的复核判断和适用条件', '填写复核意见', {
      inputType: 'textarea', inputValidator: value => !!value?.trim() || '复核意见不能为空',
      confirmButtonText: '保存复核意见', cancelButtonText: '取消',
    })
    await session.setRiskStatus(risk, 'to_modify', value)
    ElMessage.success('已标记为需修改，复核意见已保存')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('操作失败')
  } finally {
    applyingId.value = null
  }
}

const levelMeta: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { label: '高', type: 'danger' },
  medium: { label: '中', type: 'warning' },
  low: { label: '低', type: 'info' },
}

const docRef = ref<HTMLElement>()
async function scrollToRisk(id: number) {
  selectedId.value = id
  matchIndex.value = 0
  await scrollToMatch()
}
async function scrollToMatch() {
  await nextTick()
  const container = docRef.value
  const mark = container?.querySelector('mark')
  if (!container || !mark) return
  container.scrollTo({
    top: container.scrollTop + mark.getBoundingClientRect().top - container.getBoundingClientRect().top - container.clientHeight / 2,
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
  })
}
async function nextMatch() {
  matchIndex.value = (matchIndex.value + 1) % matches.value.length
  await scrollToMatch()
}
</script>

<template>
  <el-dialog v-model="visible" :title="`合同原文与风险批注 · ${filename}`" width="min(1120px, calc(100vw - 24px))" top="4vh" class="document-review-dialog">
    <p class="reader-note">以下为文件解析正文。版式与原文件可能不同；扫描识别、缺页或引用差异需要人工核对。</p>
    <el-alert v-if="documentData?.requires_review || documentData?.missing_pages?.length" type="warning" :closable="false"
      :title="documentData.review_reason || '解析结果需要人工核对'" :description="documentData.missing_pages?.length ? `缺失页码：${documentData.missing_pages.join('、')}` : undefined" />
    <div class="fulltext">
      <article ref="docRef" class="doc" role="region" aria-label="完整解析正文" tabindex="0" :aria-busy="loading">
        <p v-if="loading" class="doc-empty" role="status">正在加载解析正文…</p>
        <div v-else-if="loadError || !documentText" class="doc-empty" role="status">
          <p>{{ loadError || documentData?.message || '请先选择一份合同。' }}</p>
          <el-button v-if="contractId" :disabled="parsing" @click="loadDocument">重新加载正文</el-button>
          <el-button v-if="contractId && allowParse && !loadError" type="primary" :loading="parsing" @click="parseDocument">解析材料正文</el-button>
          <p v-if="parseError" role="alert">{{ parseError }}</p>
        </div>
        <template v-else>
          <div class="doc-hint">完整解析正文 · {{ documentText.length }} 字符</div>
          <div class="doc-text"><span>{{ textParts[0] }}</span><mark v-if="currentMatch" class="ann-sentence">{{ textParts[1] }}</mark><span>{{ textParts[2] }}</span></div>
        </template>
      </article>

      <aside class="ann-list" aria-label="风险批注">
        <div class="ann-head">批注（{{ risks.length }}）</div>
        <p v-if="!risks.length" class="reader-note">暂无风险批注，仍可阅读完整解析正文。</p>
        <div v-if="selectedRisk && documentText" class="match-status" role="status">
          <span v-if="!matches.length">未在解析正文中找到精确引用，请人工核对。</span>
          <template v-else>已定位 {{ matchIndex + 1 }} / {{ matches.length }} 处引用
            <el-button v-if="matches.length > 1" size="small" @click="nextMatch">下一处</el-button>
          </template>
        </div>
        <section
          v-for="r in risks"
          :key="r.id"
          class="ann-item"
          :class="[`lvl-${r.level}`, { selected: selectedId === r.id }]"
        >
          <button type="button" class="ann-locate" :aria-label="`定位风险：${r.category}`" :aria-pressed="selectedId === r.id" @click="scrollToRisk(r.id)">
            <span class="ann-item-head">
            <el-tag :type="levelMeta[r.level].type" size="small">{{ levelMeta[r.level].label }}</el-tag>
            <b>{{ r.category }}</b>
            </span>
            <span class="risk-quote">{{ r.original_text || '该风险缺少引用原文，请人工核对。' }}</span>
          </button>
          <p>{{ r.suggestion }}</p>
          <el-button
            size="small"
            :type="r.review_status === 'to_modify' ? 'success' : 'primary'"
            :loading="applyingId === r.id"
            :disabled="r.review_status === 'to_modify' || applyingId !== null"
            plain
            class="apply-btn"
            @click.stop="applyAsSuggestion(r)"
          >
            {{ r.review_status === 'to_modify' ? '已标记需修改' : '标记需修改' }}
          </el-button>
        </section>
      </aside>
    </div>
  </el-dialog>
</template>

<style scoped>
.fulltext {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);
  gap: 16px;
  height: 66vh;
  margin-top: 12px;
}
.reader-note { color: var(--muted); font-size: 12px; line-height: 1.6; margin: 0 0 10px; }
.doc-text { white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--serif); font-size: 14px; }
.match-status { padding: 10px; margin-bottom: 10px; background: var(--amber-soft); color: var(--ivory); font-size: 12px; line-height: 1.6; }
.ann-locate { display: block; width: 100%; padding: 0; margin: 0 0 10px; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; font: inherit; }
.risk-quote { display: block; font-size: 12px; color: var(--muted); line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.ann-item.selected { border-color: var(--brass); background: var(--amber-soft); }
.ann-locate:focus-visible, .doc:focus-visible { outline: 2px solid var(--brass); outline-offset: 3px; }
.doc {
  min-width: 0;
  overflow-y: auto;
  padding: 24px 28px;
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background-image: repeating-linear-gradient(
    to bottom,
    transparent,
    transparent 31px,
    var(--paper-line) 32px
  );
  line-height: 2;
}
.clause {
  margin-bottom: 18px;
}
.clause h4 {
  margin: 0 0 4px;
  font-family: var(--serif);
  color: var(--ivory);
  font-size: 15px;
}
.clause p {
  margin: 0;
  color: var(--ivory-dim);
  font-family: var(--serif);
}
.ann-list {
  min-width: 0;
  overflow-y: auto;
  padding-right: 4px;
}
.ann-head {
  font-family: var(--serif);
  font-weight: 600;
  color: var(--ivory);
  margin-bottom: 10px;
}
.ann-item {
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: 10px 12px;
  margin-bottom: 10px;
  position: relative;
  transition: border-color 0.2s var(--ease), background-color 0.2s var(--ease);
}
.ann-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: var(--r-sm) 0 0 var(--r-sm);
}
.ann-item.lvl-high::before {
  background: var(--seal);
}
.ann-item.lvl-medium::before {
  background: var(--amber);
}
.ann-item.lvl-low::before {
  background: var(--sage);
}
.ann-item:hover {
  border-color: var(--brass);
}
.ann-item-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.ann-item-head b {
  color: var(--ivory);
  font-size: 13px;
}
.ann-item p {
  margin: 0;
  font-size: 12px;
  color: var(--ivory-dim);
  line-height: 1.5;
}
.apply-btn {
  margin-top: 8px;
  width: 100%;
}
:deep(.ann-sentence) {
  text-decoration: underline wavy var(--seal);
  text-underline-offset: 3px;
  background: var(--seal-soft);
  color: var(--ivory);
  padding: 0 2px;
  border-radius: 2px;
  transition: background 0.3s var(--ease);
}
:deep(.ann-sentence.flash) {
  background: var(--amber-soft);
  animation: flash 1.4s var(--ease);
}
@keyframes flash {
  0%,
  100% {
    background: var(--seal-soft);
  }
  30% {
    background: var(--annotation-highlight);
  }
}
.doc-hint {
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 12px;
  font-family: var(--serif);
}
.doc-empty {
  font-size: 13px;
  color: var(--muted);
  text-align: center;
  padding: 40px 0;
}
.clause-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.clause-head b {
  font-size: 13px;
  color: var(--ivory);
}
.clause.lvl-high { border-left-color: var(--seal); }
.clause.lvl-medium { border-left-color: var(--amber); }
.clause.lvl-low { border-left-color: var(--sage); }
@media (max-width: 760px) {
  .fulltext { grid-template-columns: minmax(0, 1fr); height: auto; gap: 12px; }
  .doc { height: 36vh; min-height: 180px; padding: 16px; }
  .ann-list { max-height: 27vh; padding: 4px; }
}
@media (prefers-reduced-motion: reduce) {
  .ann-item, :deep(.ann-sentence) { transition: none; }
}
</style>
