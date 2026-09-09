<script setup lang="ts">
// 法规知识库(RAG)：搜索 + 分类 chip + 4 统计卡 + 卡片网格 + 关键词高亮 + 详情 + 批量导入。
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheck, CircleClose, Loading, Upload } from '@element-plus/icons-vue'
import {
  getKnowledgeCards,
  getKnowledgeStats,
  getKnowledgeDetail,
  importKnowledge,
  importKnowledgeFile,
  previewLegalImport,
  applyLegalImport,
  deleteKnowledge,
} from '@/api/knowledge'
import type { LegalImportPreview, LegalImportResult } from '@/api/knowledge'
import type { KnowledgeCard, KnowledgeCat } from '@/mock/knowledge'
import DemoBadge from '@/components/common/DemoBadge.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const isAdmin = computed(() => auth.role === 'admin')

const cards = ref<KnowledgeCard[]>([])
const stats = ref<{ cat: KnowledgeCat; count: number }[]>([])
const loading = ref(false)
const keyword = ref('')
const activeCat = ref<'全部' | KnowledgeCat>('全部')

// 分页状态
const currentPage = ref(1)
const pageSize = ref(24)
const total = ref(0)

const cats: ('全部' | KnowledgeCat)[] = ['全部', '法律法规', '标准条款', '风险规则', '典型案例']
const catType: Record<string, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  法律法规: 'primary',
  标准条款: 'success',
  风险规则: 'danger',
  典型案例: 'warning',
}

