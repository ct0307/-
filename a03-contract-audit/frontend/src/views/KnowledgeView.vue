<script setup lang="ts">
// 法规知识库(RAG)：搜索 + 分类 chip + 4 统计卡 + 卡片网格 + 关键词高亮 + 详情 + 批量导入。
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getKnowledgeCards, getKnowledgeStats, importKnowledge, importKnowledgeFile } from '@/api/knowledge'
import type { KnowledgeCard, KnowledgeCat } from '@/mock/knowledge'
import DemoBadge from '@/components/common/DemoBadge.vue'

const cards = ref<KnowledgeCard[]>([])
const stats = ref<{ cat: KnowledgeCat; count: number }[]>([])
const loading = ref(false)
const keyword = ref('')
const activeCat = ref<'全部' | KnowledgeCat>('全部')

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
    ;[cards.value, stats.value] = await Promise.all([getKnowledgeCards(), getKnowledgeStats()])
  } catch {
    ElMessage.error('知识库加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const filtered = computed(() => {
  const kw = keyword.value.trim()
  return cards.value.filter((c) => {
    const catOk = activeCat.value === '全部' || c.cat === activeCat.value
    const kwOk =
      !kw || c.title.includes(kw) || c.desc.includes(kw) || c.chips.some((t) => t.includes(kw))
    return catOk && kwOk
  })
})

// 关键词命中高亮
function highlight(text: string): string {
  const kw = keyword.value.trim()
  if (!kw) return text
  return text.replace(new RegExp(`(${kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'g'), '<mark>$1</mark>')
}

// 详情
const detailOpen = ref(false)
const active = ref<KnowledgeCard | null>(null)
function openDetail(c: KnowledgeCard) {
  active.value = c
  detailOpen.value = true
}

function copyClause() {
  const text = [active.value?.title, active.value?.desc].filter(Boolean).join('\n')
  navigator.clipboard.writeText(text)
    .then(() => ElMessage.success('已复制，可粘贴至合同修改建议'))
    .catch(() => ElMessage.error('复制失败，请手动选中文本'))
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
const batchCat = ref<KnowledgeCat>('法律法规')
const batchImporting = ref(false)

// 文件队列状态
interface FileItem {
  file: File
  status: 'pending' | 'importing' | 'done' | 'error'
  chunks: number
  error: string
}
const fileItems = ref<FileItem[]>([])
const totalImported = computed(() => fileItems.value.reduce((s, f) => s + f.chunks, 0))
const doneCount = computed(() => fileItems.value.filter((f) => f.status === 'done').length)

function onBatchFileChange(file: { raw: File }) {
  // el-upload 回调：添加到队列（去重）
  if (fileItems.value.some((f) => f.file.name === file.raw.name)) return
  fileItems.value.push({ file: file.raw, status: 'pending', chunks: 0, error: '' })
}

function removeFile(idx: number) {
  fileItems.value.splice(idx, 1)
}

async function startBatchImport() {
  const pending = fileItems.value.filter((f) => f.status === 'pending')
  if (!pending.length) return
  batchImporting.value = true
  const cat = catKeyMap[batchCat.value]
  for (const item of pending) {
    item.status = 'importing'
    try {
      const res = await importKnowledgeFile(item.file, cat)
      item.chunks = res.imported_chunks
      item.status = 'done'
    } catch (e: unknown) {
      item.status = 'error'
      const msg = e instanceof Error ? e.message : String(e)
      item.error = msg.slice(0, 80)
    }
  }
  batchImporting.value = false
  // 全部完成后刷新
  if (fileItems.value.every((f) => f.status !== 'pending')) {
    await load()
    ElMessage.success(`批量导入完成，共入库 ${totalImported.value} 个切片`)
  }
}

function closeBatch() {
  if (batchImporting.value) return
  batchOpen.value = false
  fileItems.value = []
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
            @click="activeCat = c"
          >{{ c }}</button>
        </div>
      </div>
      <div class="tool-right">
        <DemoBadge module="knowledge" />
        <el-button :icon="'Upload'" @click="batchOpen = true">导入文件</el-button>
        <el-button type="primary" :icon="'Plus'" @click="addOpen = true">添加知识</el-button>
      </div>
    </div>

    <section class="stat-row">
      <article v-for="s in stats" :key="s.cat" class="stat-card">
        <span>{{ s.cat }}</span>
        <strong class="mono">{{ s.count.toLocaleString() }}</strong>
      </article>
    </section>

    <el-empty v-if="!filtered.length" description="未找到匹配的知识条目" />
    <section v-else class="card-grid">
      <article v-for="c in filtered" :key="c.id" class="k-card" @click="openDetail(c)">
        <div class="k-head">
          <el-tag :type="catType[c.cat]" size="small">{{ c.cat }}</el-tag>
          <span class="k-date mono">{{ c.date }}</span>
        </div>
        <h3 v-html="highlight(c.title)" />
        <p class="k-desc" v-html="highlight(c.desc)" />
        <div class="k-chips">
          <span v-for="t in c.chips" :key="t">{{ t }}</span>
        </div>
      </article>
    </section>

    <!-- 详情 -->
    <el-dialog v-model="detailOpen" :title="active?.title" width="620px">
      <template v-if="active">
        <el-tag :type="catType[active.cat]" size="small" style="margin-bottom: 12px">{{ active.cat }}</el-tag>
        <p class="detail-desc">{{ active.desc }}</p>
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
      :close-on-click-modal="!batchImporting"
      :before-close="closeBatch"
    >
      <!-- 分类选择 -->
      <div class="batch-config">
        <span class="batch-label">导入分类</span>
        <el-select v-model="batchCat" size="default" style="width: 160px" :disabled="batchImporting">
          <el-option v-for="c in cats.filter((x) => x !== '全部')" :key="c" :label="c" :value="c" />
        </el-select>
        <span class="batch-hint">所有文件将归入此分类</span>
      </div>

      <!-- 上传区 -->
      <el-upload
        multiple
        :auto-upload="false"
        :show-file-list="false"
        accept=".txt,.docx,.pdf"
        :disabled="batchImporting"
        :on-change="onBatchFileChange"
        drag
        class="batch-upload"
      >
        <el-icon class="el-icon--upload"><Upload /></el-icon>
        <div class="el-upload__text">
          拖拽文件到此，或<em>点击选择</em>
          <p class="upload-sub">支持 .txt / .docx / .pdf，可多选</p>
        </div>
      </el-upload>

      <!-- 文件列表 -->
      <div v-if="fileItems.length" class="file-list">
        <div v-for="(f, i) in fileItems" :key="f.file.name" class="file-row">
          <el-icon class="file-icon">
            <CircleCheck v-if="f.status === 'done'" class="is-done" />
            <CircleClose v-else-if="f.status === 'error'" class="is-error" />
            <Loading v-else-if="f.status === 'importing'" class="is-loading" />
            <Document v-else />
          </el-icon>
          <span class="file-name">{{ f.file.name }}</span>
          <span v-if="f.status === 'done'" class="file-result done">+{{ f.chunks }} 条</span>
          <span v-else-if="f.status === 'error'" class="file-result error" :title="f.error">失败</span>
          <span v-else-if="f.status === 'importing'" class="file-result pending">导入中…</span>
          <span v-else class="file-result pending">待导入</span>
          <el-button
            v-if="f.status === 'pending'"
            link
            type="danger"
            size="small"
            @click="removeFile(i)"
          >移除</el-button>
        </div>
      </div>

      <!-- 汇总 -->
      <div v-if="fileItems.length && doneCount > 0" class="batch-summary">
        已完成 {{ doneCount }} / {{ fileItems.length }} 个文件，入库 {{ totalImported }} 个切片
      </div>

      <template #footer>
        <el-button :disabled="batchImporting" @click="closeBatch">关闭</el-button>
        <el-button
          type="primary"
          :loading="batchImporting"
          :disabled="!fileItems.some((f) => f.status === 'pending')"
          @click="startBatchImport"
        >
          开始导入
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
  gap: 16px;
  margin-bottom: 18px;
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
  border-radius: 20px;
  background: var(--ink-2);
  color: var(--ivory-dim);
  cursor: pointer;
  font-size: 13px;
}
.chips button.active {
  background: var(--brass);
  color: #fff;
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
  border-radius: var(--r-lg);
  padding: 16px 20px;
  box-shadow: var(--shadow-sm);
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
  border-radius: var(--r-lg);
  padding: 16px;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: border-color 0.2s var(--ease), transform 0.2s var(--ease);
}
.k-card:hover {
  border-color: var(--brass);
  transform: translateY(-2px);
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
  border-radius: 4px;
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
  margin-bottom: 16px;
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
.file-result.done  { color: var(--sage); }
.file-result.error { color: var(--seal); }
.file-result.pending { color: var(--muted); }
.batch-summary {
  font-size: 13px;
  color: var(--sage);
  text-align: right;
  padding: 4px 0;
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
</style>