async function load() {
  loading.value = true
  try {
    const cat = activeCat.value === '全部' ? '' : catKeyMap[activeCat.value]
    const [cardsResult, statsResult] = await Promise.all([
      getKnowledgeCards(currentPage.value, pageSize.value, keyword.value.trim(), cat),
      getKnowledgeStats(),
    ])
    cards.value = cardsResult.items
    total.value = cardsResult.total
    stats.value = statsResult
  } catch {
    ElMessage.error('知识库加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(load)

// 搜索防抖：400ms 后重新请求
let _searchTimer: ReturnType<typeof setTimeout> | null = null
watch(keyword, () => {
  if (_searchTimer) clearTimeout(_searchTimer)
  _searchTimer = setTimeout(() => {
    currentPage.value = 1
    load()
  }, 400)
})

function onPageChange(page: number) {
  currentPage.value = page
  load()
}

// 服务端分页+过滤，前端只对当前页做关键词高亮
// highlight 复用 keyword 即可，不需要 filtered computed

// 关键词命中高亮
function highlight(text: string): string {
  const kw = keyword.value.trim()
  if (!kw) return text
  return text.replace(new RegExp(`(${kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'g'), '<mark>$1</mark>')
}

// 详情
const detailOpen = ref(false)
const active = ref<KnowledgeCard | null>(null)
const detailContent = ref('')     // 完整正文（懒加载）
const detailLoading = ref(false)

async function openDetail(c: KnowledgeCard) {
  active.value = c
  detailContent.value = c.desc   // 先显示截断摘要，避免白屏
  detailOpen.value = true
  // 懒加载完整内容
  const numId = parseInt(c.id.replace(/\D/g, ''))
  if (!numId) return
  detailLoading.value = true
  try {
    const detail = await getKnowledgeDetail(numId)
    detailContent.value = detail.content
  } catch {
    // 失败时保留截断摘要，不弹错误
  } finally {
    detailLoading.value = false
  }
}

function copyClause() {
  // 复制完整正文（懒加载后），未加载完则退化为标题+摘要
  const text = [active.value?.title, detailContent.value || active.value?.desc].filter(Boolean).join('\n')
  navigator.clipboard.writeText(text)
    .then(() => ElMessage.success('已复制，可粘贴至合同修改建议'))
    .catch(() => ElMessage.error('复制失败，请手动选中文本'))
}

// K2：知识条目删除（仅 admin）
async function delCard(c: KnowledgeCard) {
  const numId = parseInt(c.id.replace(/\D/g, ''))
  if (!numId) return
  try {
    await ElMessageBox.confirm(`确认删除「${c.title}」？`, '删除确认', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
    await deleteKnowledge(numId)
    await load()
    ElMessage.success('已删除')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

// 前端分类名 → 后端 category 英文键
const catKeyMap: Record<KnowledgeCat, string> = {
  法律法规: 'law',
  标准条款: 'template',
  风险规则: 'rule',
  典型案例: 'case',
}

// —— 单条添加 ——
const addOpen = ref(false)
const addSaving = ref(false)
const form = ref({ title: '', cat: '法律法规' as KnowledgeCat, desc: '' })

async function submitAdd() {
  if (!form.value.title || !form.value.desc) {
    ElMessage.warning('请填写标题和摘要')
    return
  }
  addSaving.value = true
  try {
    await importKnowledge({
      category: catKeyMap[form.value.cat],
      source: form.value.title,
      content: form.value.desc,
    })
    await load()
    addOpen.value = false
    form.value = { title: '', cat: '法律法规', desc: '' }
    ElMessage.success('已入库')
  } catch {
    ElMessage.error('入库失败，请重试')
  } finally {
    addSaving.value = false
  }
}

// —— 批量导入文件 ——
const batchOpen = ref(false)
const batchImporting = ref(false)
const overwriteMode = ref(false)   // true = 先删同名旧切片再入库
type ImportState = 'idle' | 'previewing' | 'generic-ready' | 'legal-ready' | 'applying' | 'success' | 'error'
const importState = ref<ImportState>('idle')
const legalFile = ref<File | null>(null)
const legalPreview = ref<LegalImportPreview | null>(null)
const legalResult = ref<LegalImportResult | null>(null)
const legalError = ref('')
const importBusy = computed(() => batchImporting.value || ['previewing', 'applying'].includes(importState.value))
const isLegalFlow = computed(() => legalPreview.value?.candidate === true)
const legalAcceptancePassed = computed(() => Boolean(
  legalResult.value?.first_article_ok
  && legalResult.value?.article_585_ok
  && legalResult.value?.last_article_ok,
))

// 英文分类 key → 中文标签（用于展示识别结果）
const catLabelMap: Record<string, KnowledgeCat> = {
  law: '法律法规',
  template: '标准条款',
  rule: '风险规则',
  case: '典型案例',
}

// 文件队列状态
interface FileItem {
  file: File
  status: 'pending' | 'importing' | 'done' | 'error'
  chunks: number
  skipped: number
  mode: 'article' | 'clause' | 'paragraph' | 'empty' | ''
  detectedCat: string
  filteredPH: number   // 被过滤的占位符条文数
  error: string
}
const fileItems = ref<FileItem[]>([])
const totalImported = computed(() => fileItems.value.reduce((s, f) => s + f.chunks, 0))
const doneCount = computed(() => fileItems.value.filter((f) => f.status === 'done').length)

async function onBatchFileChange(file: { raw: File }) {
  await addFileToQueue(file.raw)
}

function removeFile(idx: number) {
  fileItems.value.splice(idx, 1)
  if (!fileItems.value.length) importState.value = 'idle'
}

async function startBatchImport() {
  if (isLegalFlow.value) {
    await startLegalImport()
    return
  }
  const pending = fileItems.value.filter((f) => f.status === 'pending')
  if (!pending.length) return
  batchImporting.value = true
  importState.value = 'applying'
  for (const item of pending) {
    item.status = 'importing'
    try {
      const res = await importKnowledgeFile(item.file, 'auto', overwriteMode.value)
      item.chunks = res.imported_chunks
      item.skipped = res.skipped_duplicates
      item.mode = res.split_mode
      item.detectedCat = catLabelMap[res.category] ?? res.category
      item.filteredPH = res.filtered_placeholders ?? 0
      item.status = 'done'
      if (res.overlap_warning) {
        ElMessage.warning({ message: res.overlap_warning, duration: 6000, showClose: true })
      }
    } catch (e: unknown) {
      item.status = 'error'
      const msg = e instanceof Error ? e.message : String(e)
      item.error = msg.slice(0, 80)
    }
  }
  batchImporting.value = false
  importState.value = fileItems.value.some((f) => f.status === 'error') ? 'error' : 'success'
  if (fileItems.value.every((f) => f.status !== 'pending')) {
    await load()
    ElMessage.success(`批量导入完成，共入库 ${totalImported.value} 个切片`)
  }
}

function closeBatch() {
  if (importBusy.value) return
  batchOpen.value = false
  fileItems.value = []
  overwriteMode.value = false
  importState.value = 'idle'
  legalFile.value = null
  legalPreview.value = null
  legalResult.value = null
  legalError.value = ''
}

// —— 拖拽区（支持文件 + 文件夹）——
const isDragging = ref(false)
const ACCEPTED_EXTS = new Set(['.txt', '.docx', '.pdf'])

function enqueueGenericFile(file: File) {
  fileItems.value.push({
    file, status: 'pending', chunks: 0, skipped: 0,
    mode: '', detectedCat: '', filteredPH: 0, error: '',
  })
  importState.value = 'generic-ready'
}

async function addFileToQueue(file: File) {
  const ext = '.' + (file.name.split('.').pop() ?? '').toLowerCase()
  if (!ACCEPTED_EXTS.has(ext)) return
  if (fileItems.value.some((f) => f.file.name === file.name) || legalFile.value?.name === file.name) return

  if (!isAdmin.value) {
    enqueueGenericFile(file)
    return
  }

  importState.value = 'previewing'
  legalError.value = ''
  legalResult.value = null
  try {
    const preview = await previewLegalImport(file)
    if (!preview.candidate) {
      enqueueGenericFile(file)
      return
    }
    if (fileItems.value.length) {
      fileItems.value = []
      ElMessage.warning('权威法源需单独导入，已清空普通文件队列')
    }
    legalFile.value = file
    legalPreview.value = preview
    if (preview.allowed && preview.token) {
      importState.value = 'legal-ready'
    } else {
      legalError.value = preview.errors.join('；') || '文件未通过权威法源校验'
      importState.value = 'error'
    }
  } catch (e: unknown) {
    legalFile.value = file
    legalPreview.value = null
    legalError.value = e instanceof Error ? e.message : String(e)
    importState.value = 'error'
  }
}

function clearLegalFile() {
  if (importBusy.value) return
  legalFile.value = null
  legalPreview.value = null
  legalResult.value = null
  legalError.value = ''
  importState.value = fileItems.value.length ? 'generic-ready' : 'idle'
}

async function startLegalImport() {
  const file = legalFile.value
  const preview = legalPreview.value
  if (!file || !preview?.allowed || !preview.token) return
  try {
    await ElMessageBox.confirm(
      `将原子替换现有 ${preview.replace_article_count} 条父法条和 ${preview.replace_chunk_count} 个子切片，其他知识不受影响。是否继续？`,
      '确认替换权威法源',
      { type: 'warning', confirmButtonText: '确认替换', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  importState.value = 'applying'
  legalError.value = ''
  try {
    legalResult.value = await applyLegalImport(file, preview.token)
    importState.value = 'success'
    await load()
    ElMessage.success('权威法源已完成原子替换')
  } catch (e: unknown) {
    legalError.value = e instanceof Error ? e.message : String(e)
    importState.value = 'error'
  }
}

/** 递归读取 FileSystemEntry，一级文件夹展开，不再深入子目录。 */
async function readEntries(entries: FileSystemEntry[]): Promise<File[]> {
  const files: File[] = []
  for (const entry of entries) {
    if (entry.isFile) {
      const file = await new Promise<File>((res, rej) =>
        (entry as FileSystemFileEntry).file(res, rej),
      )
      files.push(file)
    } else if (entry.isDirectory) {
      // 展开一级文件夹
      const reader = (entry as FileSystemDirectoryEntry).createReader()
      const children = await new Promise<FileSystemEntry[]>((res, rej) =>
        reader.readEntries(res, rej),
      )
      for (const child of children) {
        if (child.isFile) {
          const file = await new Promise<File>((res, rej) =>
            (child as FileSystemFileEntry).file(res, rej),
          )
          files.push(file)
        }
      }
    }
  }
  return files
}

function onDragOver(e: DragEvent) {
  e.preventDefault()
  isDragging.value = true
}

function onDragLeave(e: DragEvent) {
  // 只在离开整个拖拽区时清除，忽略内部子元素切换
  const related = e.relatedTarget as Node | null
  if (!(e.currentTarget as HTMLElement).contains(related)) {
    isDragging.value = false
  }
}

async function onDrop(e: DragEvent) {
  e.preventDefault()
  isDragging.value = false
  if (!e.dataTransfer || batchImporting.value) return

  const entries: FileSystemEntry[] = []
  for (const item of e.dataTransfer.items) {
    const entry = item.webkitGetAsEntry()
    if (entry) entries.push(entry)
  }
  const files = await readEntries(entries)
  for (const file of files) await addFileToQueue(file)
}

/** 单文件重试：重置状态后重新调接口。 */
async function retryFile(item: FileItem) {
  item.status = 'importing'
  item.error = ''
  item.chunks = 0
  item.skipped = 0
  item.mode = ''
  item.detectedCat = ''
  item.filteredPH = 0
  try {
    const res = await importKnowledgeFile(item.file, 'auto')
    item.chunks = res.imported_chunks
    item.skipped = res.skipped_duplicates
    item.mode = res.split_mode
    item.detectedCat = catLabelMap[res.category] ?? res.category
    item.status = 'done'
  } catch (e: unknown) {
    item.status = 'error'
    const msg = e instanceof Error ? e.message : String(e)
    item.error = msg.slice(0, 80)
  }
}

/** 分类 chip 切换：重置到第一页并重新拉取。 */
function onCatClick(cat: '全部' | KnowledgeCat) {
  activeCat.value = cat
  currentPage.value = 1
  load()
}
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <div class="search-cats">
        <el-input
          v-model="keyword"
          placeholder="搜索法规、条款、案例..."
          :prefix-icon="'Search'"
          style="width: 260px"
          clearable
        />
        <div class="chips">
          <button
            v-for="c in cats"
            :key="c"
            :class="{ active: activeCat === c }"
            @click="onCatClick(c)"
          >{{ c }}</button>
        </div>
      </div>
      <div class="tool-right">
        <DemoBadge module="knowledge" />
        <el-button :icon="Upload" @click="batchOpen = true">导入文件</el-button>
        <el-button type="primary" :icon="'Plus'" @click="addOpen = true">添加知识</el-button>
      </div>
    </div>

    <section class="stat-row">
      <article v-for="s in stats" :key="s.cat" class="stat-card">
        <span>{{ s.cat }}</span>
        <strong class="mono">{{ s.count.toLocaleString() }}</strong>
      </article>
    </section>

    <el-empty v-if="!cards.length" description="未找到匹配的知识条目" />
    <section v-else class="card-grid">
      <article v-for="c in cards" :key="c.id" class="k-card" @click="openDetail(c)">
        <div class="k-head">
          <el-tag :type="catType[c.cat]" size="small">{{ c.cat }}</el-tag>
          <span class="k-date mono">{{ c.date }}</span>
          <!-- K2：仅 admin 可见删除按钮，阻止冒泡避免触发详情弹窗 -->
          <el-button
            v-if="isAdmin"
            link
            type="danger"
            size="small"
            :icon="'Delete'"
            style="margin-left: auto"
            @click.stop="delCard(c)"
          />
        </div>
        <h3 v-html="highlight(c.title)" />
        <p class="k-desc" v-html="highlight(c.desc)" />
        <div class="k-chips">
          <span v-for="t in c.chips" :key="t">{{ t }}</span>
        </div>
      </article>
    </section>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="pagination-row">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next, total"
        :pager-count="5"
        @current-change="onPageChange"
      />
    </div>

    <!-- 详情 -->
    <el-dialog v-model="detailOpen" :title="active?.title" width="620px">
      <template v-if="active">
        <el-tag :type="catType[active.cat]" size="small" style="margin-bottom: 12px">{{ active.cat }}</el-tag>
        <div v-loading="detailLoading" style="min-height: 60px">
          <p class="detail-desc">{{ detailContent }}</p>
        </div>
        <div class="k-chips">
          <span v-for="t in active.chips" :key="t">{{ t }}</span>
        </div>
      </template>
      <template #footer>
        <el-button @click="detailOpen = false">关闭</el-button>
        <el-button type="primary" @click="copyClause">复制条文</el-button>
      </template>
    </el-dialog>

    <!-- 单条添加 -->
    <el-dialog v-model="addOpen" title="添加知识" width="560px">
      <el-form label-width="72px">
        <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.cat" style="width: 100%">
            <el-option v-for="c in cats.filter((x) => x !== '全部')" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="摘要">
          <el-input v-model="form.desc" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addOpen = false">取消</el-button>
        <el-button type="primary" :loading="addSaving" @click="submitAdd">入库</el-button>
      </template>
    </el-dialog>

    <!-- 批量导入文件 -->
    <el-dialog
      v-model="batchOpen"
      title="批量导入文件"
      width="600px"
      :close-on-click-modal="!importBusy"
      :before-close="closeBatch"
    >
      <!-- 自动识别提示 + 覆盖开关 -->
      <div class="batch-config">
        <el-icon style="color: var(--sage)"><CircleCheck /></el-icon>
        <span class="batch-label">{{ isAdmin ? '自动预检并识别分类' : '自动识别分类' }}</span>
        <span class="batch-hint">权威法源将校验条文结构和文件哈希，普通文件沿用原导入流程</span>
        <div v-if="!isLegalFlow" class="batch-overwrite">
          <el-switch v-model="overwriteMode" size="small" :disabled="importBusy" />
          <span class="batch-hint" style="margin-left:6px">覆盖同名旧数据</span>
        </div>
      </div>

      <!-- 上传区：外层 div 处理文件夹拖拽，el-upload 负责点击选择 -->
      <div
        class="batch-upload"
        :class="{ 'is-dragover': isDragging }"
        @dragover="onDragOver"
        @dragleave="onDragLeave"
        @drop="onDrop"
      >
        <el-upload
          multiple
          :auto-upload="false"
          :show-file-list="false"
          accept=".txt,.docx,.pdf"
          :disabled="importBusy || isLegalFlow"
          :on-change="onBatchFileChange"
          class="batch-upload-inner"
        >
          <el-icon class="el-icon--upload"><Upload /></el-icon>
          <div class="el-upload__text">
            拖拽文件或<em>文件夹</em>到此，或<em>点击选择文件</em>
            <p class="upload-sub">支持 .txt / .docx / .pdf，可多选，支持整个文件夹</p>
          </div>
        </el-upload>
      </div>

      <div v-if="importState === 'previewing'" class="legal-state" aria-live="polite">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在校验文件结构与权威哈希…</span>
      </div>

      <section v-if="isLegalFlow && legalPreview" class="legal-preview" aria-label="权威法源预检结果">
        <div class="legal-preview-head">
          <div>
            <span class="legal-eyebrow">权威法源</span>
            <h3>{{ legalPreview.title }}</h3>
            <p>{{ legalFile?.name }}</p>
          </div>
          <el-tag :type="legalPreview.allowed ? 'success' : 'danger'">
            {{ legalPreview.allowed ? '校验通过' : '禁止导入' }}
          </el-tag>
        </div>

        <dl class="legal-metrics">
          <div><dt>1260 条父法条</dt><dd>{{ legalPreview.article_count }}</dd></div>
          <div><dt>父子切片</dt><dd>{{ legalPreview.chunk_count }}</dd></div>
          <div><dt>替换现有父法条</dt><dd>{{ legalPreview.replace_article_count }}</dd></div>
          <div><dt>替换现有子切片</dt><dd>{{ legalPreview.replace_chunk_count }}</dd></div>
        </dl>

        <div class="legal-hash">
          <span>文件 SHA-256</span>
          <code>{{ legalPreview.file_sha256 }}</code>
          <el-tag size="small" :type="legalPreview.hash_matches ? 'success' : 'danger'">
            {{ legalPreview.hash_matches ? '与官方基准一致' : '与官方基准不一致' }}
          </el-tag>
        </div>
        <el-alert
          v-if="legalError"
          :title="legalError"
          type="error"
          :closable="false"
          show-icon
        />
        <el-button v-if="importState !== 'applying'" link type="danger" @click="clearLegalFile">
          移除文件
        </el-button>
      </section>

      <el-alert
        v-else-if="importState === 'error' && legalError"
        :title="legalError"
        type="error"
        :closable="false"
        show-icon
      />

      <section v-if="legalResult" class="legal-result" aria-label="权威法源导入结果">
        <el-icon><CircleCheck /></el-icon>
        <div>
          <strong>权威法源导入完成</strong>
          <p v-if="legalAcceptancePassed">第 1、585、1260 条均已核验</p>
          <p v-else class="legal-result-warning">第 1、585、1260 条验收未完全通过</p>
          <p>
            {{ legalResult.article_count }} 条父法条 · {{ legalResult.chunk_count }} 个子切片 ·
            复用 {{ legalResult.reused_embeddings }} 个向量 · 重建 {{ legalResult.rebuilt_embeddings }} 个向量
          </p>
        </div>
      </section>

      <!-- 文件列表 -->
      <div v-if="fileItems.length && !isLegalFlow" class="file-list">
        <div v-for="(f, i) in fileItems" :key="f.file.name" class="file-row">
          <el-icon class="file-icon">
            <CircleCheck v-if="f.status === 'done'" class="is-done" />
            <CircleClose v-else-if="f.status === 'error'" class="is-error" />
            <Loading v-else-if="f.status === 'importing'" class="is-loading" />
            <Document v-else />
          </el-icon>
          <span class="file-name">{{ f.file.name }}</span>
          <span v-if="f.status === 'done'" class="file-result done">
            <span v-if="f.detectedCat" class="mode-tag article">{{ f.detectedCat }}</span>
            <span v-if="f.mode === 'article'" class="mode-tag para">法条识别</span>
            <span v-else-if="f.mode === 'clause'" class="mode-tag para">款项切分</span>
            <span v-else-if="f.mode === 'paragraph'" class="mode-tag para">段落切分</span>
            +{{ f.chunks }} 条
            <template v-if="f.skipped"> · 去重 {{ f.skipped }}</template>
            <template v-if="f.filteredPH"> · 过滤占位 {{ f.filteredPH }}</template>
          </span>
          <span v-else-if="f.status === 'error'" class="file-result error" :title="f.error">失败</span>
          <span v-else-if="f.status === 'importing'" class="file-result pending">导入中…</span>
          <span v-else class="file-result pending">待导入</span>
          <!-- 操作按钮：独立 v-if，不参与状态文字的 v-else 链 -->
          <el-button
            v-if="f.status === 'error'"
            link type="primary" size="small"
            @click="retryFile(f)"
          >重试</el-button>
          <el-button
            v-if="f.status === 'pending'"
            link type="danger" size="small"
            @click="removeFile(i)"
          >移除</el-button>
        </div>
      </div>

      <!-- 汇总 -->
      <div v-if="fileItems.length && doneCount > 0" class="batch-summary">
        已完成 {{ doneCount }} / {{ fileItems.length }} 个文件，入库 {{ totalImported }} 个切片
      </div>

      <template #footer>
        <el-button :disabled="importBusy" @click="closeBatch">关闭</el-button>
        <el-button
          type="primary"
          :loading="importState === 'applying'"
          :disabled="isLegalFlow
            ? importState !== 'legal-ready'
            : !fileItems.some((f) => f.status === 'pending')"
          @click="startBatchImport"
        >
          {{ isLegalFlow ? '应用权威法源' : '开始导入' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.search-cats {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.chips {
  display: flex;
  gap: 6px;
}
.chips button {
  padding: 5px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-pill);
  background: var(--ink-2);
  color: var(--ivory-dim);
  cursor: pointer;
  font-size: 13px;
}
.chips button.active {
  background: var(--brass);
  color: var(--on-brass);
  border-color: var(--brass);
}
.tool-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.stat-card {
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  padding: 16px 20px;
}
.stat-card span {
  font-size: 13px;
  color: var(--ivory-dim);
}
.stat-card strong {
  display: block;
  font-size: 26px;
  color: var(--brass);
  margin-top: 6px;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.k-card {
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  padding: 16px;
  cursor: pointer;
  transition: border-color 0.2s var(--ease), background-color 0.2s var(--ease);
}
.k-card:hover {
  border-color: var(--brass);
  background: var(--ink-3);
}
.k-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.k-date {
  font-size: 11px;
  color: var(--muted);
}
.k-card h3 {
  margin: 10px 0 6px;
  font-size: 15px;
  line-height: 1.4;
}
.k-desc {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--ivory-dim);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.k-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.k-chips span {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--r-xs);
  background: var(--brass-soft);
  color: var(--brass);
  font-family: var(--mono);
}
.detail-desc {
  line-height: 1.8;
  color: var(--ivory);
  margin: 0 0 14px;
}

/* 批量导入弹窗 */
.batch-config {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.batch-overwrite {
  display: flex;
  align-items: center;
  margin-left: auto;
}
.batch-label {
  font-size: 13px;
  color: var(--ivory-dim);
  white-space: nowrap;
}
.batch-hint {
  font-size: 12px;
  color: var(--muted);
}
.batch-upload {
  border: 2px dashed var(--line);
  border-radius: var(--r-md);
  margin-bottom: 16px;
  transition: border-color 0.2s, background 0.2s;
  cursor: pointer;
}
.batch-upload:hover {
  border-color: var(--brass);
}
.batch-upload.is-dragover {
  border-color: var(--brass);
  background: var(--brass-soft);
}
/* 让 el-upload 内部铺满外层 div，居中显示图标+文字 */
.batch-upload :deep(.el-upload) {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 148px;
  padding: 28px 20px;
  box-sizing: border-box;
}
.batch-upload :deep(.el-icon--upload) {
  font-size: 44px;
  color: var(--brass);
  margin-bottom: 10px;
  opacity: 0.75;
}
.batch-upload :deep(.el-upload__text) {
  text-align: center;
  color: var(--ivory-dim);
  font-size: 14px;
  line-height: 1.6;
}
.batch-upload :deep(.el-upload__text em) {
  color: var(--brass);
  font-style: normal;
}
.upload-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--muted);
}
.file-list {
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  overflow: hidden;
  margin-bottom: 12px;
}
.file-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  font-size: 13px;
}
.file-row:last-child {
  border-bottom: none;
}
.file-icon {
  font-size: 16px;
  color: var(--muted);
  flex: none;
}
.file-icon .is-done { color: var(--sage); }
.file-icon .is-error { color: var(--seal); }
.file-name {
  flex: 1;
  color: var(--ivory);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.file-result {
  font-size: 12px;
  font-family: var(--mono);
  white-space: nowrap;
}
.file-result.done  { color: var(--sage); display: inline-flex; align-items: center; gap: 6px; }
.file-result.error { color: var(--seal); }
.file-result.pending { color: var(--muted); }
.mode-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 3px;
}
.mode-tag.article { background: var(--brass-soft); color: var(--brass); }
.mode-tag.para { background: var(--ink-3, rgba(255,255,255,0.06)); color: var(--ivory-dim); }
.batch-summary {
  font-size: 13px;
  color: var(--sage);
  text-align: right;
  padding: 4px 0;
}
.legal-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 52px;
  color: var(--ivory-dim);
  font-size: 13px;
}
.legal-preview,
.legal-result {
  border-top: 1px solid var(--line);
  padding: 16px 0 0;
  margin-top: 4px;
}
.legal-preview-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
.legal-preview-head h3 {
  margin: 3px 0;
  font-size: 16px;
}
.legal-preview-head p,
.legal-result p {
  margin: 2px 0;
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.legal-eyebrow {
  color: var(--brass);
  font-size: 11px;
}
.legal-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  margin: 0 0 14px;
  background: var(--line);
  border: 1px solid var(--line);
}
.legal-metrics div {
  background: var(--ink-2);
  padding: 10px 12px;
}
.legal-metrics dt {
  color: var(--muted);
  font-size: 11px;
}
.legal-metrics dd {
  margin: 3px 0 0;
  color: var(--ivory);
  font-family: var(--mono);
  font-size: 16px;
}
.legal-hash {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 11px;
  color: var(--muted);
}
.legal-hash code {
  overflow-wrap: anywhere;
  color: var(--ivory-dim);
}
.legal-result {
  display: flex;
  gap: 10px;
  color: var(--sage);
}
.legal-result strong {
  color: var(--ivory);
  font-size: 14px;
}
.legal-result .legal-result-warning {
  color: var(--seal);
}
.pagination-row {
  display: flex;
  justify-content: center;
  padding: 20px 0 8px;
}
:deep(mark) {
  background: var(--amber-soft);
  color: var(--amber);
  padding: 0 2px;
  border-radius: 2px;
}
@media (max-width: 1180px) {
  .stat-row { grid-template-columns: 1fr 1fr; }
  .card-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 720px) {
  .stat-row,
  .card-grid {
    grid-template-columns: 1fr;
  }
  .search-cats,
  .tool-right {
    width: 100%;
  }
  .chips {
    max-width: 100%;
    overflow-x: auto;
  }
  .legal-metrics {
    grid-template-columns: 1fr;
  }
  .legal-hash {
    grid-template-columns: 1fr;
  }
}
</style>
